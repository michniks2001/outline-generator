"""
Outline generation functions for research paper outlines.
"""
from .utils import clean_filename


def generate_outline(
    collection,
    question: str,
    folder_name: str,
    gemini_client,
    gemini_model,
    n_results: int = 50
) -> dict:
    """
    Generate an outline for a research paper based on a question.
    
    Args:
        collection: ChromaDB collection
        question: Question to generate outline for
        folder_name: Folder name to search in
        gemini_client: Gemini AI client
        gemini_model: Gemini model name
        n_results: Number of chunks to retrieve
    
    Returns:
        Dictionary with outline, sources, and metadata
    """
    if not gemini_client or not gemini_model:
        return {
            "error": "Gemini API key or model not configured. Please set GEMINI_API_KEY and GEMINI_API_MODEL in .env file"
        }
    
    if not folder_name:
        return {"error": "folder_name is required"}
    
    try:
        # Stage 1: Retrieve chunks from ALL documents in folder
        query_results = collection.query(
            query_texts=[question],
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
            return {
                "question": question,
                "outline": None,
                "error": "No relevant chunks found for this question."
            }
        
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
            model=gemini_model,
            contents=prompt
        )
        
        # Extract text from response
        if hasattr(response, 'text') and response.text:
            outline_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            outline_text = response.candidates[0].content.parts[0].text
        else:
            raise ValueError("No text content in response")
        
        return {
            "question": question,
            "outline": outline_text,
            "sources_used": len(source_documents),
            "source_documents": source_documents
        }
        
    except Exception as e:
        return {
            "question": question,
            "outline": None,
            "error": f"Error generating outline: {str(e)}"
        }

