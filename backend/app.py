"""
Main entry point for the FastAPI backend application.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import chromadb
import os
from dotenv import load_dotenv
from google import genai

from src.endpoints import register_routes
from src.database import Database

# Load environment variables
load_dotenv()

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_MODEL = os.getenv("GEMINI_API_MODEL")

# Initialize Gemini client
gemini_client = None
if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Initialize FastAPI app
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize ChromaDB client with persistent storage
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# Get or create main collection (we'll use metadata filtering for folders)
collection = chroma_client.get_or_create_collection(
    name="pdf_texts",
    metadata={"hnsw:space": "cosine"}
)

# Initialize database wrapper
db = Database(collection, gemini_client, GEMINI_API_MODEL)

# Register all routes
register_routes(app, db, collection, gemini_client, GEMINI_API_MODEL)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
