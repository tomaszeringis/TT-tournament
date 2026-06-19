import sys
import os
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from bracketool.single_elimination import SingleEliminationGen
from bracketool.domain import Competitor
from round_robin_tournament import tournament as rr_tournament

# Ensure we can import from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import Match, MatchStatus, Tournament

class TournamentStrategy(ABC):
    @abstractmethod
    def generate_matches(self, player_names: list, tournament_id: int, db: Session) -> list:
        """Generate match objects for a tournament."""
        pass

class KnockoutStrategy(TournamentStrategy):
    def generate_matches(self, player_names: list, tournament_id: int, db: Session) -> list:
        """
        Generate a single-elimination bracket using bracketool and store it in the database.
        Handles 'byes' by automatically completing those matches and propagating winners.
        """
        if not player_names:
            return []

        # Initialize bracketool generator
        gen = SingleEliminationGen(use_three_way_final=False, third_place_clash=False, use_teams=False)
        
        # Wrap player names into Competitor objects
        competitors = [Competitor(name=p, team=None, rating=1200) for p in player_names]
        
        # Generate the bracket structure
        bracket = gen.generate(competitors)
        
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
                tournament_id=tournament_id,
                status=MatchStatus.pending,
                round_number=round_map[clash],
                bracket_index=i
            )
            
            # Handle BYEs
            if hasattr(clash, 'is_bye') and clash.is_bye:
                match.winner = p1 if p1 != "TBD" else p2
                match.status = MatchStatus.completed
                match.score = "BYE"
                
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
                        if next_match.player1 == "TBD":
                            next_match.player1 = winner_name
                        elif next_match.player2 == "TBD":
                            next_match.player2 = winner_name
                            
        db.commit()
        return match_objs

class RoundRobinStrategy(TournamentStrategy):
    def generate_matches(self, player_names: list, tournament_id: int, db: Session) -> list:
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
        
        match_objs = []
        for i, rr_match in enumerate(rr_matches):
            participants = rr_match.get_participants()
            p1 = participants[0].competitor
            p2 = participants[1].competitor
            
            match = Match(
                player1=str(p1),
                player2=str(p2),
                tournament_id=tournament_id,
                status=MatchStatus.pending,
                round_number=1, # Round-robin in this library doesn't explicitly group by round
                bracket_index=i
            )
            db.add(match)
            match_objs.append(match)
            
        db.commit()
        return match_objs

class TournamentFactory:
    @staticmethod
    def create_tournament(format_type: str, player_names: list, tournament_id: int, db: Session) -> list:
        """
        Factory method to create a tournament based on the specified format.
        """
        if format_type.lower() in ['knockout', 'single-elimination']:
            strategy = KnockoutStrategy()
        elif format_type.lower() == 'round-robin':
            strategy = RoundRobinStrategy()
        else:
            raise ValueError(f"Unsupported tournament format: {format_type}")
            
        return strategy.generate_matches(player_names, tournament_id, db)

def generate_knockout_bracket(player_names: list, tournament_id: int, db: Session):
    """
    Deprecated: Use TournamentFactory.create_tournament instead.
    Maintained for backward compatibility.
    """
    return TournamentFactory.create_tournament('knockout', player_names, tournament_id, db)
