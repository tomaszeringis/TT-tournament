from typing import List
from fastapi import FastAPI, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import ValidationError
import uvicorn
import httpx
import re
import json
import logging
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager

# Import models and database
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player, Tournament
from tournament_platform.services.ai_engine import AIEngine
from tournament_platform.services.ranking_service import RatingManager
from tournament_platform.services.match_reporting import (
    ReportMatchCommand,
    MatchNotFoundError,
    MatchAlreadyCompletedError,
    InvalidWinnerError,
    report_existing_match,
)
from tournament_platform.services.schemas import (
    MatchResultParseRequest,
    MatchResultParseResponse,
    LeaderboardEntry,
    RatingHistoryEntry,
    PreviewMatchRequest,
    PreviewMatchResponse,
    ActiveMatchResponse,
    ActiveTournamentMatchesResponse,
)
from tournament_platform.services.match_parser import parse_match_result
from tournament_platform.services.rating_intelligence import (
    get_leaderboard_data,
    get_player_rating_history_data,
    preview_match_rating,
)
from tournament_platform.config import settings
from tournament_platform.services.settings import (
    ENABLE_VOICE_ENTRY,
    ENABLE_RULES_ASSISTANT,
    ENABLE_RANKING_INTELLIGENCE,
    ENABLE_SPOKEN_CONFIRMATION,
    KEEP_AUDIO_FILES,
)

# Configure logging
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, settings.LOG_DIR)
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'app.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize AI Engine and Rating Manager
ai_engine = AIEngine()
rating_manager = RatingManager()

# Dependency: Get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application starting up")
    yield
    # Shutdown
    logger.info("Application shutting down")

