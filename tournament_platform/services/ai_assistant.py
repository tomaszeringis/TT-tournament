import os
import sys
from typing import Annotated
import asyncio

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function
from semantic_kernel.connectors.ai.ollama import OllamaChatCompletion
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.contents import ChatHistory

from models import SessionLocal, Match, Player, MatchStatus
from sqlalchemy import desc, func

class TournamentPlugin:
    @kernel_function(
        name="get_my_next_match",
        description="Gets the next scheduled match for a specific player."
    )
    def get_my_next_match(
        self, 
        player_name: Annotated[str, "The name of the player to look up"]
    ) -> str:
        db = SessionLocal()
        try:
            match = db.query(Match).filter(
                ((Match.player1 == player_name) | (Match.player2 == player_name)),
                Match.status != MatchStatus.completed
            ).order_by(Match.scheduled_time.asc()).first()
            
            if not match:
                return f"No upcoming matches found for {player_name}."
            
            opponent = match.player2 if match.player1 == player_name else match.player1
            time_str = match.scheduled_time.strftime("%Y-%m-%d %H:%M") if match.scheduled_time else "TBD"
            location = match.location if match.location else "TBD"
            
            return f"Your next match is against {opponent} at {location} on {time_str}."
        except Exception as e:
            return f"Error retrieving next match: {str(e)}"
        finally:
            db.close()

    @kernel_function(
        name="get_standings",
        description="Gets the current tournament standings based on number of wins."
    )
    def get_standings(self) -> str:
        db = SessionLocal()
        try:
            # Query winners and count them
            standings = db.query(Match.winner, func.count(Match.id).label('wins')) \
                .filter(Match.winner != None, Match.winner != "") \
                .group_by(Match.winner) \
                .order_by(desc('wins')) \
                .all()
            
            if not standings:
                return "No match results found yet. Standings are currently empty."
            
            result = "Current Standings:\n"
            for i, (player, wins) in enumerate(standings, 1):
                result += f"{i}. {player}: {wins} wins\n"
            return result
        except Exception as e:
            return f"Error retrieving standings: {str(e)}"
        finally:
            db.close()

async def get_tournament_assistant():
    # Initialize the kernel
    kernel = Kernel()

    # Configure Ollama service
    # llama3.1:latest is used as it has strong tool-calling support
    ollama_service = OllamaChatCompletion(
        service_id="tournament_assistant",
        ai_model_id="llama3.1:latest",
        host="http://localhost:11434"
    )
    kernel.add_service(ollama_service)

    # Register the plugin
    kernel.add_plugin(TournamentPlugin(), plugin_name="Tournament")

    return kernel

async def ask_assistant(query: str):
    kernel = await get_tournament_assistant()
    
    # Enable automatic function calling
    service_id = "tournament_assistant"
    settings = kernel.get_prompt_execution_settings_from_service_id(service_id=service_id)
    settings.function_choice_behavior = FunctionChoiceBehavior.Auto()

    chat_history = ChatHistory()
    chat_history.add_user_message(query)

    response = await kernel.get_service(service_id).get_chat_message_content(
        chat_history=chat_history,
        settings=settings,
        kernel=kernel
    )
    
    return str(response)

if __name__ == "__main__":
    # Test if called directly
    async def main():
        print("Testing Tournament Assistant...")
        queries = [
            "Who am I playing next? My name is Alice.",
            "Show me the current standings.",
            "What's the next match for Bob?"
        ]
        
        for q in queries:
            print(f"\nUser: {q}")
            try:
                response = await ask_assistant(q)
                print(f"Assistant: {response}")
            except Exception as e:
                print(f"Error: {e}")

    asyncio.run(main())
