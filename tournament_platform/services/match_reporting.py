from typing import Optional

from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from tournament_platform.models import Match, MatchStatus, Player


class ReportMatchCommand(BaseModel):
    """Command to report a result for an existing scheduled match."""
    match_id: int
    winner: str
    score: str
    game_scores: Optional[str] = None

    @field_validator('score')
    @classmethod
    def validate_score(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Score cannot be empty")
        return v.strip()


class MatchNotFoundError(Exception):
    """Raised when the target match does not exist."""
    pass


class MatchAlreadyCompletedError(Exception):
    """Raised when the target match has already been completed."""
    pass


class InvalidWinnerError(Exception):
    """Raised when the reported winner is not a participant in the match."""
    pass


def report_existing_match(db: Session, command: ReportMatchCommand) -> Match:
    """
    Validate and update an existing scheduled match with a result.

    Args:
        db: SQLAlchemy database session.
        command: Validated report command containing match_id, winner, and score.

    Returns:
        The updated Match row, refreshed from the database.

    Raises:
        MatchNotFoundError: If no match exists for the given match_id.
        MatchAlreadyCompletedError: If the match is already marked completed.
        InvalidWinnerError: If the winner is not one of the match participants.
    """
    match = db.query(Match).filter(Match.id == command.match_id).first()
    if not match:
        raise MatchNotFoundError(f"Match {command.match_id} not found")

    if match.status == MatchStatus.completed:
        raise MatchAlreadyCompletedError(
            f"Match {command.match_id} has already been completed"
        )

    # Validate winner against player names resolved from FK columns
    p1 = db.query(Player).filter(Player.id == match.player1_id).first() if match.player1_id else None
    p2 = db.query(Player).filter(Player.id == match.player2_id).first() if match.player2_id else None
    p1_name = p1.name if p1 else "Unknown"
    p2_name = p2.name if p2 else "Unknown"
    if command.winner not in (p1_name, p2_name):
        raise InvalidWinnerError(
            f"Winner must be either {p1_name} or {p2_name}"
        )

    # Update both display strings and FK columns
    match.winner = command.winner
    match.winner_id = (
        match.player1_id if command.winner == p1_name else match.player2_id
    )
    match.score = command.score
    if command.game_scores:
        match.game_scores = command.game_scores
    match.status = MatchStatus.completed

    db.commit()
    db.refresh(match)
    return match
