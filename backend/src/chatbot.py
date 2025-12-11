"""
Chatbot functions for handling chat queries and generating responses.
"""
import re
from .utils import clean_filename
import json


def process_chat_query_stream(
    collection,
    message: str,
    folder_name: str,
    conversation_history: list,
    gemini_client,
    gemini_model,
    n_results: int = 20
):
    """
    Process a chat query and stream the response with source citations.
    
    Args:
        collection: ChromaDB collection
        message: User's message
        folder_name: Folder name to search in
        conversation_history: Previous conversation messages
        gemini_client: Gemini AI client
        gemini_model: Gemini model name
        n_results: Number of chunks to retrieve
    
    Yields:
        JSON strings with streaming response chunks
    """
    if not gemini_client or not gemini_model:
        yield json.dumps({
            "error": "Gemini API key or model not configured. Please set GEMINI_API_KEY and GEMINI_API_MODEL in .env file"
        }) + "\n"
        return
    
    if not folder_name:
        yield json.dumps({"error": "folder_name is required"}) + "\n"
        return
    
    if not message or not message.strip():
        yield json.dumps({"error": "message is required"}) + "\n"
        return
    
    try:
        # Stage 1: Retrieve relevant chunks from the folder
        query_results = collection.query(
            query_texts=[message],
            n_results=n_results,
            where={"folder_name": folder_name}
        )
        
        # Organize chunks by document
        documents_data = {}
        if query_results['documents'] and len(query_results['documents'][0]) > 0:
            documents = query_results['documents'][0]
            metadatas = query_results.get('metadatas', [[]])[0] if query_results.get('metadatas') else []
            distances = query_results.get('distances', [[]])[0] if query_results.get('distances') else []
            
            for i in range(len(documents)):
                metadata = metadatas[i] if i < len(metadatas) else {}
                source_title = metadata.get('source', 'Unknown Document')
                source_author = metadata.get('author', '')
                distance = distances[i] if i < len(distances) else 1.0
                
                # Only include reasonably relevant chunks (distance < 0.85)
                if distance < 0.85:
                    if source_title not in documents_data:
                        documents_data[source_title] = {
                            'author': source_author if source_author else None,
                            'chunks': []
                        }
                    
                    documents_data[source_title]['chunks'].append({
                        'text': documents[i],
                        'distance': distance,
                        'metadata': metadata
                    })
        
        if not documents_data:
            yield json.dumps({
                "error": "No relevant information found in the folder for this question.",
                "response": None,
                "sources": []
            }) + "\n"
            return
        
        # Sort chunks within each document by relevance
        for doc_title in documents_data:
            documents_data[doc_title]['chunks'].sort(key=lambda x: x['distance'])
        
        # Stage 2: Build context from top chunks
        context_parts = []
        source_documents = []
        source_authors = {}
        
        # Take top chunks from each document (up to 5 chunks per document)
        for doc_title in sorted(documents_data.keys()):
            doc_data = documents_data[doc_title]
            chunks = doc_data['chunks'][:5]  # Top 5 chunks per doc
            author = doc_data.get('author')
            source_documents.append(doc_title)
            if author:
                source_authors[doc_title] = author
            
            doc_context = f"\n{'='*60}\nSOURCE: {doc_title}\n{'='*60}\n"
            for chunk in chunks:
                doc_context += f"\n{chunk['text']}\n"
            
            context_parts.append(doc_context)
        
        full_context = "\n".join(context_parts)
        
        # Stage 3: Build conversation history for context
        conversation_context = ""
        if conversation_history:
            conversation_context = "\n\nPrevious conversation:\n"
            for msg in conversation_history[-6:]:  # Last 6 messages for context
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                conversation_context += f"{role.capitalize()}: {content}\n"
        
        # Stage 4: Generate response with citations (streaming)
        prompt = f"""You are a helpful assistant answering questions based on the provided source documents.

USER QUESTION:
{message}
{conversation_context}

SOURCE DOCUMENTS AVAILABLE:
{chr(10).join([f"  - {doc}" for doc in source_documents])}

CONTEXT FROM SOURCES:
{full_context}

INSTRUCTIONS:
1. Answer the user's question based ONLY on the provided source documents
2. When referencing information from a source, cite it using the format: [Source Title]
3. Use the EXACT source titles shown above (e.g., if a source is "Memory Faults and Fixes", use exactly "[Memory Faults and Fixes]")
4. If information comes from multiple sources, cite all of them: [Source1; Source2]
5. Be concise but thorough
6. If the question cannot be answered from the sources, say so clearly
7. Include specific details, quotes, or examples from the sources when relevant

Generate your response:"""

        # Send metadata first
        yield json.dumps({
            "type": "metadata",
            "sources": source_documents,
            "source_authors": source_authors
        }) + "\n"
        
        # Stream response using Gemini
        response_stream = gemini_client.models.generate_content_stream(
            model=gemini_model,
            contents=prompt
        )
        
        # Stream chunks and collect full response for source extraction
        full_response = ""
        for chunk in response_stream:
            chunk_text = ""
            if hasattr(chunk, 'text') and chunk.text:
                chunk_text = chunk.text
            elif hasattr(chunk, 'candidates') and chunk.candidates:
                if chunk.candidates[0].content.parts:
                    chunk_text = chunk.candidates[0].content.parts[0].text
            
            if chunk_text:
                full_response += chunk_text
                yield json.dumps({
                    "type": "chunk",
                    "content": chunk_text
                }) + "\n"
        
        # After streaming is complete, extract sources and send source chunks
        cited_sources = []
        citation_pattern = r'\[([^\]]+)\]'
        citations = re.findall(citation_pattern, full_response)
        for citation in citations:
            sources = re.split(r'[;,]', citation)
            for source in sources:
                source = source.strip()
                if source and source not in cited_sources:
                    for doc_title in source_documents:
                        if source.lower() in doc_title.lower() or doc_title.lower() in source.lower():
                            cited_sources.append(doc_title)
                            break
                    else:
                        cited_sources.append(source)
        
        # Remove duplicates
        seen = set()
        unique_cited_sources = []
        for source in cited_sources:
            if source not in seen:
                seen.add(source)
                unique_cited_sources.append(source)
        
        # Build source chunks data
        source_chunks_data = {}
        for doc_title in source_documents:
            doc_data = documents_data[doc_title]
            chunks = doc_data['chunks'][:5]
            source_chunks_data[doc_title] = {
                "author": doc_data.get('author'),
                "chunks": [
                    {
                        "text": chunk['text'],
                        "distance": chunk['distance'],
                        "metadata": chunk['metadata']
                    }
                    for chunk in chunks
                ]
            }
        
        # Send final metadata with sources
        yield json.dumps({
            "type": "complete",
            "sources": unique_cited_sources,
            "source_chunks": source_chunks_data
        }) + "\n"
        
    except Exception as e:
        yield json.dumps({
            "type": "error",
            "error": f"Error generating response: {str(e)}"
        }) + "\n"


