from typing import List, Optional
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
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player, Tournament, VenueTable, Announcement, AuditLog
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
from tournament_platform.services.tournament_read_models import (
    list_tournaments,
    get_public_schedule,
    get_public_rankings,
    get_operator_queue,
    get_table_status,
    get_next_available_table,
    get_player_path,
)
from tournament_platform.services.audit_service import log_audit, get_audit_logs
from tournament_platform.services.operator_commands import (
    parse_operator_command,
    apply_operator_command,
    OperatorIntent,
)
from tournament_platform.services.announcement_service import (
    create_announcement,
    send_webhook_announcement,
    get_announcements,
    generate_match_call_message,
    generate_semifinal_start_message,
    generate_final_start_message,
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


# ============================================================================
# Public Board Endpoints
# ============================================================================

@app.get("/api/public/tournaments")
async def api_list_tournaments(db: Session = Depends(get_db)):
    """List all tournaments for public board."""
    try:
        return list_tournaments(db)
    except Exception as e:
        logger.error(f"Error listing tournaments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list tournaments")


@app.get("/api/public/tournaments/{tournament_id}/schedule")
async def api_get_public_schedule(tournament_id: int, db: Session = Depends(get_db)):
    """Get public schedule for a tournament."""
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")
        return get_public_schedule(db, tournament_id=tournament_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting schedule for tournament {tournament_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get schedule")


@app.get("/api/public/tournaments/{tournament_id}/rankings")
async def api_get_public_rankings(tournament_id: int, db: Session = Depends(get_db)):
    """Get public rankings for a tournament."""
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")
        return get_public_rankings(db, tournament_id=tournament_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting rankings for tournament {tournament_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get rankings")


@app.get("/api/public/player/{player_name}/path")
async def api_get_player_path(player_name: str, tournament_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Get player path for a tournament."""
    try:
        return get_player_path(db, player_name, tournament_id=tournament_id)
    except Exception as e:
        logger.error(f"Error getting player path for {player_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get player path")


# ============================================================================
# Operator Console Endpoints
# ============================================================================

@app.get("/api/operator/tournaments/{tournament_id}/queue")
async def api_get_operator_queue(tournament_id: int, db: Session = Depends(get_db)):
    """Get operator queue for a tournament."""
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")
        return get_operator_queue(db, tournament_id=tournament_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting operator queue for tournament {tournament_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get operator queue")


@app.get("/api/operator/tournaments/{tournament_id}/tables")
async def api_get_table_status(tournament_id: int, db: Session = Depends(get_db)):
    """Get table status for a tournament."""
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")
        return get_table_status(db, tournament_id=tournament_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting table status for tournament {tournament_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get table status")


@app.get("/api/operator/tournaments/{tournament_id}/tables/available")
async def api_get_next_available_table(tournament_id: int, db: Session = Depends(get_db)):
    """Get next available table for a tournament."""
    try:
        tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
        if not tournament:
            raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")
        result = get_next_available_table(db, tournament_id=tournament_id)
        if result is None:
            return {"status": "no_tables", "message": "No active tables configured"}
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting available table for tournament {tournament_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get available table")


# ============================================================================
# Table Availability Endpoints
# ============================================================================

@app.get("/api/operator/tables/availability")
async def api_get_table_availability(
    tournament_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Get table availability summary.

    Returns:
    - total_tables: count of all venue tables
    - active_tables: count of active venue tables
    - inactive_tables: count of inactive venue tables
    - tables: list of table summaries with id, name, is_active, status, etc.
    """
    try:
        from tournament_platform.services.table_availability_service import get_table_availability_summary
        return get_table_availability_summary(db, tournament_id=tournament_id)
    except Exception as e:
        logger.error(f"Error getting table availability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get table availability")


@app.post("/api/operator/tables/max-available")
async def api_set_max_available_tables(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Set the maximum number of available tables.

    Request body:
    {
        "max_tables": 4,
        "tournament_id": optional,
        "prefer_keep_busy_tables_active": true
    }

    Response:
    - requested_max_tables
    - resulting_active_tables
    - updated_tables
    - warnings
    - table_summaries
    """
    try:
        from tournament_platform.services.table_availability_service import set_max_available_tables
        data = await request.json()
        max_tables = data.get("max_tables", 0)
        tournament_id = data.get("tournament_id")
        prefer_keep_busy = data.get("prefer_keep_busy_tables_active", True)

        if max_tables < 0:
            raise HTTPException(status_code=400, detail="max_tables must be >= 0")

        result = set_max_available_tables(
            db,
            max_tables=max_tables,
            tournament_id=tournament_id,
            actor="api",
            prefer_keep_busy_tables_active=prefer_keep_busy,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting max available tables: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to set max available tables")


@app.post("/api/operator/tables/ensure-minimum")
async def api_ensure_minimum_venue_tables(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Ensure a minimum number of venue tables exist.

    Request body:
    {
        "count": 6
    }

    Response:
    - requested_count
    - created_tables
    - table_names
    """
    try:
        from tournament_platform.services.table_availability_service import ensure_minimum_venue_tables
        data = await request.json()
        count = data.get("count", 0)

        if count < 0:
            raise HTTPException(status_code=400, detail="count must be >= 0")

        result = ensure_minimum_venue_tables(db, count=count, actor="api")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ensuring minimum venue tables: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to ensure minimum venue tables")


@app.post("/api/operator/matches/{match_id}/call")
async def api_call_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """Call a match (set call_status to 'called')."""
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        data = await request.json()
        table_name = data.get("table")
        
        if table_name:
            match.location = table_name
        
        match.call_status = "called"
        match.called_at = datetime.now(timezone.utc)
        db.commit()
        
        log_audit(
            db,
            action="call_match",
            entity_type="match",
            entity_id=match_id,
            actor="operator",
            payload={"table": table_name}
        )
        
        return {"status": "success", "match_id": match_id, "call_status": "called"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calling match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to call match")


@app.post("/api/operator/matches/{match_id}/start")
async def api_start_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """Start a match (set call_status to 'active')."""
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        match.call_status = "active"
        match.started_at = datetime.now(timezone.utc)
        db.commit()
        
        log_audit(
            db,
            action="start_match",
            entity_type="match",
            entity_id=match_id,
            actor="operator"
        )
        
        return {"status": "success", "match_id": match_id, "call_status": "active"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start match")


@app.post("/api/operator/matches/{match_id}/complete")
async def api_complete_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """Complete a match (set call_status to 'completed')."""
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        match.call_status = "completed"
        match.completed_at = datetime.now(timezone.utc)
        db.commit()
        
        log_audit(
            db,
            action="complete_match",
            entity_type="match",
            entity_id=match_id,
            actor="operator"
        )
        
        return {"status": "success", "match_id": match_id, "call_status": "completed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to complete match")


@app.post("/api/operator/matches/{match_id}/delay")
async def api_delay_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """Delay a match (set call_status to 'delayed' and set delayed_until)."""
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        data = await request.json()
        delay_minutes = data.get("delay_minutes", 15)
        
        match.call_status = "delayed"
        match.delayed_until = datetime.now(timezone.utc) + __import__("datetime").timedelta(minutes=delay_minutes)
        db.commit()
        
        log_audit(
            db,
            action="delay_match",
            entity_type="match",
            entity_id=match_id,
            actor="operator",
            payload={"delay_minutes": delay_minutes}
        )
        
        return {"status": "success", "match_id": match_id, "call_status": "delayed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error delaying match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delay match")


@app.post("/api/operator/matches/{match_id}/reschedule")
async def api_reschedule_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """Reschedule a match (change scheduled_time and optionally location)."""
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        data = await request.json()
        new_time = data.get("scheduled_time")
        new_table = data.get("table")
        
        if new_time:
            match.scheduled_time = datetime.fromisoformat(new_time.replace("Z", "+00:00"))
        if new_table:
            match.location = new_table
        
        match.call_status = "queued"
        db.commit()
        
        log_audit(
            db,
            action="reschedule_match",
            entity_type="match",
            entity_id=match_id,
            actor="operator",
            payload={"scheduled_time": new_time, "table": new_table}
        )
        
        return {"status": "success", "match_id": match_id, "call_status": "queued"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rescheduling match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reschedule match")


@app.post("/api/operator/matches/{match_id}/reset-call")
async def api_reset_call(match_id: int, request: Request, db: Session = Depends(get_db)):
    """Reset a match call (set call_status back to 'queued' and clear call-related fields)."""
    try:
        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        match.call_status = "queued"
        match.called_at = None
        match.started_at = None
        match.completed_at = None
        match.delayed_until = None
        db.commit()
        
        log_audit(
            db,
            action="reset_call",
            entity_type="match",
            entity_id=match_id,
            actor="operator"
        )
        
        return {"status": "success", "match_id": match_id, "call_status": "queued"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting call for match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reset call")


@app.get("/api/operator/audit")
async def api_get_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get audit log entries."""
    try:
        return get_audit_logs(db, entity_type=entity_type, entity_id=entity_id, limit=limit)
    except Exception as e:
        logger.error(f"Error getting audit logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get audit logs")


# ============================================================================
# Operator Commands Endpoints
# ============================================================================

@app.post("/api/operator/commands/parse")
async def api_parse_operator_command(request: Request):
    """
    Parse operator command text into structured intent.
    - Accepts plain text command
    - Returns parsed intent, args, confidence, and preview
    - NEVER writes to the database
    """
    try:
        data = await request.json()
        text = data.get("text", "")
        if not text:
            raise HTTPException(status_code=400, detail="'text' field must not be empty")
        
        parsed = parse_operator_command(text)
        
        return {
            "intent": parsed.intent.value,
            "confidence": parsed.confidence,
            "args": parsed.args,
            "requires_confirmation": parsed.requires_confirmation,
            "preview": parsed.preview,
            "errors": parsed.errors,
        }
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error parsing operator command: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.post("/api/operator/commands/apply")
async def api_apply_operator_command(request: Request, db: Session = Depends(get_db)):
    """
    Apply a parsed operator command.
    - Accepts text and optional confirmed flag
    - For read-only commands, returns result without confirmation
    - For state-changing commands, requires confirmed=True
    - Creates audit log entries for state changes
    """
    try:
        data = await request.json()
        text = data.get("text", "")
        confirmed = data.get("confirmed", False)
        tournament_id = data.get("tournament_id")
        
        if not text:
            raise HTTPException(status_code=400, detail="'text' field must not be empty")
        
        parsed = parse_operator_command(text)
        result = apply_operator_command(
            db,
            parsed,
            confirmed=confirmed,
            tournament_id=tournament_id,
        )
        
        return result
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error applying operator command: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


# ============================================================================
# Announcement Endpoints
# ============================================================================

@app.post("/api/announcements")
async def api_create_announcement(request: Request, db: Session = Depends(get_db)):
    """
    Create an announcement.
    
    Args:
        message: The announcement message
        match_id: Optional match ID to associate
        tournament_id: Optional tournament ID to associate
        channel: Channel for the announcement (default: "local")
    """
    try:
        data = await request.json()
        message = data.get("message", "")
        match_id = data.get("match_id")
        tournament_id = data.get("tournament_id")
        channel = data.get("channel", "local")
        
        if not message:
            raise HTTPException(status_code=400, detail="'message' field must not be empty")
        
        from tournament_platform.services.announcement_service import create_announcement
        announcement = create_announcement(
            db,
            message=message,
            match_id=match_id,
            tournament_id=tournament_id,
            channel=channel,
        )
        
        return {
            "status": "success",
            "announcement_id": announcement.id,
            "message": "Announcement created",
        }
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in request: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error creating announcement: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.post("/api/announcements/{announcement_id}/send")
async def api_send_announcement(announcement_id: int, db: Session = Depends(get_db)):
    """
    Send an announcement via webhook.
    
    Args:
        announcement_id: ID of the announcement to send
    """
    try:
        from tournament_platform.services.announcement_service import send_webhook_announcement
        result = send_webhook_announcement(db, announcement_id)
        return result
    except Exception as e:
        logger.error(f"Error sending announcement: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@app.get("/api/announcements")
async def api_get_announcements(
    limit: int = 50,
    channel: Optional[str] = None,
    sent_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Get recent announcements.
    
    Args:
        limit: Maximum number of announcements to return
        channel: Optional filter by channel
        sent_status: Optional filter by sent status
    """
    try:
        from tournament_platform.services.announcement_service import get_announcements
        announcements = get_announcements(
            db,
            limit=limit,
            channel=channel,
            sent_status=sent_status,
        )
        return {"announcements": announcements}
    except Exception as e:
        logger.error(f"Error getting announcements: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


if __name__ == "__main__":
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