app = FastAPI(lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler that logs errors"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=exc)
    return {
        "status": "error",
        "message": "Internal server error. Check logs for details.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/api/report")
async def report_match(request: Request, db: Session = Depends(get_db)):
    """
    Async endpoint to report match results for an existing scheduled match.
    - Receives match_id, winner, and score from frontend
    - Delegates to the match_reporting service for validation and update
    - Sends notification to Teams
    """
    try:
        data = await request.json()
        # Defensive logging: avoid logging full request body (may contain PII)
        logger.info(f"Received match report: match_id={data.get('match_id')}, has_winner={bool(data.get('winner'))}")

        command = ReportMatchCommand(**data)
        match = report_existing_match(db, command)
        logger.info(f"Match {match.id} updated with result via service")

        # Update Ratings
        logger.info(f"Attempting live ratings update for match {match.id}")
        if match.winner_id and match.player1_id and match.player2_id:
            try:
                winner_id = match.winner_id
                loser_id = match.player2_id if winner_id == match.player1_id else match.player1_id

                logger.info(f"Winner ID: {winner_id}, Loser ID: {loser_id}")
                rating_manager.update_ratings(winner_id, loser_id, db_session=db)
                logger.info(f"RatingManager.update_ratings called successfully")
            except Exception as e:
                logger.error(f"Failed to update live ratings: {e}", exc_info=True)
        else:
            p1_name = match.player1_rel.name if match.player1_rel else "Unknown"
            p2_name = match.player2_rel.name if match.player2_rel else "Unknown"
            winner_name = match.winner_rel.name if match.winner_rel else "Unknown"
            logger.warning(f"Skipping ratings update: Missing match data. Winner={winner_name}, P1={p1_name}, P2={p2_name}")

        # Push to Teams webhook asynchronously (only if configured)
        p1_name = match.player1_rel.name if match.player1_rel else "Unknown"
        p2_name = match.player2_rel.name if match.player2_rel else "Unknown"
        winner_name = match.winner_rel.name if match.winner_rel else "Unknown"
        msg = f"🎾 Match Result: {p1_name} vs {p2_name} → Score: {match.score} (Winner: {winner_name})"

        if settings.TEAMS_WEBHOOK_URL:
            async with httpx.AsyncClient() as client:
                try:
                    await client.post(
                        settings.TEAMS_WEBHOOK_URL,
                        json={"text": msg},
                        timeout=10.0
                    )
                    logger.info("Successfully sent notification to Teams")
                except Exception as e:
                    logger.warning(f"Failed to send Teams notification: {e}")
        else:
            logger.debug("Teams webhook not configured, skipping notification")

        return {
            "status": "success",
            "match_id": match.id,
            "message": "Match result recorded and notification sent"
        }

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except ValidationError as e:
        logger.warning(f"Match report validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (MatchNotFoundError, MatchAlreadyCompletedError, InvalidWinnerError) as e:
        logger.warning(f"Match report validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (ValueError, ConnectionError) as e:
        logger.error(f"AI Engine error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing match report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.post("/api/match/parse")
async def parse_match(request: Request):
    """
    Parse-only endpoint for match result entry.
    - Accepts a plain-text transcript
    - Returns structured JSON for UI confirmation
    - NEVER writes to the database
    """
    try:
        data = await request.json()
        # Defensive logging: avoid logging full transcript (may contain PII)
        transcript_preview = data.get("text", "")[:50] + "..." if data.get("text") else ""
        logger.info(f"Received match parse request: transcript_preview={transcript_preview!r}, tournament_id={data.get('tournament_id')}, match_id={data.get('match_id')}")

        # Validate request body
        try:
            parse_request = MatchResultParseRequest(**data)
        except ValidationError as e:
            logger.warning(f"Parse request validation error: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

        transcript = parse_request.text.strip()
        if not transcript:
            raise HTTPException(status_code=400, detail="'text' field must not be empty")

        # Call the parser service (no DB writes)
        parsed = parse_match_result(
            text=transcript,
            ai_engine=ai_engine,
            tournament_id=parse_request.tournament_id,
            match_id=parse_request.match_id,
        )

        # Validate response against schema
        response = MatchResultParseResponse(**parsed)
        logger.info(f"Parse result: status={response.status}, winner={response.winner}, score={response.score}")
        return response.model_dump()

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except ValidationError as e:
        logger.warning(f"Parse response validation error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal validation error: {e}")
    except Exception as e:
        logger.error(f"Error parsing match result: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.post("/api/rules/ask")
async def ask_rules(request: Request):
    """
    Endpoint to ask questions about tournament rules.
    - Uses RAG to get the answer
    - Bolds rule citations
    - Sends to Teams
    """
    try:
        data = await request.json()
        question = data.get('question')
        if not question:
            raise HTTPException(status_code=400, detail="Missing 'question' in request body")
        
        logger.info(f"Processing rules question: {question}")
        answer = ai_engine.referee_answer(question)
        
        # Bold rule citations (e.g., Rule 1.2.3)
        formatted_answer = re.sub(r"(Rule\s+\d+(?:\.\d+)*)", r"**\1**", answer)
        
        # Prepare Teams message
        teams_msg = {
            "text": f"🙋 **Question:** {question}\n\n⚖️ **Referee Answer:** {formatted_answer}"
        }
        
        if settings.TEAMS_WEBHOOK_URL:
            async with httpx.AsyncClient() as client:
                try:
                    await client.post(
                        settings.TEAMS_WEBHOOK_URL,
                        json=teams_msg,
                        timeout=10.0
                    )
                    logger.info("Successfully sent rule answer to Teams")
                except Exception as e:
                    logger.warning(f"Failed to send Teams notification: {e}")
        else:
            logger.debug("Teams webhook not configured, skipping notification")
        
        return {
            "status": "success",
            "question": question,
            "answer": answer,
            "formatted_answer": formatted_answer
        }
    except Exception as e:
        logger.error(f"Error in ask_rules: {e}", exc_info=True)
        if "Model" in str(e) or "connect" in str(e).lower():
            raise HTTPException(status_code=503, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ratings/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(db: Session = Depends(get_db)):
    """
    Return the current ratings leaderboard with wins/losses derived from completed matches.
    """
    try:
        data = get_leaderboard_data(db_session=db)
        return [LeaderboardEntry(**entry) for entry in data]
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch leaderboard")


@app.get("/api/ratings/player/{player_id}/history", response_model=List[RatingHistoryEntry])
async def get_player_history(player_id: int, db: Session = Depends(get_db)):
    """
    Return rating history for a specific player.
    """
    try:
        data = get_player_rating_history_data(player_id, db_session=db)
        return [RatingHistoryEntry(**entry) for entry in data]
    except Exception as e:
        logger.error(f"Error fetching rating history for player {player_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch rating history")


@app.post("/api/ratings/preview-match", response_model=PreviewMatchResponse)
async def preview_match(request: Request, db: Session = Depends(get_db)):
    """
    Preview the rating impact and upset potential for a match between two players.
    Does not write to the database.
    """
    try:
        data = await request.json()
        logger.info(f"Received match preview request: {data}")

        try:
            req = PreviewMatchRequest(**data)
        except ValidationError as e:
            logger.warning(f"Preview request validation error: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid request body: {e}")

        preview = preview_match_rating(
            player1_id=req.player1_id,
            player2_id=req.player2_id,
            winner_id=req.winner_id,
            db_session=db,
        )
        return PreviewMatchResponse(**preview)

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error previewing match: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.get("/api/tournaments/{tournament_id}/matches/active", response_model=ActiveTournamentMatchesResponse)
async def get_active_tournament_matches(
    tournament_id: int,
    statuses: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Return scorable matches for a tournament.

    By default returns matches with status: active, pending.
    Optionally includes in_progress if the app uses that status.

    Query params:
    - statuses: comma-separated list of statuses to include (e.g. "active,pending,in_progress")
    - limit: maximum number of matches to return (default 100)
    """
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")

        # Build allowed statuses
        allowed_statuses = set()
        if statuses:
            for s in statuses.split(","):
                s = s.strip().lower()
                if s in {st.value for st in MatchStatus}:
                    allowed_statuses.add(s)
        else:
            # Default: active and pending
            allowed_statuses = {MatchStatus.active.value, MatchStatus.pending.value}
            # Include in_progress if it exists in the enum
            if hasattr(MatchStatus, "in_progress"):
                allowed_statuses.add(MatchStatus.in_progress.value)

        # Query matches
        query = db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status.in_(allowed_statuses)
        )
        matches = query.limit(limit).all()

        # Sort: status priority (active/in_progress first), then round, bracket, scheduled_time, id
        def sort_key(m):
            status_priority = 0 if m.status in (MatchStatus.active, MatchStatus.active) else 1
            if hasattr(MatchStatus, "in_progress") and m.status == MatchStatus.in_progress:
                status_priority = 0
            return (
                status_priority,
                m.round_number or 0,
                m.bracket_index or 0,
                m.scheduled_time or datetime.min.replace(tzinfo=timezone.utc),
                m.id,
            )

        matches.sort(key=sort_key)

        # Build response
        result_matches = []
        for m in matches:
            p1 = db.query(Player).filter(Player.id == m.player1_id).first() if m.player1_id else None
            p2 = db.query(Player).filter(Player.id == m.player2_id).first() if m.player2_id else None
            incomplete = not (m.player1_id and m.player2_id and p1 and p2)

            result_matches.append(ActiveMatchResponse(
                match_id=m.id,
                player1_id=m.player1_id,
                player1_name=p1.name if p1 else m.player1,
                player2_id=m.player2_id,
                player2_name=p2.name if p2 else m.player2,
                status=m.status.value if isinstance(m.status, MatchStatus) else str(m.status),
                round_number=m.round_number,
                bracket_index=m.bracket_index,
                scheduled_time=m.scheduled_time.isoformat() if m.scheduled_time else None,
                location=m.location,
                score=m.score,
                incomplete=incomplete,
            ))

        return ActiveTournamentMatchesResponse(
            tournament_id=tournament_id,
            tournament_name=tournament.name,
            matches=result_matches,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching active matches for tournament {tournament_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch active matches")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
