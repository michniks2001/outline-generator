from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import uvicorn
import chromadb
from chromadb.config import Settings
import uuid
from pdf2image import convert_from_bytes
from io import BytesIO
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import os
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_MODEL = os.getenv("GEMINI_API_MODEL")

# Initialize Gemini client
gemini_client = None
if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

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

def clean_filename(filename: str) -> str:
    """
    Clean filename for display (remove extension, replace underscores/hyphens with spaces).
    
    Args:
        filename: The filename to clean
    
    Returns:
        Cleaned filename
    """
    if not filename:
        return None
    
    # Remove path if present
    filename = filename.split('/')[-1]
    
    # Remove extension
    if '.' in filename:
        filename = '.'.join(filename.split('.')[:-1])
    
    # Replace underscores and hyphens with spaces
    filename = filename.replace('_', ' ').replace('-', ' ')
    
    # Clean up multiple spaces
    filename = ' '.join(filename.split())
    
    return filename.strip()

def extract_title(text: str, fallback_name: str = None) -> str:
    """
    Extract title from document text. Looks for title in first few lines.
    Always uses filename as fallback if title cannot be extracted.
    
    Args:
        text: The document text
        fallback_name: Fallback name (filename) if title cannot be extracted
    
    Returns:
        Extracted title or cleaned filename
    """
    # Clean the filename for better display - prioritize filename
    cleaned_filename = clean_filename(fallback_name) if fallback_name else None
    
    if not text:
        return cleaned_filename or "Untitled Document"
    
    # Get first 500 characters (usually contains title)
    first_part = text[:500].strip()
    lines = first_part.split('\n')
    
    # Look for title in first few non-empty lines
    for line in lines[:10]:  # Check first 10 lines
        line = line.strip()
        if not line:
            continue
        
        # Skip common non-title patterns
        if line.lower().startswith(('abstract', 'introduction', 'table of contents', 'contents')):
            continue
        
        # Skip lines that look like IDs, UUIDs, or random alphanumeric strings
        if len(line) <= 20 and (line.replace('-', '').replace('_', '').isalnum() or 
                                all(c.isalnum() or c in '-_' for c in line)):
            if line.count(' ') < 2:
                continue
        
        # If line is reasonably short and looks like a title, use it
        if len(line) > 10 and len(line) < 200 and not line.startswith((' ', '\t')):
            words = line.split()
            if len(words) >= 2:
                if not line.isupper() or len(words) <= 15:
                    return line
    
    # If no good title found, always use cleaned filename as fallback
    return cleaned_filename or "Untitled Document"

def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list:
    """
    Split text into chunks with overlap using sentence boundaries.
    
    Args:
        text: The text to chunk
        chunk_size: Target size of each chunk (default: 500 chars)
        overlap: Number of characters to overlap between chunks (default: 100)
    
    Returns:
        List of text chunks
    """
    if not text:
        return []
    
    # Split text into sentences using regex
    sentence_pattern = r'(?<=[.!?])\s+'
    sentences = re.split(sentence_pattern, text)
    
    # Filter out empty sentences
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if not sentences:
        # Fallback: if no sentence boundaries found, use character-based chunking
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start = end - overlap
            if end >= len(text):
                break
        return chunks
    
    chunks = []
    current_chunk = []
    current_length = 0
    
    for sentence in sentences:
        sentence_length = len(sentence)
        
        # If adding this sentence would exceed chunk_size, finalize current chunk
        if current_length + sentence_length > chunk_size and current_chunk:
            chunks.append(' '.join(current_chunk))
            
            # Start new chunk with overlap: take last few sentences that fit in overlap
            overlap_sentences = []
            overlap_length = 0
            for s in reversed(current_chunk):
                if overlap_length + len(s) <= overlap:
                    overlap_sentences.insert(0, s)
                    overlap_length += len(s) + 1  # +1 for space
                else:
                    break
            
            current_chunk = overlap_sentences + [sentence]
            current_length = overlap_length + sentence_length
        else:
            current_chunk.append(sentence)
            current_length += sentence_length + 1  # +1 for space
    
    # Add the last chunk if it exists
    if current_chunk:
        chunks.append(' '.join(current_chunk))
    
    return chunks

