"""
API endpoint handlers for the FastAPI application.
"""
from fastapi import File, UploadFile, Form
from fastapi.responses import StreamingResponse
import json
from .models import TextRequest, QuestionsRequest, ChatRequest, FolderRequest
from .database import Database
from .chatbot import process_chat_query, process_chat_query_stream
from .outline import generate_outline


def register_routes(app, db, collection, gemini_client, gemini_model):
    """
    Register all API routes with the FastAPI app.
    
    Args:
        app: FastAPI application instance
        db: Database instance
        collection: ChromaDB collection
        gemini_client: Gemini AI client
        gemini_model: Gemini model name
    """
    
    @app.get("/")
    def read_root():
        return {"message": "Hello, World!"}
    
    @app.post("/store-text")
    def store_text(request: TextRequest):
        """Store extracted text in the database."""
        return db.store_text(
            text=request.text,
            folder_name=request.folder_name,
            filename=request.filename,
            title=request.title,
            author=request.author
        )
    
    @app.post("/ocr-pdf")
    async def ocr_pdf(
        file: UploadFile = File(...), 
        folder_name: str = Form(...),
        title: str = Form(None),
        author: str = Form(None)
    ):
        """
        Process a scanned PDF using OCR (pytesseract) with parallel processing and store the extracted text.
        """
        try:
            if not folder_name or not folder_name.strip():
                return {"error": "folder_name is required"}
            
            filename = file.filename if file.filename else "unknown.pdf"
            pdf_bytes = await file.read()
            
            result = await db.ocr_pdf(
                pdf_bytes=pdf_bytes,
                folder_name=folder_name.strip(),
                filename=filename,
                title=title.strip() if title else None,
                author=author.strip() if author else None
            )
            
            return result
        except Exception as e:
            return {"error": f"OCR error: {str(e)}"}
    
    @app.post("/get-documents")
    def get_documents(request: FolderRequest):
        """Get all unique documents (with title and author) in a folder."""
        return db.get_documents(request.folder_name)
    
    @app.post("/update-document-authors")
    def update_document_authors(request: FolderRequest):
        """Update author information for existing documents in a folder."""
        return db.update_document_authors(request.folder_name)
    
    @app.post("/search-chunks")
    def search_chunks(request: QuestionsRequest):
        """Search for relevant chunks in the specified folder."""
        result = db.search_chunks(
            questions=request.questions,
            folder_name=request.folder_name
        )
        return result
    
    @app.post("/generate-outline")
    def generate_outline_endpoint(request: QuestionsRequest):
        """
        Generate an outline for a paper using a two-stage approach:
        1. Retrieve many chunks from vector DB
        2. Use LLM to extract specific evidence and generate detailed outline
        """
        if not gemini_client or not gemini_model:
            return {
                "error": "Gemini API key or model not configured. Please set GEMINI_API_KEY and GEMINI_API_MODEL in .env file"
            }
        
        if not request.folder_name:
            return {"error": "folder_name is required"}
        
        questions = request.questions
        outlines = []
        
        for question in questions:
            result = generate_outline(
                collection=collection,
                question=question,
                folder_name=request.folder_name,
                gemini_client=gemini_client,
                gemini_model=gemini_model
            )
            outlines.append(result)
        
        return {"outlines": outlines}
    
    @app.post("/chat")
    def chat(request: ChatRequest):
        """
        Chat endpoint that answers questions using relevant chunks from the folder.
        Returns streaming response with source citations.
        """
        return StreamingResponse(
            process_chat_query_stream(
                collection=collection,
                message=request.message,
                folder_name=request.folder_name,
                conversation_history=request.conversation_history,
                gemini_client=gemini_client,
                gemini_model=gemini_model
            ),
            media_type="text/event-stream"
        )

