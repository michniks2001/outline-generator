"""
Database operations for ChromaDB.
"""
import uuid
from datetime import datetime
from fastapi.concurrency import run_in_threadpool
from pdf2image import convert_from_bytes
from io import BytesIO
from concurrent.futures import ProcessPoolExecutor

from .utils import (
    extract_title_and_author,
    chunk_text,
    ocr_image_bytes
)


class Database:
    """Database operations wrapper for ChromaDB."""
    
    def __init__(self, collection, gemini_client=None, gemini_model=None):
        self.collection = collection
        self.gemini_client = gemini_client
        self.gemini_model = gemini_model
    
    def store_text(self, text: str, folder_name: str, filename: str) -> dict:
        """
        Store extracted text in the database.
        
        Args:
            text: The text to store
            folder_name: Folder name for organization
            filename: Original filename
        
        Returns:
            Dictionary with storage results
        """
        if not folder_name:
            return {"error": "folder_name is required"}
        
        if not filename:
            return {"error": "filename is required"}
        
        timestamp = datetime.now().isoformat()
        doc_metadata = extract_title_and_author(
            text, 
            filename, 
            self.gemini_client, 
            self.gemini_model
        )
        document_title = doc_metadata["title"]
        document_author = doc_metadata["author"]
        chunks = chunk_text(text)
        chunk_ids = [str(uuid.uuid4()) for _ in chunks]
        
        self.collection.add(
            ids=chunk_ids,
            documents=chunks,
            metadatas=[
                {
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "folder_name": folder_name,
                    "source": document_title,
                    "author": document_author if document_author else "",
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
            "document_author": document_author,
            "filename": filename,
            "total_chunks": len(chunks),
            "chunk_ids": chunk_ids
        }
    
    async def ocr_pdf(self, pdf_bytes: bytes, folder_name: str, filename: str) -> dict:
        """
        Process a scanned PDF using OCR and store the extracted text.
        
        Args:
            pdf_bytes: PDF file bytes
            folder_name: Folder name for organization
            filename: Original filename
        
        Returns:
            Dictionary with processing results
        """
        if not folder_name or not folder_name.strip():
            return {"error": "folder_name is required"}
        
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
        doc_metadata = extract_title_and_author(
            combined_text, 
            filename, 
            self.gemini_client, 
            self.gemini_model
        )
        document_title = doc_metadata["title"]
        document_author = doc_metadata["author"]
        
        timestamp = datetime.now().isoformat()
        metadatas = [
            {
                "chunk_index": i,
                "total_chunks": len(all_chunks),
                "folder_name": folder_name,
                "source": document_title,
                "author": document_author if document_author else "",
                "filename": filename,
                "timestamp": timestamp
            }
            for i in range(len(all_chunks))
        ]
        
        def add_to_collection():
            self.collection.add(
                ids=all_chunk_ids,
                documents=all_chunks,
                metadatas=metadatas
            )
        
        await run_in_threadpool(add_to_collection)
        
        return {
            "message": f"PDF processed with OCR successfully in {len(batches_processed)} batch(es)",
            "folder_name": folder_name,
            "document_title": document_title,
            "document_author": document_author,
            "filename": filename,
            "total_pages": page_count,
            "total_chunks": len(all_chunks),
            "batches": batches_processed,
            "chunk_ids": all_chunk_ids
        }
    
    def get_documents(self, folder_name: str) -> dict:
        """
        Get all unique documents (with title and author) in a folder.
        
        Args:
            folder_name: Folder name to query
        
        Returns:
            Dictionary with documents list
        """
        if not folder_name:
            return {"error": "folder_name is required"}
        
        try:
            # Get all chunks from the folder
            results = self.collection.get(
                where={"folder_name": folder_name}
            )
            
            # Extract unique documents with their metadata
            documents_map = {}
            if results.get('metadatas'):
                for metadata in results['metadatas']:
                    source = metadata.get('source', 'Unknown Document')
                    author = metadata.get('author', '')
                    filename = metadata.get('filename', '')
                    
                    if source not in documents_map:
                        documents_map[source] = {
                            "title": source,
                            "author": author if author else None,
                            "filename": filename
                        }
            
            documents = list(documents_map.values())
            
            return {
                "folder_name": folder_name,
                "documents": documents,
                "count": len(documents)
            }
        except Exception as e:
            return {"error": f"Error retrieving documents: {str(e)}"}
    
    def update_document_authors(self, folder_name: str) -> dict:
        """
        Update author information for existing documents in a folder by re-extracting from stored chunks.
        
        Args:
            folder_name: Folder name to update
        
        Returns:
            Dictionary with update results
        """
        if not folder_name:
            return {"error": "folder_name is required"}
        
        if not self.gemini_client or not self.gemini_model:
            return {"error": "Gemini API key or model not configured. Author extraction requires AI."}
        
        try:
            # Get all chunks from the folder
            results = self.collection.get(
                where={"folder_name": folder_name}
            )
            
            if not results.get('ids') or len(results['ids']) == 0:
                return {"error": "No documents found in this folder"}
            
            # Group chunks by document (using source title)
            documents_chunks = {}
            if results.get('metadatas') and results.get('documents'):
                for i, metadata in enumerate(results['metadatas']):
                    source = metadata.get('source', 'Unknown Document')
                    if source not in documents_chunks:
                        documents_chunks[source] = {
                            'chunks': [],
                            'ids': [],
                            'metadata': metadata
                        }
                    documents_chunks[source]['chunks'].append(results['documents'][i])
                    documents_chunks[source]['ids'].append(results['ids'][i])
            
            updated_count = 0
            errors = []
            
            # Re-extract author for each document
            for source_title, doc_data in documents_chunks.items():
                try:
                    # Combine chunks to get full document text (first 2000 chars for extraction)
                    full_text = ' '.join(doc_data['chunks'])[:2000]
                    doc_metadata = extract_title_and_author(
                        full_text, 
                        doc_data['metadata'].get('filename'),
                        self.gemini_client,
                        self.gemini_model
                    )
                    new_author = doc_metadata.get('author', '')
                    
                    if new_author:
                        # Update all chunks for this document
                        chunk_ids = doc_data['ids']
                        # Get current metadatas
                        current_results = self.collection.get(ids=chunk_ids)
                        updated_metadatas = []
                        
                        for metadata in current_results['metadatas']:
                            updated_metadata = metadata.copy()
                            updated_metadata['author'] = new_author
                            updated_metadatas.append(updated_metadata)
                        
                        # Update in ChromaDB (delete and re-add with updated metadata)
                        self.collection.delete(ids=chunk_ids)
                        self.collection.add(
                            ids=chunk_ids,
                            documents=current_results['documents'],
                            metadatas=updated_metadatas
                        )
                        
                        updated_count += 1
                except Exception as e:
                    errors.append(f"Error updating {source_title}: {str(e)}")
            
            return {
                "message": f"Updated {updated_count} document(s)",
                "updated_count": updated_count,
                "errors": errors if errors else None
            }
        except Exception as e:
            return {"error": f"Error updating document authors: {str(e)}"}
    
    def search_chunks(self, questions: list[str], folder_name: str, n_results: int = 50) -> dict:
        """
        Search for relevant chunks in the specified folder.
        
        Args:
            questions: List of questions to search for
            folder_name: Folder name to search in
            n_results: Number of results per question
        
        Returns:
            Dictionary with search results
        """
        if not folder_name:
            return {"error": "folder_name is required"}
        
        results = []
        
        for question in questions:
            query_results = self.collection.query(
                query_texts=[question],
                n_results=n_results,
                where={"folder_name": folder_name}
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
            "note": f"Searched documents in folder: {folder_name}"
        }

