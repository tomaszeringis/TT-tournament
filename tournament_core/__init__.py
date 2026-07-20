"""
Tournament Core Package

Core tournament logic separated from AI/multimodal features.
This package contains:
- Tournament models (Player, Match, Tournament, Event, Stage, Group, Entry)
- Tournament strategies (Knockout, Round Robin, Groups → Knockout, Swiss)
- Match management and scoring
- Scheduling and conflict detection
"""

try:
    from tournament_platform.models import (
        Player,
        Match,
        Tournament,
        MatchStatus,
        TournamentType,
        Event,
        EventType,
        Stage,
        Group,
        Entry,
        ScorerToken,
        VenueTable,
        RatingHistory,
    )
except Exception:  # pragma: no cover - depends on lab availability
    Player = Match = Tournament = None
    MatchStatus = TournamentType = Event = EventType = None
    Stage = Group = Entry = ScorerToken = VenueTable = RatingHistory = None

try:
    from tournament_platform.services.tournament_engine import (
        TournamentStrategy,
        KnockoutStrategy,
        RoundRobinStrategy,
        GroupsKnockoutStrategy,
        SwissStrategy,
        TournamentContext,
    )
except Exception:  # pragma: no cover - depends on lab availability
    TournamentStrategy = KnockoutStrategy = None
    RoundRobinStrategy = GroupsKnockoutStrategy = None
    SwissStrategy = TournamentContext = None

__all__ = [
    # Models
    "Player",
    "Match",
    "Tournament",
    "MatchStatus",
    "TournamentType",
    "Event",
    "EventType",
    "Stage",
    "Group",
    "Entry",
    "ScorerToken",
    "VenueTable",
    "RatingHistory",
    # Strategies
    "TournamentStrategy",
    "KnockoutStrategy",
    "RoundRobinStrategy",
    "GroupsKnockoutStrategy",
    "SwissStrategy",
    "TournamentContext",
]