def process_chat_query(
    collection,
    message: str,
    folder_name: str,
    conversation_history: list,
    gemini_client,
    gemini_model,
    n_results: int = 20
) -> dict:
    """
    Process a chat query and generate a response with source citations.
    
    Args:
        collection: ChromaDB collection
        message: User's message
        folder_name: Folder name to search in
        conversation_history: Previous conversation messages
        gemini_client: Gemini AI client
        gemini_model: Gemini model name
        n_results: Number of chunks to retrieve
    
    Returns:
        Dictionary with response, sources, and source chunks
    """
    if not gemini_client or not gemini_model:
        return {
            "error": "Gemini API key or model not configured. Please set GEMINI_API_KEY and GEMINI_API_MODEL in .env file"
        }
    
    if not folder_name:
        return {"error": "folder_name is required"}
    
    if not message or not message.strip():
        return {"error": "message is required"}
    
    try:
        # Stage 1: Retrieve relevant chunks from the folder
        query_results = collection.query(
            query_texts=[message],
            n_results=n_results,
            where={"folder_name": folder_name}
        )
        
        # Organize chunks by document
        documents_data = {}
        if query_results['documents'] and len(query_results['documents'][0]) > 0:
            documents = query_results['documents'][0]
            metadatas = query_results.get('metadatas', [[]])[0] if query_results.get('metadatas') else []
            distances = query_results.get('distances', [[]])[0] if query_results.get('distances') else []
            
            for i in range(len(documents)):
                metadata = metadatas[i] if i < len(metadatas) else {}
                source_title = metadata.get('source', 'Unknown Document')
                source_author = metadata.get('author', '')
                distance = distances[i] if i < len(distances) else 1.0
                
                # Only include reasonably relevant chunks (distance < 0.85)
                if distance < 0.85:
                    if source_title not in documents_data:
                        documents_data[source_title] = {
                            'author': source_author if source_author else None,
                            'chunks': []
                        }
                    
                    documents_data[source_title]['chunks'].append({
                        'text': documents[i],
                        'distance': distance,
                        'metadata': metadata
                    })
        
        if not documents_data:
            return {
                "error": "No relevant information found in the folder for this question.",
                "response": None,
                "sources": []
            }
        
        # Sort chunks within each document by relevance
        for doc_title in documents_data:
            documents_data[doc_title]['chunks'].sort(key=lambda x: x['distance'])
        
        # Stage 2: Build context from top chunks
        context_parts = []
        source_documents = []
        source_authors = {}
        
        # Take top chunks from each document (up to 5 chunks per document)
        for doc_title in sorted(documents_data.keys()):
            doc_data = documents_data[doc_title]
            chunks = doc_data['chunks'][:5]  # Top 5 chunks per doc
            author = doc_data.get('author')
            source_documents.append(doc_title)
            if author:
                source_authors[doc_title] = author
            
            doc_context = f"\n{'='*60}\nSOURCE: {doc_title}\n{'='*60}\n"
            for chunk in chunks:
                doc_context += f"\n{chunk['text']}\n"
            
            context_parts.append(doc_context)
        
        full_context = "\n".join(context_parts)
        
        # Stage 3: Build conversation history for context
        conversation_context = ""
        if conversation_history:
            conversation_context = "\n\nPrevious conversation:\n"
            for msg in conversation_history[-6:]:  # Last 6 messages for context
                role = msg.get('role', 'user')
                content = msg.get('content', '')
                conversation_context += f"{role.capitalize()}: {content}\n"
        
        # Stage 4: Generate response with citations
        prompt = f"""You are a helpful assistant answering questions based on the provided source documents.

USER QUESTION:
{message}
{conversation_context}

SOURCE DOCUMENTS AVAILABLE:
{chr(10).join([f"  - {doc}" for doc in source_documents])}

CONTEXT FROM SOURCES:
{full_context}

INSTRUCTIONS:
1. Answer the user's question based ONLY on the provided source documents
2. When referencing information from a source, cite it using the format: [Source Title]
3. Use the EXACT source titles shown above (e.g., if a source is "Memory Faults and Fixes", use exactly "[Memory Faults and Fixes]")
4. If information comes from multiple sources, cite all of them: [Source1; Source2]
5. Be concise but thorough
6. If the question cannot be answered from the sources, say so clearly
7. Include specific details, quotes, or examples from the sources when relevant

Generate your response:"""

        # Generate response using Gemini (streaming)
        response_stream = gemini_client.models.generate_content_stream(
            model=gemini_model,
            contents=prompt
        )
        
        # Collect streamed response
        response_text = ""
        for chunk in response_stream:
            if hasattr(chunk, 'text') and chunk.text:
                response_text += chunk.text
            elif hasattr(chunk, 'candidates') and chunk.candidates:
                if chunk.candidates[0].content.parts:
                    response_text += chunk.candidates[0].content.parts[0].text
        
        if not response_text:
            raise ValueError("No text content in response")
        
        # Extract cited sources from response
        cited_sources = []
        # Look for citations in format [Source Title] or [Source1; Source2]
        citation_pattern = r'\[([^\]]+)\]'
        citations = re.findall(citation_pattern, response_text)
        for citation in citations:
            # Handle multiple sources separated by semicolon or comma
            sources = re.split(r'[;,]', citation)
            for source in sources:
                source = source.strip()
                if source and source not in cited_sources:
                    # Only add if it matches one of our source documents (case-insensitive partial match)
                    for doc_title in source_documents:
                        if source.lower() in doc_title.lower() or doc_title.lower() in source.lower():
                            cited_sources.append(doc_title)
                            break
                    else:
                        # If no match found, add the source as-is (might be a partial name)
                        cited_sources.append(source)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_cited_sources = []
        for source in cited_sources:
            if source not in seen:
                seen.add(source)
                unique_cited_sources.append(source)
        
        cited_sources = unique_cited_sources
        
        # Build source chunks data for frontend display
        source_chunks_data = {}
        for doc_title in source_documents:
            doc_data = documents_data[doc_title]
            chunks = doc_data['chunks'][:5]  # Top 5 chunks per doc
            source_chunks_data[doc_title] = {
                "author": doc_data.get('author'),
                "chunks": [
                    {
                        "text": chunk['text'],
                        "distance": chunk['distance'],
                        "metadata": chunk['metadata']
                    }
                    for chunk in chunks
                ]
            }
        
        return {
            "response": response_text,
            "sources": list(set(cited_sources)),  # Remove duplicates
            "all_available_sources": source_documents,
            "source_authors": source_authors,  # Map of source title -> author
            "source_chunks": source_chunks_data  # Map of source title -> {author, chunks}
        }
        
    except Exception as e:
        return {
            "error": f"Error generating response: {str(e)}",
            "response": None,
            "sources": []
        }
