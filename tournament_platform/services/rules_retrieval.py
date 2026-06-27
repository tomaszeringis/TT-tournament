import os
import chromadb
import chromadb.utils.embedding_functions as ef
from typing import List, Dict, Optional
from tournament_platform.config import settings

# Singleton pattern to avoid multiple chromadb client initializations
_chroma_client = None


def _get_chroma_client(chroma_path: str):
    """Get or create a singleton chromadb client."""
    global _chroma_client
    if _chroma_client is None:
        # Ensure directory exists
        if not os.path.exists(chroma_path):
            os.makedirs(chroma_path, exist_ok=True)
        
        # Use chromadb.Client with settings to avoid Rust bindings issues
        try:
            _chroma_client = chromadb.PersistentClient(path=chroma_path)
        except Exception as e:
            # If PersistentClient fails due to Rust bindings, try with explicit settings
            print(f"Warning: PersistentClient failed, trying with settings: {e}")
            settings_obj = chromadb.Settings(
                is_persistent=True,
                persist_directory=chroma_path,
            )
            _chroma_client = chromadb.Client(settings=settings_obj)
    
    return _chroma_client


class RulesRetriever:
    """
    Service for retrieving relevant tournament rules from ChromaDB.
    """
    def __init__(self, chroma_path=None):
        if chroma_path is None:
            self.chroma_path = settings.CHROMA_DB_PATH
        else:
            self.chroma_path = chroma_path

        # Use singleton client to avoid multiple initializations
        self.chroma_client = _get_chroma_client(self.chroma_path)
        
        # Use nomic-embed-text for consistent embeddings with the ingestion process
        self.embedding_function = ef.OllamaEmbeddingFunction(
            model_name=settings.OLLAMA_EMBEDDING_MODEL,
            url=settings.OLLAMA_EMBEDDING_URL,
        )

        # Get or create the 'tournament_rules' collection
        try:
            self.rules_collection = self.chroma_client.get_collection(
                name="tournament_rules",
                embedding_function=self.embedding_function
            )
        except ValueError:
            # This often happens if the collection was created with a different embedding function
            # In a real app we might want to migrate, but here we'll re-create for consistency
            # if we are sure it's the right thing to do. 
            # Alternatively, just get it without specifying the function.
            try:
                self.rules_collection = self.chroma_client.get_collection(name="tournament_rules")
                # If we got here, it exists but with a different EF. 
                # We should probably warn and use it, but query() will need manual embeddings.
                # To keep it simple and consistent with AIEngine, let's try to just use it.
            except Exception:
                self.rules_collection = self.chroma_client.create_collection(
                    name="tournament_rules",
                    embedding_function=self.embedding_function
                )
        except Exception:
            # Other errors (e.g. collection doesn't exist)
            try:
                self.rules_collection = self.chroma_client.create_collection(
                    name="tournament_rules",
                    embedding_function=self.embedding_function
                )
            except Exception:
                # If it already exists but failed to get with EF, fallback to getting it without EF
                self.rules_collection = self.chroma_client.get_collection(name="tournament_rules")

    def search_rules(self, query: str, n_results: int = 3) -> str:
        """
        Retrieves the top N most relevant text chunks based on the user's query.
        Returns these chunks combined into a single context string.
        """
        try:
            results = self.rules_collection.query(
                query_texts=[query],
                n_results=n_results
            )

            if results['documents'] and len(results['documents']) > 0:
                # Combine the documents into a single context string
                # We use double newline for clear separation between chunks
                context = "\n\n".join(results['documents'][0])
                return context
            return ""
        except Exception as e:
            print(f"Error retrieving rules: {e}")
            return ""

    def search_rules_with_metadata(self, query: str, n_results: int = 3) -> List[Dict]:
        """
        Retrieves the top N most relevant text chunks with full metadata.
        
        Returns a list of dicts with:
        - document: the text chunk
        - metadata: source metadata (page, source, etc.)
        - distance: retrieval score (lower is more relevant)
        - id: chunk identifier
        """
        try:
            results = self.rules_collection.query(
                query_texts=[query],
                n_results=n_results,
                include=['documents', 'metadatas', 'distances', 'ids']
            )

            sources = []
            if results['documents'] and len(results['documents']) > 0:
                for i in range(len(results['documents'][0])):
                    source = {
                        'document': results['documents'][0][i],
                        'metadata': results['metadatas'][0][i] if results.get('metadatas') else {},
                        'distance': results['distances'][0][i] if results.get('distances') else None,
                        'id': results['ids'][0][i] if results.get('ids') else None
                    }
                    sources.append(source)
            return sources
        except Exception as e:
            print(f"Error retrieving rules with metadata: {e}")
            return []

if __name__ == "__main__":
    # Quick sanity check
    retriever = RulesRetriever()
    print(f"Connected to ChromaDB at: {retriever.chroma_path}")
    test_query = "Who is the winner?"
    context = retriever.search_rules(test_query)
    print(f"Test search for '{test_query}':")
    print("-" * 20)
    print(context if context else "[No results found]")
    print("-" * 20)
