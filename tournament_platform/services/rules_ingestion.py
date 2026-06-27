import os
import sys
import uuid
import chromadb
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from tournament_platform.config import settings
from .rules_retrieval import _get_chroma_client

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

    # 3. Initialize local ChromaDB client using singleton
    chroma_path = settings.CHROMA_DB_PATH
    
    print(f"📦 Initializing ChromaDB client at: {chroma_path}")
    client = _get_chroma_client(chroma_path)

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
        model_name=settings.OLLAMA_EMBEDDING_MODEL,
        url=settings.OLLAMA_EMBEDDING_URL,
    )
    
    collection = client.create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

    # 5. Generate embeddings and store
    print(f"🧠 Generating embeddings with '{settings.OLLAMA_EMBEDDING_MODEL}' via Ollama...")
    try:
        # Initialize LangChain's OllamaEmbeddings
        embeddings_model = OllamaEmbeddings(model=settings.OLLAMA_EMBEDDING_MODEL)
        
        texts = [chunk.page_content for chunk in chunks]
        
        # 6. Store everything in ChromaDB
        print(f"📥 Inserting {len(chunks)} chunks into ChromaDB...")
        collection.add(
            documents=texts,
            embeddings=embeddings_model.embed_documents(texts),
            metadatas=[chunk.metadata for chunk in chunks],
            ids=[f"chunk_{i}_{uuid.uuid4()}" for i in range(len(chunks))]
        )
        print(f"✨ Successfully ingested tournament rules into '{collection_name}'!")
        
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        print(f"Ensure Ollama is running and '{settings.OLLAMA_EMBEDDING_MODEL}' model is pulled.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rules_ingestion.py <path_to_pdf>")
        print("Example: python rules_ingestion.py data/rules.pdf")
    else:
        pdf_file = sys.argv[1]
        ingest_rules_from_pdf(pdf_file)
