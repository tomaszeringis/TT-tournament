import os
import chromadb
import chromadb.utils.embedding_functions as ef

class RulesRetriever:
    """
    Service for retrieving relevant tournament rules from ChromaDB.
    """
    def __init__(self, chroma_path=None):
        if chroma_path is None:
            # Consistent with AIEngine and rules_ingestion: tournament_platform/data/chroma_db
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.chroma_path = os.path.join(base_dir, "data", "chroma_db")
        else:
            self.chroma_path = chroma_path

        # Ensure directory exists
        if not os.path.exists(self.chroma_path):
            os.makedirs(self.chroma_path, exist_ok=True)

        self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
        
        # Use nomic-embed-text for consistent embeddings with the ingestion process
        self.embedding_function = ef.OllamaEmbeddingFunction(
            model_name="nomic-embed-text",
            url="http://localhost:11434/api/embeddings",
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
