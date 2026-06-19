import os
import sys
import uuid
import chromadb
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings

def ingest_rules_from_pdf(pdf_path: str):
    """
    Ingests tournament rules from a PDF file into ChromaDB.
    Chops the text into chunks, generates embeddings using Ollama (nomic-embed-text),
    and stores them in a persistent collection named 'tournament_rules'.
    
    This script is idempotent: it clears the existing collection before re-indexing.
    """
    if not os.path.exists(pdf_path):
        print(f"❌ Error: PDF file not found at {pdf_path}")
        return

    # 1. Load the PDF rulebook
    print(f"📄 Loading rulebook from: {pdf_path}...")
    try:
        loader = PyPDFLoader(pdf_path)
        documents = loader.load()
        print(f"✅ Loaded {len(documents)} pages.")
    except Exception as e:
        print(f"❌ Failed to load PDF: {e}")
        return

    # 2. Split text into chunks
    print("✂️ Splitting text into chunks (1000 chars with 200 overlap)...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_documents(documents)
    print(f"✅ Created {len(chunks)} text chunks.")

    # 3. Initialize local ChromaDB client
    # Consistent with AIEngine path: tournament_platform/data/chroma_db
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chroma_path = os.path.join(base_dir, "data", "chroma_db")
    
    print(f"📦 Initializing ChromaDB client at: {chroma_path}")
    if not os.path.exists(chroma_path):
        os.makedirs(chroma_path, exist_ok=True)
    
    client = chromadb.PersistentClient(path=chroma_path)

    collection_name = "tournament_rules"
    print(f"🧹 Resetting collection: '{collection_name}'...")
    try:
        client.delete_collection(name=collection_name)
    except Exception:
        # Collection might not exist, which is fine
        pass
    
    # Define embedding function for Chroma
    import chromadb.utils.embedding_functions as ef
    embedding_function = ef.OllamaEmbeddingFunction(
        model_name="nomic-embed-text",
        url="http://localhost:11434/api/embeddings",
    )
    
    collection = client.create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    # 5. Generate embeddings and store
    print(f"🧠 Generating embeddings with 'nomic-embed-text' via Ollama...")
    try:
        # Initialize LangChain's OllamaEmbeddings
        embeddings_model = OllamaEmbeddings(model="nomic-embed-text")
        
        texts = [chunk.page_content for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]
        # Ensure metadatas are simple dictionaries
        for meta in metadatas:
            meta["source"] = os.path.basename(pdf_path)
            
        ids = [str(uuid.uuid4()) for _ in range(len(chunks))]

        # Generate embeddings for the chunks
        print("💡 Requesting embeddings from Ollama (this may take a moment)...")
        embeddings = embeddings_model.embed_documents(texts)
        
        # 6. Store everything in ChromaDB
        print(f"📥 Inserting {len(chunks)} chunks into ChromaDB...")
        collection.add(
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        print(f"✨ Successfully ingested tournament rules into '{collection_name}'!")
        
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        print("Ensure Ollama is running and 'nomic-embed-text' model is pulled.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rules_ingestion.py <path_to_pdf>")
        print("Example: python rules_ingestion.py data/rules.pdf")
    else:
        pdf_file = sys.argv[1]
        ingest_rules_from_pdf(pdf_file)
