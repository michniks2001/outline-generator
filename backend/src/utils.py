"""
Utility functions for text processing, title extraction, and OCR.
"""
import re
import json
from io import BytesIO
from PIL import Image
import pytesseract


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


def extract_title_and_author(text: str, fallback_name: str = None, gemini_client=None, gemini_model=None) -> dict:
    """
    Extract title and author from document text using AI if available, otherwise fallback to simple extraction.
    
    Args:
        text: The document text
        fallback_name: Fallback name (filename) if title cannot be extracted
        gemini_client: Gemini AI client (optional)
        gemini_model: Gemini model name (optional)
    
    Returns:
        Dictionary with 'title' and 'author' keys
    """
    cleaned_filename = clean_filename(fallback_name) if fallback_name else None
    
    # Try AI extraction if Gemini is available
    if gemini_client and gemini_model and text:
        try:
            # Use first 2000 characters for extraction (usually contains title page info)
            extraction_text = text[:2000].strip()
            
            prompt = f"""Extract the document title and author from the following text. 
Return ONLY a JSON object with "title" and "author" fields.
If author is not found, use null for author.
If title is not found, use null for title.
Be precise - use the exact title and author names as they appear.

Text:
{extraction_text}

Return JSON format:
{{"title": "...", "author": "..."}}"""

            response = gemini_client.models.generate_content(
                model=gemini_model,
                contents=prompt
            )
            
            # Extract text from response
            if hasattr(response, 'text') and response.text:
                response_text = response.text.strip()
            elif hasattr(response, 'candidates') and response.candidates:
                response_text = response.candidates[0].content.parts[0].text.strip()
            else:
                raise ValueError("No text content in response")
            
            # Try to parse JSON from response
            # Remove markdown code blocks if present
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*', '', response_text)
            response_text = response_text.strip()
            
            try:
                result = json.loads(response_text)
                title = result.get('title', None)
                author = result.get('author', None)
                
                # Validate and clean results
                if title and isinstance(title, str) and len(title.strip()) > 0:
                    title = title.strip()
                else:
                    title = None
                
                if author and isinstance(author, str) and len(author.strip()) > 0:
                    author = author.strip()
                else:
                    author = None
                
                # Fallback to simple extraction if AI didn't find title
                if not title:
                    title = extract_title(text, fallback_name)
                elif not cleaned_filename:
                    pass  # Use AI-extracted title
                else:
                    # Use AI title if it's different from filename
                    if title.lower() != cleaned_filename.lower():
                        pass  # Use AI title
                    else:
                        title = cleaned_filename
                
                return {
                    "title": title or cleaned_filename or "Untitled Document",
                    "author": author
                }
            except json.JSONDecodeError:
                # If JSON parsing fails, fall back to simple extraction
                pass
        except Exception as e:
            print(f"AI extraction failed: {e}, falling back to simple extraction")
            pass
    
    # Fallback to simple title extraction
    title = extract_title(text, fallback_name)
    return {
        "title": title,
        "author": None
    }


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
    image = Image.open(BytesIO(image_bytes))
    text = pytesseract.image_to_string(image)
    return text

