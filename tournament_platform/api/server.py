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
from tournament_platform.models import SessionLocal, Match, MatchStatus, Player
from tournament_platform.services.ai_engine import AIEngine
from tournament_platform.services.ranking_service import RatingManager
from tournament_platform.services.match_reporting import (
    ReportMatchCommand,
    MatchNotFoundError,
    MatchAlreadyCompletedError,
    InvalidWinnerError,
    report_existing_match,
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
        logger.info(f"Received match report: {data}")

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

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