def ocr_image_bytes(image_bytes: bytes) -> str:
    """Worker function that runs OCR on a bytes image."""
    from PIL import Image
    import pytesseract
    import io
    
    image = Image.open(io.BytesIO(image_bytes))
    text = pytesseract.image_to_string(image)
    return text

@app.get("/")
def read_root():
    return {"message": "Hello, World!"}

class TextRequest(BaseModel):
    text: str
    folder_name: str
    filename: str

class QuestionsRequest(BaseModel):
    questions: list[str]
    folder_name: str

@app.post("/store-text")
def store_text(request: TextRequest):
    text = request.text
    folder_name = request.folder_name
    filename = request.filename
    
    if not folder_name:
        return {"error": "folder_name is required"}
    
    if not filename:
        return {"error": "filename is required"}
    
    timestamp = datetime.now().isoformat()
    document_title = extract_title(text, filename)
    chunks = chunk_text(text)
    chunk_ids = [str(uuid.uuid4()) for _ in chunks]
    
    collection.add(
        ids=chunk_ids,
        documents=chunks,
        metadatas=[
            {
                "chunk_index": i,
                "total_chunks": len(chunks),
                "folder_name": folder_name,
                "source": document_title,
                "filename": filename,
                "timestamp": timestamp
            }
            for i in range(len(chunks))
        ]
    )
    
    return {
        "message": "Text stored successfully",
        "folder_name": folder_name,
        "document_title": document_title,
        "filename": filename,
        "total_chunks": len(chunks),
        "chunk_ids": chunk_ids
    }

