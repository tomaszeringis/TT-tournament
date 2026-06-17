from fastapi import FastAPI, Request, Depends, HTTPException
from sqlalchemy.orm import Session
import uvicorn
import httpx
import json
import logging
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager

# Import models and database
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import SessionLocal, Match, MatchStatus

# Configure logging
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'app.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TEAMS_WEBHOOK_URL = "YOUR_TEAMS_WEBHOOK_URL_HERE"

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
    Async endpoint to report match results.
    - Receives match data from frontend
    - Updates database
    - Sends notification to Teams
    """
    try:
        data = await request.json()
        logger.info(f"Received match report: {data}")

        # Validate required fields
        required_fields = ['player1', 'player2', 'score']
        if not all(field in data for field in required_fields):
            logger.warning(f"Missing required fields. Received: {data.keys()}")
            raise HTTPException(status_code=400, detail="Missing required fields")

        # Create new match record
        match = Match(
            player1=data['player1'],
            player2=data['player2'],
            score=data['score'],
            winner=data.get('winner'),
            status=MatchStatus.completed,
            tournament_id=data.get('tournament_id')
        )

        db.add(match)
        db.commit()
        db.refresh(match)
        logger.info(f"Match record created with ID: {match.id}")

        # Push to Teams webhook asynchronously
        msg = f"🎾 New Match Result: {data['player1']} vs {data['player2']} → Score: {data['score']}"

        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    TEAMS_WEBHOOK_URL,
                    json={"text": msg},
                    timeout=10.0
                )
                logger.info("Successfully sent notification to Teams")
            except Exception as e:
                logger.warning(f"Failed to send Teams notification: {e}")

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
    except Exception as e:
        logger.error(f"Error processing match report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)





