import ollama
import chromadb
import json
from pydantic import BaseModel
from typing import Optional
import os
import uuid

class MatchReport(BaseModel):
    """Structured response from AI engine for match analysis"""
    summary: str
    key_play: str
    predicted_winner: str

class AIEngine:
    def __init__(self, model="llama3.3:8b", chroma_path="./data/chroma_db"):
        self.model = model
        self.chroma_path = chroma_path

        # Initialize Chroma client for RAG
        if not os.path.exists(chroma_path):
            os.makedirs(chroma_path, exist_ok=True)

        self.chroma_client = chromadb.PersistentClient(path=chroma_path)

        # Get or create collection for tournament rules
        try:
            self.rules_collection = self.chroma_client.get_collection(name="tournament_rules")
        except:
            self.rules_collection = self.chroma_client.create_collection(name="tournament_rules")

    def add_rule_to_rag(self, rule_text: str, rule_id: Optional[str] = None):
        """Add tournament rules to the RAG knowledge base"""
        if rule_id is None:
            rule_id = str(uuid.uuid4())

        self.rules_collection.add(
            documents=[rule_text],
            ids=[rule_id],
            metadatas=[{"type": "tournament_rule"}]
        )

    def retrieve_rules_context(self, query: str, top_k: int = 3) -> str:
        """Retrieve relevant rules from the knowledge base"""
        try:
            results = self.rules_collection.query(
                query_texts=[query],
                n_results=top_k
            )

            if results['documents'] and len(results['documents']) > 0:
                context = "\n".join(results['documents'][0])
                return context
            return ""
        except Exception as e:
            print(f"Error retrieving rules: {e}")
            return ""

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
            response = ollama.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                stream=False,
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