@app.post("/ocr-pdf")
async def ocr_pdf(file: UploadFile = File(...), folder_name: str = Form(...)):
    """
    Process a scanned PDF using OCR (pytesseract) with parallel processing and store the extracted text.
    """
    try:
        if not folder_name or not folder_name.strip():
            return {"error": "folder_name is required"}
        
        filename = file.filename if file.filename else "unknown.pdf"
        pdf_bytes = await file.read()
        pages = convert_from_bytes(pdf_bytes, dpi=150)
        page_count = len(pages)
        
        # Process pages in batches of 30
        batch_size = 30
        all_chunks = []
        all_chunk_ids = []
        all_text_parts = []
        batches_processed = []
        
        for batch_start in range(0, page_count, batch_size):
            batch_end = min(batch_start + batch_size, page_count)
            batch_pages = pages[batch_start:batch_end]
            batch_number = (batch_start // batch_size) + 1
            
            page_byte_list = []
            for page in batch_pages:
                buf = BytesIO()
                page.save(buf, format="PNG")
                page_byte_list.append(buf.getvalue())
            
            with ProcessPoolExecutor() as pool:
                results = list(pool.map(ocr_image_bytes, page_byte_list))
            
            batch_text = "\n\n".join(results)
            all_text_parts.append(batch_text)
            
            batch_chunks = chunk_text(batch_text)
            batch_chunk_ids = [str(uuid.uuid4()) for _ in batch_chunks]
            
            all_chunks.extend(batch_chunks)
            all_chunk_ids.extend(batch_chunk_ids)
            
            batches_processed.append({
                "batch": batch_number,
                "pages": f"{batch_start + 1}-{batch_end}",
                "chunks": len(batch_chunks)
            })
        
        combined_text = "\n\n".join(all_text_parts)
        document_title = extract_title(combined_text, filename)
        
        timestamp = datetime.now().isoformat()
        metadatas = [
            {
                "chunk_index": i,
                "total_chunks": len(all_chunks),
                "folder_name": folder_name,
                "source": document_title,
                "filename": filename,
                "timestamp": timestamp
            }
            for i in range(len(all_chunks))
        ]
        
        def add_to_collection():
            collection.add(
                ids=all_chunk_ids,
                documents=all_chunks,
                metadatas=metadatas
            )
        
        await run_in_threadpool(add_to_collection)
        
        return {
            "message": f"PDF processed with OCR successfully in {len(batches_processed)} batch(es)",
            "folder_name": folder_name,
            "document_title": document_title,
            "filename": filename,
            "total_pages": page_count,
            "total_chunks": len(all_chunks),
            "batches": batches_processed,
            "chunk_ids": all_chunk_ids
        }
    except Exception as e:
        return {"error": f"OCR error: {str(e)}"}

@app.post("/search-chunks")
def search_chunks(request: QuestionsRequest):
    """
    Search for relevant chunks in the specified folder.
    """
    if not request.folder_name:
        return {"error": "folder_name is required"}
    
    questions = request.questions
    results = []
    
    for question in questions:
        query_results = collection.query(
            query_texts=[question],
            n_results=50,  # Get many candidates
            where={"folder_name": request.folder_name}
        )
        
        chunks_with_metadata = []
        if query_results['documents'] and len(query_results['documents'][0]) > 0:
            documents = query_results['documents'][0]
            metadatas = query_results.get('metadatas', [[]])[0] if query_results.get('metadatas') else []
            distances = query_results.get('distances', [[]])[0] if query_results.get('distances') else []
            
            for i in range(len(documents)):
                chunks_with_metadata.append({
                    "text": documents[i],
                    "distance": distances[i] if i < len(distances) else None,
                    "metadata": metadatas[i] if i < len(metadatas) else {}
                })
        
        results.append({
            "question": question,
            "chunks": chunks_with_metadata[:20]  # Return top 20
        })
    
    return {
        "results": results,
        "note": f"Searched documents in folder: {request.folder_name}"
    }

@app.post("/generate-outline")
def generate_outline(request: QuestionsRequest):
    """
    Generate an outline for a paper using a two-stage approach:
    1. Retrieve many chunks from vector DB
    2. Use LLM to extract specific evidence and generate detailed outline
    """
    if not gemini_client or not GEMINI_API_MODEL:
        return {
            "error": "Gemini API key or model not configured. Please set GEMINI_API_KEY and GEMINI_API_MODEL in .env file"
        }
    
    if not request.folder_name:
        return {"error": "folder_name is required"}
    
    questions = request.questions
    outlines = []
    
    for question in questions:
        try:
            # Stage 1: Retrieve chunks from ALL documents in folder
            query_results = collection.query(
                query_texts=[question],
                n_results=50,  # Get many chunks for comprehensive coverage
                where={"folder_name": request.folder_name}
            )
            
            # Organize chunks by document
            documents_data = {}
            if query_results['documents'] and len(query_results['documents'][0]) > 0:
                documents = query_results['documents'][0]
                metadatas = query_results.get('metadatas', [[]])[0] if query_results.get('metadatas') else []
                distances = query_results.get('distances', [[]])[0] if query_results.get('distances') else []
                
                for i in range(len(documents)):
                    metadata = metadatas[i] if i < len(metadatas) else {}
                    filename = metadata.get('filename', 'Unknown Document')
                    distance = distances[i] if i < len(distances) else 1.0
                    
                    # Only include reasonably relevant chunks (distance < 0.85)
                    if distance < 0.85:
                        doc_name = clean_filename(filename) if filename != 'Unknown Document' else 'Unknown Document'
                        
                        if doc_name not in documents_data:
                            documents_data[doc_name] = []
                        
                        documents_data[doc_name].append({
                            'text': documents[i],
                            'distance': distance,
                            'metadata': metadata
                        })
            
            if not documents_data:
                outlines.append({
                    "question": question,
                    "outline": None,
                    "error": "No relevant chunks found for this question."
                })
                continue
            
            # Sort chunks within each document by relevance
            for doc_name in documents_data:
                documents_data[doc_name].sort(key=lambda x: x['distance'])
            
            # Stage 2: Build comprehensive context from top chunks of each document
            context_parts = []
            source_documents = []
            
            # Take top chunks from each document (up to 8 chunks per document)
            for doc_name in sorted(documents_data.keys()):
                chunks = documents_data[doc_name][:8]  # Top 8 chunks per doc
                source_documents.append(doc_name)
                
                doc_context = f"\n{'='*60}\nSOURCE DOCUMENT: {doc_name}\n{'='*60}\n"
                for chunk in chunks:
                    doc_context += f"\n{chunk['text']}\n"
                
                context_parts.append(doc_context)
            
            full_context = "\n".join(context_parts)
            
            # Stage 3: Generate outline with emphasis on using all sources
            source_list = "\n".join([f"  {i+1}. {doc}" for i, doc in enumerate(source_documents)])
            
            prompt = f"""You are creating an OUTLINE for an academic research paper. You have been given context from {len(source_documents)} different source documents.

IMPORTANT: Generate an OUTLINE ONLY - not a full paper. The outline should show the structure and key points, not complete paragraphs or full explanations.

QUESTION TO ANSWER:
{question}

AVAILABLE SOURCE DOCUMENTS:
{source_list}

FULL CONTEXT FROM ALL SOURCES:
{full_context}

CRITICAL INSTRUCTIONS:
1. You MUST cite information using the format [Document Name] - use the exact document names shown above
2. You MUST use evidence from MULTIPLE sources - aim to cite at least {min(len(source_documents), 3)} different documents
3. Include SPECIFIC details, examples, studies, statistics, and quotes from the sources in the outline points
4. When sources provide specific evidence (like case names, statistics, procedures), YOU MUST INCLUDE THESE DETAILS in the outline
5. Do NOT write generic statements - every outline point should reference specific evidence from the sources
6. If multiple sources discuss the same topic, cite all of them: [Source1; Source2; Source3]

OUTLINE STRUCTURE REQUIREMENTS:
- Introduction (with thesis statement as a bullet point)
- 3-5 main body sections with subsections (each subsection should list key points, not full paragraphs)
- Conclusion (summary points, not full text)
- Use markdown formatting (## for main sections, ### for subsections)
- Each outline point should be brief but specific, indicating what evidence will be discussed

EXAMPLE OF GOOD vs BAD OUTLINE POINTS:
❌ BAD: "Research shows memory is unreliable" (too generic, no citation)
✅ GOOD: "DNA evidence exonerations: Steven Smith and Anthony Porter cases - eyewitness testimony recanted [Memory Faults and Fixes]"

❌ BAD: "Courts have procedures to help with this" (too vague)
✅ GOOD: "TWGEYEE uniform practices for evidence collection and preservation [Eyewitness Testimony]"

Generate a detailed, evidence-rich OUTLINE (not a full paper) that demonstrates you've read and understood all the source materials. Each section should list key points with specific evidence and proper citations."""

            # Generate outline using Gemini
            response = gemini_client.models.generate_content(
                model=GEMINI_API_MODEL,
                contents=prompt
            )
            
            # Extract text from response
            if hasattr(response, 'text') and response.text:
                outline_text = response.text
            elif hasattr(response, 'candidates') and response.candidates:
                outline_text = response.candidates[0].content.parts[0].text
            else:
                raise ValueError("No text content in response")
            
            outlines.append({
                "question": question,
                "outline": outline_text,
                "sources_used": len(source_documents),
                "source_documents": source_documents
            })
            
        except Exception as e:
            outlines.append({
                "question": question,
                "outline": None,
                "error": f"Error generating outline: {str(e)}"
            })
    
    return {"outlines": outlines}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)