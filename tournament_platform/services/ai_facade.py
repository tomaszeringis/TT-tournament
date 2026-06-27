"""
AI Facade - Streamlit-facing service interface that hides internal AI fragmentation.
Provides a clean, stable API for the UI to call.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict

from tournament_platform.services.ai_engine import AIEngine
from tournament_platform.services.ai_utils import get_ai_status


class AIAnswer(BaseModel):
    """Response from AI for rules questions."""
    answer: str
    sources: List[str] = []
    source_details: List[Dict] = []
    confidence: Optional[str] = None
    grounded: bool = False


class ParsedMatch(BaseModel):
    """Parsed match result from transcribed text with explicit player-score mapping."""
    player_a: str
    player_b: str
    player_a_score: int
    player_b_score: int
    winner: str
    confidence: Optional[str] = None


class AIHealth(BaseModel):
    """Health status of AI services."""
    available: bool
    model_name: Optional[str] = None
    retrieval_available: bool = False
    error: Optional[str] = None


def _get_ai_engine() -> AIEngine:
    """
    Lazy initialization of AIEngine.
    Returns cached instance if available, otherwise creates new one.
    """
    return AIEngine()


def answer_rules_question(question: str) -> AIAnswer:
    """
    Answer a rules question using the AI engine with RAG context.
    
    Args:
        question: The question to ask about tournament rules
    
    Returns:
        AIAnswer with the response, sources, and optional confidence
    """
    try:
        ai_engine = _get_ai_engine()
        
        # Get sources with metadata from rules retriever
        source_details = []
        context = ""
        try:
            source_details = ai_engine.rules_retriever.search_rules_with_metadata(question, top_k=3)
            if source_details:
                context = "\n\n".join([s['document'] for s in source_details])
        except Exception:
            pass
        
        # Determine if we have grounded context
        grounded = len(source_details) > 0
        
        # Build the prompt with guardrails
        if grounded and context:
            prompt = f"""You are an official Table Tennis Referee. Use the provided context to answer the user's question. 

IMPORTANT RULES:
- If the answer is clearly in the context, provide it with confidence.
- If the context is incomplete or unclear, state that you are uncertain and suggest checking the official rulebook.
- Do NOT invent or hallucinate rules that are not in the context.
- Cite specific rules or sections when possible.

Context from rulebook:
{context}

User Question: {question}"""
        else:
            prompt = f"""You are an official Table Tennis Referee. 

IMPORTANT: No relevant rules were found in the rulebook database. You should:
- State that you are uncertain and do not have the specific rule in your knowledge base.
- Suggest the user check the official ITTF rulebook or contact a tournament official.
- Do NOT invent or guess at official rules.

User Question: {question}"""
        
        # Get AI response
        try:
            response = ai_engine._chat_with_fallback(
                messages=[{'role': 'user', 'content': prompt}]
            )
            answer = response['message']['content']
        except Exception as e:
            answer = f"Error: {e}"
        
        # Extract source labels for display
        sources = []
        for s in source_details:
            if s.get('metadata'):
                # Try to get source from metadata
                source = s['metadata'].get('source', s['metadata'].get('page', 'Unknown'))
                if source:
                    sources.append(str(source))
            elif s.get('id'):
                sources.append(s['id'])
        
        return AIAnswer(
            answer=answer,
            sources=sources,
            source_details=source_details,
            confidence="high" if grounded else "low",
            grounded=grounded
        )
    except Exception as e:
        return AIAnswer(
            answer=f"Sorry, I couldn't process your question. Please ensure Ollama is running and the model is available.",
            sources=[],
            source_details=[],
            confidence=None,
            grounded=False
        )


def parse_match_report(text: str) -> ParsedMatch:
    """
    Parse a match report from transcribed text.
    
    Args:
        text: The transcribed text describing a match result
    
    Returns:
        ParsedMatch with extracted player names, scores, and winner
    """
    try:
        ai_engine = _get_ai_engine()
        result = ai_engine.parse_match_result(text)
        
        return ParsedMatch(
            player_a=result.player_a,
            player_b=result.player_b,
            player_a_score=result.player_a_score,
            player_b_score=result.player_b_score,
            winner=result.winner,
            confidence="high"
        )
    except Exception as e:
        return ParsedMatch(
            player_a="",
            player_b="",
            player_a_score=0,
            player_b_score=0,
            winner="",
            confidence=None
        )


def check_rules_retrieval_available() -> bool:
    """
    Check if rules retrieval (ChromaDB) is available without heavy AIEngine instantiation.
    Uses a lightweight check that only connects to ChromaDB.
    """
    try:
        from tournament_platform.services.rules_retrieval import RulesRetriever
        retriever = RulesRetriever()
        # Try a simple query to verify the collection is accessible
        retriever.search_rules("test", n_results=1)
        return True
    except Exception:
        return False


def get_ai_health() -> AIHealth:
    """
    Get the health status of AI services.
    
    Returns:
        AIHealth with availability, model name, and any errors
    """
    try:
        status = get_ai_status()
        
        # Check if retrieval is available (lightweight check, no AIEngine instantiation)
        retrieval_available = check_rules_retrieval_available()
        
        return AIHealth(
            available=status["ollama_connected"] and status["model_available"],
            model_name=status.get("current_model"),
            retrieval_available=retrieval_available,
            error=status.get("error")
        )
    except Exception as e:
        return AIHealth(
            available=False,
            model_name=None,
            retrieval_available=False,
            error=str(e)
        )