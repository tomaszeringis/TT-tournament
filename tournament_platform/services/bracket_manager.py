import json
import os
import logging

logger = logging.getLogger(__name__)

class TournamentState:
    """
    Manages the JSON structure required by brackets-viewer.js.
    Ensures schema compliance with brackets-manager.js format.
    """

    def __init__(self, file_path='data/bracket.json', data=None):
        self.file_path = file_path
        if data:
            self.data = data
        else:
            self.data = self._load_data()

    def _load_data(self):
        """Loads bracket data from JSON file or initializes a new structure."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {self.file_path}: {e}")
        
        # Default structure compliant with brackets-manager.js
        return {
            "stages": [],
            "matches": [],
            "participants": []
        }

    def save(self):
        """Saves current state back to the JSON file."""
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)
            logger.info(f"Bracket data saved to {self.file_path}")
        except Exception as e:
            logger.error(f"Error saving {self.file_path}: {e}")

    def update_match_result(self, match_id: int, winner_name: str, score: str, tournament_type: str = 'knockout'):
        """
        Updates a match result, sets the winner, and propagates to the next round if knockout.

        Args:
            match_id: The unique ID of the match to update.
            winner_name: Name of the winning participant.
            score: Score string (e.g., "2-1").
            tournament_type: 'knockout' or 'round-robin'.
        """
        # 1. Locate the specific match by ID
        match = next((m for m in self.data.get('matches', []) if m['id'] == match_id), None)
        if not match:
            raise ValueError(f"Match with ID {match_id} not found.")

        # 2. Determine winner ID from name
        winner = next((p for p in self.data.get('participants', []) if p['name'] == winner_name), None)
        if not winner:
            raise ValueError(f"Participant with name '{winner_name}' not found.")

        winner_id = winner['id']

        # 3. Parse score and update match
        try:
            parts = score.replace(' ', '').split('-')
            s1, s2 = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            s1, s2 = 0, 0
            logger.warning(f"Invalid score format '{score}', defaulting to 0-0")

        # Assign higher score to the winner
        high_score = max(s1, s2)
        low_score = min(s1, s2)

        if match.get('opponent1') and match['opponent1'].get('id') == winner_id:
            match['opponent1']['score'] = high_score
            if match.get('opponent2'):
                match['opponent2']['score'] = low_score
        elif match.get('opponent2') and match['opponent2'].get('id') == winner_id:
            match['opponent2']['score'] = high_score
            if match.get('opponent1'):
                match['opponent1']['score'] = low_score
        else:
            # Winner was not originally in the match? Handle this edge case
            logger.warning(f"Winner {winner_name} (ID: {winner_id}) not found in match {match_id} opponents.")
            if match.get('opponent1'):
                match['opponent1']['score'] = high_score
            if match.get('opponent2'):
                match['opponent2']['score'] = low_score

        match['status'] = 5  # Completed

        # 4. Trigger creation/update of the next round's placeholder if knockout
        if tournament_type == 'knockout':
            self._propagate_winner(match, winner_id)

        # 5. Save changes
        self.save()

    def _propagate_winner(self, current_match, winner_id):
        """
        Propagates the winner to the next match in a single-elimination structure.
        """
        stage_id = current_match.get('stageId')
        round_id = current_match.get('roundId')
        match_number = current_match.get('number')

        if stage_id is None or round_id is None or match_number is None:
            return

        # Simple single-elimination logic:
        # Match N and N+1 of round R feed into match (N+1)/2 of round R+1
        next_round_id = round_id + 1
        next_match_number = (match_number + 1) // 2

        next_match = next((m for m in self.data.get('matches', []) 
                           if m['stageId'] == stage_id 
                           and m['roundId'] == next_round_id 
                           and m['number'] == next_match_number), None)

        if next_match:
            # Determine if this winner goes to opponent1 or opponent2 of the next match
            # Odd match numbers go to opponent1, even go to opponent2
            if match_number % 2 != 0:
                if 'opponent1' not in next_match or next_match['opponent1'] is None:
                    next_match['opponent1'] = {"id": winner_id}
                else:
                    next_match['opponent1']['id'] = winner_id
            else:
                if 'opponent2' not in next_match or next_match['opponent2'] is None:
                    next_match['opponent2'] = {"id": winner_id}
                else:
                    next_match['opponent2']['id'] = winner_id

            # If both opponents are now present, set status to Ready (3) or Waiting (2)
            op1 = next_match.get('opponent1')
            op2 = next_match.get('opponent2')
            if op1 and op2 and op1.get('id') is not None and op2.get('id') is not None:
                next_match['status'] = 2  # Waiting
        else:
            # If next match doesn't exist, check if we should create it
            # (concludes a round or just needs a placeholder for the next step)
            stage = next((s for s in self.data.get('stages', []) if s['id'] == stage_id), None)
            if stage:
                size = stage.get('settings', {}).get('size', 0)
                max_rounds = 0
                if size > 0:
                    import math
                    max_rounds = math.ceil(math.log2(size))
                
                if next_round_id < max_rounds:
                    # Create the next match placeholder
                    new_id = max([m['id'] for m in self.data.get('matches', [])] + [0]) + 1
                    new_match = {
                        "id": new_id,
                        "stageId": stage_id,
                        "groupId": current_match.get('groupId', 0),
                        "roundId": next_round_id,
                        "number": next_match_number,
                        "opponent1": None,
                        "opponent2": None,
                        "status": 1  # Locked
                    }
                    
                    if match_number % 2 != 0:
                        new_match['opponent1'] = {"id": winner_id}
                    else:
                        new_match['opponent2'] = {"id": winner_id}
                    
                    self.data['matches'].append(new_match)
                    logger.info(f"Created next round placeholder: Match {new_id}")

    def get_bracket_data(self):
        """Returns the full bracket data."""
        return self.data

    def calculate_standings(self):
        """
        Calculates standings from all completed matches.
        Returns a sorted list of participants with their stats.
        """
        standings = {}
        
        # Initialize standings for all participants
        for p in self.data.get('participants', []):
            standings[p['id']] = {
                'id': p['id'],
                'name': p['name'],
                'wins': 0,
                'losses': 0,
                'matches_played': 0,
                'points_for': 0,
                'points_against': 0
            }
            
        # Iterate through matches
        for m in self.data.get('matches', []):
            if m.get('status') == 5: # Completed
                op1 = m.get('opponent1')
                op2 = m.get('opponent2')
                
                if not op1 or not op2 or op1.get('id') is None or op2.get('id') is None:
                    continue
                
                id1, id2 = op1['id'], op2['id']
                s1 = op1.get('score') or 0
                s2 = op2.get('score') or 0
                
                # Ensure ids are in standings
                if id1 not in standings or id2 not in standings:
                    continue

                # Update matches played
                standings[id1]['matches_played'] += 1
                standings[id2]['matches_played'] += 1
                
                # Update points
                standings[id1]['points_for'] += s1
                standings[id1]['points_against'] += s2
                standings[id2]['points_for'] += s2
                standings[id2]['points_against'] += s1
                
                # Update wins/losses
                if s1 > s2:
                    standings[id1]['wins'] += 1
                    standings[id2]['losses'] += 1
                elif s2 > s1:
                    standings[id2]['wins'] += 1
                    standings[id1]['losses'] += 1
                else:
                    # Draw
                    pass
        
        # Sort standings: wins DESC, points_diff DESC
        sorted_standings = sorted(
            standings.values(),
            key=lambda x: (x['wins'], x['points_for'] - x['points_against']),
            reverse=True
        )
        
        return sorted_standings
