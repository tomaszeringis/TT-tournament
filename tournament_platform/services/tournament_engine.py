import os
import math
import random
from abc import ABC, abstractmethod
from typing import override
from sqlalchemy.orm import Session
from bracketool.single_elimination import SingleEliminationGen
from bracketool.domain import Competitor
from round_robin_tournament import tournament as rr_tournament
from tournament_platform.models import Match, MatchStatus, Tournament, Player, Stage, Group, Entry
from tournament_platform.config import settings


class TournamentStrategy(ABC):
    """
    Abstract Base Class for tournament match generation strategies.
    """
    @abstractmethod
    def generate_matches(self, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Generate match objects for a tournament.
        
        Args:
            player_names: List of participants.
            tournament_id: The ID of the tournament these matches belong to.
            db: Database session for persistence.
            
        Returns:
            List of generated Match objects.
        """
        ...


class KnockoutStrategy(TournamentStrategy):
    """
    Strategy for generating single-elimination (knockout) brackets.
    """
    @override
    def generate_matches(self, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Generate a single-elimination bracket using bracketool and store it in the database.
        Handles 'byes' by automatically completing those matches and propagating winners.
        """
        if not player_names:
            return []

        # Initialize bracketool generator
        gen = SingleEliminationGen(use_three_way_final=False, third_place_clash=False, use_teams=False)

        # Wrap player names into Competitor objects
        competitors = [Competitor(name=p, team=None, rating=settings.DEFAULT_PLAYER_RATING) for p in player_names]

        # Generate the bracket structure
        bracket = gen.generate(competitors)

        # Look up player IDs for FK assignment
        players = db.query(Player).filter(Player.name.in_(player_names)).all()
        name_to_id = {p.name: p.id for p in players}

        # Flatten the rounds into a list of clashes to assign bracket indices
        all_clashes = []
        round_map = {} # clash_obj -> round_number

        for r_idx, round_clashes in enumerate(bracket.rounds):
            round_num = r_idx + 1
            for clash in round_clashes:
                all_clashes.append(clash)
                round_map[clash] = round_num

        # Map clashes to Match objects
        match_objs = []
        clash_to_match = {} # clash_index -> match_obj

        for i, clash in enumerate(all_clashes):
            p1 = clash.competitor_a.name if clash.competitor_a else "TBD"
            p2 = clash.competitor_b.name if clash.competitor_b else "TBD"

            match = Match(
                player1=p1,
                player2=p2,
                player1_id=name_to_id.get(p1),
                player2_id=name_to_id.get(p2),
                tournament_id=tournament_id,
                status=MatchStatus.pending,
                round_number=round_map[clash],
                bracket_index=i
            )

            # Handle BYEs
            if hasattr(clash, 'is_bye') and clash.is_bye:
                winner_name = p1 if p1 != "TBD" else p2
                match.winner = winner_name
                match.status = MatchStatus.completed
                match.score = "BYE"
                match.winner_id = name_to_id.get(winner_name)

            db.add(match)
            match_objs.append(match)
            clash_to_match[i] = match

        db.flush() # Get IDs to use for next_match_id

        # Link to next matches and propagate BYE winners
        for i, clash in enumerate(all_clashes):
            if clash.winner_to is not None:
                next_match = clash_to_match.get(clash.winner_to)
                if next_match:
                    match_objs[i].next_match_id = next_match.id

                    # If current match is completed (e.g. BYE), propagate the winner to the next match
                    if match_objs[i].status == MatchStatus.completed and match_objs[i].winner:
                        winner_name = match_objs[i].winner

                        # Determine which slot to fill in the next match
                        if next_match.player1_id is None:
                            next_match.player1 = winner_name
                            next_match.player1_id = name_to_id.get(winner_name)
                        elif next_match.player2_id is None:
                            next_match.player2 = winner_name
                            next_match.player2_id = name_to_id.get(winner_name)

        db.commit()
        return match_objs


class RoundRobinStrategy(TournamentStrategy):
    """
    Strategy for generating round-robin tournaments where everyone plays everyone.
    """
    @override
    def generate_matches(self, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Generate a round-robin tournament using the round_robin_tournament library.
        All players play each other once.
        """
        if not player_names:
            return []

        # Initialize round_robin_tournament
        # It takes a list of competitors and generates all pairings
        rr = rr_tournament.Tournament(player_names)
        rr_matches = rr.get_matches()

        # Look up player IDs for FK assignment
        players = db.query(Player).filter(Player.name.in_(player_names)).all()
        name_to_id = {p.name: p.id for p in players}

        match_objs = []
        for i, rr_match in enumerate(rr_matches):
            participants = rr_match.get_participants()
            p1 = participants[0].competitor
            p2 = participants[1].competitor

            match = Match(
                player1=str(p1),
                player2=str(p2),
                player1_id=name_to_id.get(str(p1)),
                player2_id=name_to_id.get(str(p2)),
                tournament_id=tournament_id,
                status=MatchStatus.pending,
                round_number=1, # Round-robin in this library doesn't explicitly group by round
                bracket_index=i
            )
            db.add(match)
            match_objs.append(match)

        db.commit()
        return match_objs


class GroupsKnockoutStrategy(TournamentStrategy):
    """
    Strategy for generating Groups → Knockout tournaments.
    
    Phase 1: Round-robin groups
    Phase 2: Knockout stage with qualifiers from each group
    """
    
    def __init__(self, num_groups: int = 2, qualifiers_per_group: int = 2):
        """
        Initialize the strategy with group configuration.
        
        Args:
            num_groups: Number of groups to create.
            qualifiers_per_group: Number of qualifiers from each group to advance.
        """
        self.num_groups = num_groups
        self.qualifiers_per_group = qualifiers_per_group
    
    @override
    def generate_matches(self, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Generate a Groups → Knockout tournament.
        
        Creates group stage matches (round-robin within groups) and knockout stage matches.
        The knockout stage is created with placeholder matches; actual qualifiers will be
        determined when group stage completes.
        """
        if not player_names:
            return []
        
        # Look up player IDs for FK assignment
        players = db.query(Player).filter(Player.name.in_(player_names)).all()
        name_to_id = {p.name: p.id for p in players}
        
        # Create group stage
        group_stage = Stage(
            event_id=tournament_id,
            stage_type="group",
            name="Group Stage",
            order_index=0
        )
        db.add(group_stage)
        db.flush()
        
        # Divide players into groups
        groups = []
        players_per_group = math.ceil(len(player_names) / self.num_groups)
        
        for g_idx in range(self.num_groups):
            start_idx = g_idx * players_per_group
            end_idx = min(start_idx + players_per_group, len(player_names))
            group_players = player_names[start_idx:end_idx]
            
            if not group_players:
                continue
            
            group = Group(
                stage_id=group_stage.id,
                name=f"Group {chr(65 + g_idx)}",  # A, B, C, etc.
                order_index=g_idx
            )
            db.add(group)
            db.flush()
            groups.append((group, group_players))
            
            # Create entries for this group
            for p_name in group_players:
                entry = Entry(
                    event_id=tournament_id,
                    group_id=group.id,
                    player1_id=name_to_id.get(p_name)
                )
                db.add(entry)
        
        # Generate round-robin matches within each group
        match_objs = []
        group_match_index = 0
        
        for group, group_players in groups:
            if len(group_players) < 2:
                continue
            
            rr = rr_tournament.Tournament(group_players)
            rr_matches = rr.get_matches()
            
            for rr_match in rr_matches:
                participants = rr_match.get_participants()
                p1 = str(participants[0].competitor)
                p2 = str(participants[1].competitor)
                
                match = Match(
                    player1=p1,
                    player2=p2,
                    player1_id=name_to_id.get(p1),
                    player2_id=name_to_id.get(p2),
                    tournament_id=tournament_id,
                    status=MatchStatus.pending,
                    round_number=1,
                    bracket_index=group_match_index,
                    stage_id=group_stage.id
                )
                db.add(match)
                match_objs.append(match)
                group_match_index += 1
        
        # Create knockout stage (placeholders for now)
        knockout_stage = Stage(
            event_id=tournament_id,
            stage_type="knockout",
            name="Knockout Stage",
            order_index=1
        )
        db.add(knockout_stage)
        db.flush()
        
        # Calculate knockout bracket size (qualifiers_per_group * num_groups)
        knockout_size = self.qualifiers_per_group * self.num_groups
        bracket_size = 4
        if knockout_size <= 4:
            bracket_size = 4
        elif knockout_size <= 8:
            bracket_size = 8
        elif knockout_size <= 16:
            bracket_size = 16
        else:
            bracket_size = 16  # Cap at 16 for now
        
        # Generate knockout bracket with placeholders
        gen = SingleEliminationGen(use_three_way_final=False, third_place_clash=False, use_teams=False)
        competitors = [Competitor(name=f"TBD{i+1}", team=None, rating=settings.DEFAULT_PLAYER_RATING) 
                       for i in range(bracket_size)]
        
        bracket = gen.generate(competitors)
        
        all_clashes = []
        round_map = {}
        
        for r_idx, round_clashes in enumerate(bracket.rounds):
            round_num = r_idx + 1
            for clash in round_clashes:
                all_clashes.append(clash)
                round_map[clash] = round_num
        
        clash_to_match = {}
        
        for i, clash in enumerate(all_clashes):
            match = Match(
                player1="TBD",
                player2="TBD",
                tournament_id=tournament_id,
                status=MatchStatus.pending,
                round_number=round_map[clash],
                bracket_index=group_match_index + i,
                stage_id=knockout_stage.id
            )
            db.add(match)
            match_objs.append(match)
            clash_to_match[i] = match
        
        db.flush()
        
        # Link knockout matches
        for i, clash in enumerate(all_clashes):
            if clash.winner_to is not None:
                next_match = clash_to_match.get(clash.winner_to)
                if next_match:
                    match_objs[group_match_index + i].next_match_id = next_match.id
        
        db.commit()
        return match_objs


class SwissStrategy(TournamentStrategy):
    """
    Strategy for generating Swiss System tournaments.
    
    Players are paired based on similar records in each round.
    Everyone plays the same number of rounds without elimination.
    """
    
    def __init__(self, num_rounds: int = 3):
        """
        Initialize the Swiss strategy.
        
        Args:
            num_rounds: Number of rounds to play (default 3).
        """
        self.num_rounds = num_rounds
    
    @override
    def generate_matches(self, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Generate a Swiss System tournament.
        
        Creates matches for each round, pairing players with similar records.
        Byes are assigned to players with worse records when needed.
        """
        if not player_names:
            return []
        
        # Look up player IDs for FK assignment
        players = db.query(Player).filter(Player.name.in_(player_names)).all()
        name_to_id = {p.name: p.id for p in players}
        
        # Track player records: {player_name: {"wins": int, "opponents": set}}
        player_records: dict[str, dict] = {
            name: {"wins": 0, "opponents": set()} for name in player_names
        }
        
        match_objs = []
        match_index = 0
        
        for round_num in range(1, self.num_rounds + 1):
            # Get current standings (sorted by wins, then by random for tie-breaking)
            standings = sorted(
                player_names,
                key=lambda p: (player_records[p]["wins"], random.random())
            )
            
            # Pair players for this round
            round_matches = self._pair_round(
                standings, player_records, tournament_id, db, name_to_id, round_num, match_index
            )
            match_objs.extend(round_matches)
            match_index += len(round_matches)
        
        db.commit()
        return match_objs
    
    def _pair_round(
        self,
        standings: list[str],
        player_records: dict[str, dict],
        tournament_id: int,
        db: Session,
        name_to_id: dict[str, int],
        round_num: int,
        match_index: int
    ) -> list[Match]:
        """
        Pair players for a single round of Swiss.
        
        Args:
            standings: Players sorted by current record.
            player_records: Current win/loss records.
            tournament_id: Tournament ID.
            db: Database session.
            name_to_id: Mapping of player names to IDs.
            round_num: Current round number.
            match_index: Starting match index.
            
        Returns:
            List of Match objects for this round.
        """
        matches = []
        used = set()
        
        for i, player in enumerate(standings):
            if player in used:
                continue
            
            # Find an opponent with similar record who hasn't played this player
            opponent = None
            for j in range(i + 1, len(standings)):
                candidate = standings[j]
                if candidate in used:
                    continue
                if candidate in player_records[player]["opponents"]:
                    continue
                # Check if records are close enough (within 1 win)
                if abs(player_records[player]["wins"] - player_records[candidate]["wins"]) <= 1:
                    opponent = candidate
                    break
            
            if opponent:
                # Create match
                match = Match(
                    player1=player,
                    player2=opponent,
                    player1_id=name_to_id.get(player),
                    player2_id=name_to_id.get(opponent),
                    tournament_id=tournament_id,
                    status=MatchStatus.pending,
                    round_number=round_num,
                    bracket_index=match_index + len(matches)
                )
                db.add(match)
                matches.append(match)
                used.add(player)
                used.add(opponent)
                player_records[player]["opponents"].add(opponent)
                player_records[opponent]["opponents"].add(player)
        
        return matches


class TournamentContext:
    """
    Context class that uses a TournamentStrategy to generate matches.
    """
    def __init__(self, strategy: TournamentStrategy) -> None:
        """
        Initialize the context with a specific tournament strategy.
        """
        self._strategy = strategy

    @property
    def strategy(self) -> TournamentStrategy:
        """Get the current strategy."""
        return self._strategy

    @strategy.setter
    def strategy(self, strategy: TournamentStrategy) -> None:
        """Change the strategy at runtime."""
        self._strategy = strategy

    def run_generation(self, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Delegate match generation to the current strategy.
        Raises ValueError if the tournament already has matches.
        """
        existing = db.query(Match).filter(Match.tournament_id == tournament_id).first()
        if existing:
            raise ValueError(
                f"Tournament {tournament_id} already has matches. "
                "Cannot generate duplicate fixtures."
            )
        return self._strategy.generate_matches(player_names, tournament_id, db)


class TournamentFactory:
    @staticmethod
    def create_tournament(format_type: str, player_names: list[str], tournament_id: int, db: Session) -> list[Match]:
        """
        Factory method to create a tournament based on the specified format.
        Uses TournamentContext and Strategy pattern.
        """
        strategies: dict[str, TournamentStrategy] = {
            "knockout": KnockoutStrategy(),
            "single-elimination": KnockoutStrategy(),
            "round-robin": RoundRobinStrategy(),
            "groups-knockout": GroupsKnockoutStrategy(),
        }
        
        normalized_format = format_type.lower()
        # Swiss strategy is behind a feature flag to preserve backwards compatibility with tests.
        if normalized_format == "swiss":
            if settings.ENABLE_SWISS:
                strategies["swiss"] = SwissStrategy()
            else:
                raise ValueError(f"Unsupported tournament format: {format_type}")

        if normalized_format not in strategies:
            raise ValueError(f"Unsupported tournament format: {format_type}")
            
        context = TournamentContext(strategies[normalized_format])
        return context.run_generation(player_names, tournament_id, db)


def generate_knockout_bracket(player_names: list, tournament_id: int, db: Session):
    """
    Deprecated: Use TournamentFactory.create_tournament instead.
    Maintained for backward compatibility.
    """
    return TournamentFactory.create_tournament('knockout', player_names, tournament_id, db)
