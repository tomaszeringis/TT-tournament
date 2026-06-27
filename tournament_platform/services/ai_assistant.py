import os
from typing import Annotated
import asyncio

from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function
from semantic_kernel.connectors.ai.ollama import OllamaChatCompletion
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.contents import ChatHistory

from tournament_platform.models import SessionLocal, Match, Player, MatchStatus
from sqlalchemy import desc, func
from tournament_platform.config import settings

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
            player = db.query(Player).filter(Player.name == player_name).first()
            if not player:
                return f"Player '{player_name}' not found."

            match = db.query(Match).filter(
                ((Match.player1_id == player.id) | (Match.player2_id == player.id)),
                Match.status != MatchStatus.completed
            ).order_by(Match.scheduled_time.asc()).first()

            if not match:
                return f"No upcoming matches found for {player_name}."

            p1 = db.query(Player).filter(Player.id == match.player1_id).first() if match.player1_id else None
            p2 = db.query(Player).filter(Player.id == match.player2_id).first() if match.player2_id else None
            p1_name = p1.name if p1 else "Unknown"
            p2_name = p2.name if p2 else "Unknown"
            opponent = p2_name if p1_name == player_name else p1_name
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
            # Query winners via FK and count them
            standings = (
                db.query(Player.name, func.count(Match.id).label('wins'))
                .join(Match, Match.winner_id == Player.id)
                .group_by(Player.id, Player.name)
                .order_by(desc('wins'))
                .all()
            )

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

    # Configure Ollama service using centralized settings
    ollama_service = OllamaChatCompletion(
        service_id="tournament_assistant",
        ai_model_id=settings.SEMANTIC_KERNEL_MODEL_ID,
        host=settings.SEMANTIC_KERNEL_OLLAMA_HOST
    )
    kernel.add_service(ollama_service)

    # Register the plugin
    kernel.add_plugin(TournamentPlugin(), plugin_name="Tournament")

    return kernel

async def ask_assistant(query: str):
    kernel = await get_tournament_assistant()
    
    # Enable automatic function calling
    service_id = "tournament_assistant"
    settings_kernel = kernel.get_prompt_execution_settings_from_service_id(service_id=service_id)
    settings_kernel.function_choice_behavior = FunctionChoiceBehavior.Auto()

    chat_history = ChatHistory()
    chat_history.add_user_message(query)

    response = await kernel.get_service(service_id).get_chat_message_content(
        chat_history=chat_history,
        settings=settings_kernel,
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
