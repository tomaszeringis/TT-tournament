import ollama
import json
import logging
from pydantic import BaseModel, model_validator
from typing import Optional, Union
import os
import uuid
from .rules_retrieval import RulesRetriever, _get_chroma_client
from .bracket_manager import TournamentState
from .ranking_service import RatingManager
from tournament_platform.models import Match, MatchStatus, Tournament, SessionLocal, Player
from tournament_platform.config import settings
from tournament_platform.services.settings import OLLAMA_MODEL as FEATURE_OLLAMA_MODEL

# Configure logging
os.makedirs(settings.LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(settings.LOG_DIR, "app.log"),
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class MatchReport(BaseModel):
    """Structured response from AI engine for match analysis"""
    summary: Optional[str] = None
    key_play: Optional[str] = None
    predicted_winner: Optional[str] = None

class MatchResult(BaseModel):
    """Structured match result extracted from speech with explicit player-score mapping"""
    player_a: str
    player_b: str
    player_a_score: int
    player_b_score: int
    winner: str

    @model_validator(mode='after')
    def validate_match_result(self):
        """Validate that winner is one of the players and scores are non-negative."""
        if self.winner not in (self.player_a, self.player_b):
            raise ValueError(f"Winner '{self.winner}' must be either player_a or player_b")
        if self.player_a_score < 0 or self.player_b_score < 0:
            raise ValueError("Scores must be non-negative integers")
        return self

    def to_match_model(self) -> dict:
        """
        Helper to convert to a dictionary compatible with Match SQLAlchemy model.
        Preserves the exact player-score mapping without reordering.
        """
        return {
            "player1": self.player_a,
            "player2": self.player_b,
            "winner": self.winner,
            "score": f"{self.player_a_score}-{self.player_b_score}"
        }

class AIEngine:
    def __init__(self, model=None, chroma_path=None):
        # Use settings default, allow override
        self.model = model or FEATURE_OLLAMA_MODEL
        if chroma_path is None:
            self.chroma_path = settings.CHROMA_DB_PATH
        else:
            self.chroma_path = chroma_path

        # Initialize RulesRetriever for RAG (handles embedding function and collection)
        # This uses the singleton chromadb client to avoid multiple initializations
        self.rules_retriever = RulesRetriever(chroma_path=self.chroma_path)
        
        # Get the shared chromadb client
        self.chroma_client = self.rules_retriever.chroma_client
        
        # Verify Ollama connection and model availability
        self._ensure_model_available()

    def _ensure_model_available(self, silent=False):
        """Verify that Ollama is running and the required model is available.

        In Cloud/external API mode this resolves availability through the
        FastAPI bridge and never instantiates the local Ollama client, so no
        ``localhost:11434`` connection is attempted and the "Failed to connect
        to Ollama" error never appears on Streamlit Cloud.
        """
        try:
            from tournament_platform.app.services.ai_provider import resolve_provider

            if resolve_provider() == "api_bridge":
                # Bridge governs availability; nothing to verify locally.
                return
        except Exception:
            pass

        try:
            available_models_resp = ollama.list()

            # Extract model names correctly based on response type
            if hasattr(available_models_resp, 'models'):
                model_names = [m.model for m in available_models_resp.models]
            else:
                model_names = [m.get('name') for m in available_models_resp.get('models', [])]

            # If our preferred model isn't there, look for a suitable fallback
            if self.model not in model_names:
                fallbacks = ["llama3.1:8b", "llama3:latest", "llama3:8b", "llama3.2:3b", "llama3.2:1b"]
                for fallback in fallbacks:
                    if fallback in model_names:
                        if not silent:
                            print(f"Warning: Model '{self.model}' not found. Falling back to '{fallback}'.")
                        self.model = fallback
                        return

                if not silent:
                    print(f"Warning: Neither '{self.model}' nor common fallbacks found in Ollama.")
                # We don't pull automatically here to avoid blocking UI for too long,
                # but we've verified connection at least.
        except Exception as e:
            if not silent:
                print(f"Error connecting to Ollama: {e}")
            # We don't raise here to allow the class to be instantiated,
            # but actual calls will fail later with the connection error.

    def _chat_with_fallback(self, messages, format=None, stream=False):
        """
        Internal helper to call Ollama with dynamic model fallback and robust
        error handling. In Cloud/external API mode this routes through the
        FastAPI bridge; locally it uses the ``ollama`` client directly.
        """
        try:
            from tournament_platform.app.services.ai_provider import ollama_chat, resolve_provider

            if resolve_provider() == "api_bridge":
                result = ollama_chat(messages=messages, model=self.model, temperature=0.3)
                if not result or not result.get("ok"):
                    raise ConnectionError(
                        f"Ollama unavailable via API bridge: {result.get('error') if result else 'no response'}"
                    )
                return {"message": {"role": "assistant", "content": result.get("message", "")}}

            return ollama.chat(
                model=self.model,
                messages=messages,
                stream=stream,
                format=format
            )
        except Exception as e:
            error_str = str(e).lower()

            # Handle model not found error by trying fallback immediately
            if "not found" in error_str or "404" in error_str:
                original_model = self.model
                # Re-check available models and update self.model
                self._ensure_model_available(silent=True)

                if self.model != original_model:
                    # Retry with new model
                    try:
                        return ollama.chat(
                            model=self.model,
                            messages=messages,
                            stream=stream,
                            format=format
                        )
                    except Exception as retry_err:
                        e = retry_err # Fall through to common error handling

                # If we're here, either fallback failed or no fallback was found
                raise ValueError(
                    f"Model '{original_model}' not found in Ollama. "
                    f"Please run 'ollama pull {original_model}' or set OLLAMA_MODEL to an available model (e.g., llama3:latest). "
                    f"Available models: {ollama.list().get('models', []) if hasattr(ollama.list(), 'get') else 'unknown'}"
                ) from e

            # Handle connection errors
            if "connection" in error_str or "connect" in error_str or "11434" in error_str:
                raise ConnectionError(
                    f"Failed to connect to Ollama at {settings.OLLAMA_HOST}. "
                    f"Please ensure Ollama is running ('ollama serve'). Details: {e}"
                ) from e

            # Other errors
            raise

    def add_rule_to_rag(self, rule_text: str, rule_id: Optional[str] = None):
        """Add tournament rules to the RAG knowledge base"""
        if rule_id is None:
            rule_id = str(uuid.uuid4())

        self.rules_retriever.rules_collection.add(
            documents=[rule_text],
            ids=[rule_id],
            metadatas=[{"type": "tournament_rule"}]
        )

    def retrieve_rules_context(self, query: str, top_k: int = 3) -> str:
        """Retrieve relevant rules from the knowledge base"""
        return self.rules_retriever.search_rules(query, n_results=top_k)

    def generate_report(self, match_data: dict) -> MatchReport:
        """Generate a structured AI report for a match with RAG context"""

        # Retrieve relevant tournament rules
        rules_context = self.retrieve_rules_context(
            f"Tournament rules for match between {match_data.get('player1')} and {match_data.get('player2')}",
            top_k=3
        )

        context_snippet = ""
        if rules_context:
            context_snippet = f"\n\nRelevant Tournament Rules:\n{rules_context}"

        prompt = f"""Analyze this table tennis match and provide a JSON response with the following structure:
{{
    "summary": "A short, engaging summary of the match (2-3 sentences)",
    "key_play": "The most critical moment or play in the match",
    "predicted_winner": "Name of the predicted winner based on the data"
}}

Match Data: {match_data}{context_snippet}

Respond ONLY with valid JSON, no additional text."""

        try:
            response = self._chat_with_fallback(
                messages=[{'role': 'user', 'content': prompt}],
                format="json"
            )

            # Extract the response content
            response_text = response['message']['content']

            # Parse JSON response
            report_dict = json.loads(response_text)
            return MatchReport(**report_dict)

        except json.JSONDecodeError as e:
            print(f"Error parsing AI response: {e}")
            return MatchReport(
                summary="Unable to generate summary",
                key_play="Analysis failed",
                predicted_winner="Unknown"
            )

    def batch_initialize_rules(self, rules_list: list):
        """Initialize the RAG system with a batch of tournament rules"""
        import uuid
        for i, rule in enumerate(rules_list):
            rule_id = f"rule_{i}_{uuid.uuid4()}"
            self.add_rule_to_rag(rule, rule_id)

    def parse_match_result(self, transcribed_text: str, match_id: Optional[int] = None) -> Union[MatchResult, dict]:
        """
        Parse match result from transcribed text using Ollama.
        If match_id is provided, updates the bracket and database.
        Returns MatchResult or the updated bracket JSON.
        """
        prompt = f"""Extract match result information from the following transcript:
"{transcribed_text}"

Return a JSON object with EXACTLY these keys:
- player_a (string) - First player mentioned
- player_b (string) - Second player mentioned
- player_a_score (integer) - Score for player_a
- player_b_score (integer) - Score for player_b
- winner (string) - Must be either player_a or player_b

Respond ONLY with valid JSON."""

        try:
            response = self._chat_with_fallback(
                messages=[{'role': 'user', 'content': prompt}],
                format="json"
            )

            response_text = response['message']['content']
            result_dict = json.loads(response_text)
            
            # Validate against Pydantic model
            match_result = MatchResult(**result_dict)
            
            # If no match_id, we just return the parsed result for UI pre-filling
            if match_id is None:
                return match_result

            # Integrate with TournamentState and Database
            ts = TournamentState()
            rating_manager = RatingManager()
            
            # Fetch tournament type from DB to handle round-robin vs knockout
            t_type = 'knockout'
            if Match and Tournament and SessionLocal:
                db_session = SessionLocal()
                try:
                    match_db = db_session.query(Match).filter(Match.id == match_id).first()
                    if match_db:
                        if match_db.tournament:
                            t_type = match_db.tournament.tournament_type.value
                        
                        # Update Match in Database - preserve exact player-score mapping
                        match_db.winner = match_result.winner
                        match_db.score = f"{match_result.player_a_score}-{match_result.player_b_score}"
                        match_db.status = MatchStatus.completed
                        db_session.commit()
                        logger.info(f"Database: Updated match {match_id} status to completed.")

                        # Update Ratings
                        winner_name = match_result.winner
                        loser_name = match_result.player_b if match_result.winner == match_result.player_a else match_result.player_a
                        
                        winner = db_session.query(Player).filter(Player.name == winner_name).first()
                        loser = db_session.query(Player).filter(Player.name == loser_name).first()
                        
                        if winner and loser:
                            rating_manager.update_ratings(winner.id, loser.id, db_session=db_session)
                            logger.info(f"Live ratings updated for {winner_name} vs {loser_name}")
                        else:
                            logger.warning(f"Could not update ratings: Player(s) not found in DB.")
                except Exception as db_e:
                    logger.error(f"Error during DB update in parse_match_result: {db_e}")
                    db_session.rollback()
                finally:
                    db_session.close()

            try:
                score_str = f"{match_result.player_a_score}-{match_result.player_b_score}"
                ts.update_match_result(match_id, match_result.winner, score_str, tournament_type=t_type)
                logger.info(f"Bracket: Successfully updated match {match_id} (Type: {t_type}).")
                return ts.get_bracket_data()
                
            except (ValueError, KeyError) as e:
                error_msg = f"Match update failed for ID {match_id}: {str(e)}"
                logger.error(error_msg)
                return {"error": error_msg, "bracket_data": ts.get_bracket_data()}

        except Exception as e:
            error_msg = f"AI Parsing error: {str(e)}"
            logger.error(error_msg)
            # Re-raise helpful errors from _chat_with_fallback if they are system-level
            if isinstance(e, (ValueError, ConnectionError)) and "not found" in str(e):
                raise
            
            return {"error": "Could not parse match result. Please try again or enter manually."}

    def referee_answer(self, question: str) -> str:
        """
        Answer questions about tournament rules using RAG.
        """
        # Call RulesRetriever.search_rules(question) to get the context.
        retrieved_rules = self.rules_retriever.search_rules(question)

        # Construct an Ollama prompt
        prompt = f"You are an official Table Tennis Referee. Use the provided context to answer the user's question. If the answer is not in the context, state that clearly and do not hallucinate. Context: {retrieved_rules}. User Question: {question}. Please cite the rules if possible."

        try:
            response = self._chat_with_fallback(
                messages=[{'role': 'user', 'content': prompt}]
            )
            return response['message']['content']
        except Exception as e:
            if isinstance(e, (ValueError, ConnectionError)):
                return f"Error: {e}"
                
            print(f"Error getting referee answer: {e}")
            return f"Error: {str(e)}"

def validate_and_map_to_match(result_dict: dict) -> Union['Match', dict]:
    """
    Helper function that validates JSON data against MatchResult Pydantic model
    and returns an object that can be passed directly to the Match SQLAlchemy model.
    """
    # Validate using Pydantic
    match_result = MatchResult(**result_dict)
    
    # Convert to Match model data
    match_data = match_result.to_match_model()
    
    if Match:
        # Return a Match SQLAlchemy instance if available
        return Match(
            player1=match_data["player1"],
            player2=match_data["player2"],
            winner=match_data["winner"],
            score=match_data["score"],
            status=MatchStatus.completed if MatchStatus else "completed"
        )
    # Return full data including explicit score fields for UI consumption
    return {
        "player_a": match_result.player_a,
        "player_b": match_result.player_b,
        "player_a_score": match_result.player_a_score,
        "player_b_score": match_result.player_b_score,
        "winner": match_result.winner,
        "score": match_data["score"]
    }
