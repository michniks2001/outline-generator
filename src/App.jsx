import { useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import Chatbot from './Chatbot'
import './App.css'

// Set up the worker for pdfjs
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker

function App() {
  const [activeTab, setActiveTab] = useState('upload') // 'upload' or 'chat'
  const [isProcessed, setIsProcessed] = useState(false)
  const [processingMessage, setProcessingMessage] = useState('')
  const [fileName, setFileName] = useState('')
  const [folderName, setFolderName] = useState('')
  const [documentTitle, setDocumentTitle] = useState('')
  const [documentAuthor, setDocumentAuthor] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [questions, setQuestions] = useState([''])
  const [outlines, setOutlines] = useState(null)
  const [isGeneratingOutline, setIsGeneratingOutline] = useState(false)

  const handleFileUpload = async (event) => {
    const file = event.target.files[0]
    
    if (!file) {
      return
    }

    // Validate file type
    if (file.type !== 'application/pdf') {
      setError('Please upload a PDF file')
      return
    }

    // Validate folder name
    if (!folderName.trim()) {
      setError('Please enter a folder name before uploading')
      return
    }

    setIsLoading(true)
    setError('')
    setIsProcessed(false)
    setProcessingMessage('')
    setFileName(file.name)

    try {
      const arrayBuffer = await file.arrayBuffer()
      const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise
      
      let fullText = ''
      
      // Extract text from all pages
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i)
        const textContent = await page.getTextContent()
        const pageText = textContent.items.map(item => item.str).join(' ')
        fullText += pageText + '\n\n'
      }

      // Check if extracted text is less than 100 characters (likely scanned PDF)
      if (fullText.trim().length < 100) {
        // Send PDF file to backend for OCR processing
        try {
          const formData = new FormData()
          formData.append('file', file)
          formData.append('folder_name', folderName.trim())
          if (documentTitle.trim()) {
            formData.append('title', documentTitle.trim())
          }
          if (documentAuthor.trim()) {
            formData.append('author', documentAuthor.trim())
          }
          
          const response = await fetch('http://localhost:8000/ocr-pdf', {
            method: 'POST',
            body: formData
          })
          
          if (!response.ok) {
            throw new Error('Failed to process PDF with OCR')
          }
          
          const data = await response.json()
          console.log('OCR response:', data)
          
          // Check if processing was successful
          if (data.folder_name && !data.error) {
            setIsProcessed(true)
            setProcessingMessage(`PDF processed with OCR successfully. ${data.total_chunks || 0} chunks stored in folder "${data.folder_name}".`)
          } else {
            setError(data.error || 'Failed to process PDF with OCR')
          }
        } catch (backendErr) {
          console.error('Error sending PDF to backend for OCR:', backendErr)
          setError('PDF appears to be scanned. OCR processing failed: ' + backendErr.message)
        }
      } else {
        // Send parsed text to backend normally
        try {
          const response = await fetch('http://localhost:8000/store-text', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
              text: fullText,
              filename: file.name,
              folder_name: folderName.trim(),
              title: documentTitle.trim() || null,
              author: documentAuthor.trim() || null
            })
          })
          
          if (!response.ok) {
            throw new Error('Failed to store text')
          }
          
          const data = await response.json()
          console.log('Backend response:', data)
          
          // Check if processing was successful
          if (data.folder_name && !data.error) {
            setIsProcessed(true)
            setProcessingMessage(`Text extracted and processed successfully. ${data.total_chunks || 0} chunks stored in folder "${data.folder_name}".`)
          } else {
            setError(data.error || 'Failed to store text')
          }
        } catch (backendErr) {
          console.error('Error sending text to backend:', backendErr)
          setError('Failed to store text: ' + backendErr.message)
        }
      }
    } catch (err) {
      setError('Error parsing PDF: ' + err.message)
      console.error('PDF parsing error:', err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleQuestionChange = (index, value) => {
    const newQuestions = [...questions]
    newQuestions[index] = value
    setQuestions(newQuestions)
  }

  const addQuestion = () => {
    setQuestions([...questions, ''])
  }

  const removeQuestion = (index) => {
    if (questions.length > 1) {
      const newQuestions = questions.filter((_, i) => i !== index)
      setQuestions(newQuestions)
    }
  }

  const handleQuestionSubmit = async (e) => {
    e.preventDefault()
    
    // Validate folder name
    if (!folderName.trim()) {
      setError('Please enter a folder name')
      return
    }
    
    // Filter out empty questions
    const validQuestions = questions.filter(q => q.trim() !== '')
    
    if (validQuestions.length === 0) {
      setError('Please enter at least one question')
      return
    }

    setIsGeneratingOutline(true)
    setError('')
    setOutlines(null)

    try {
      const response = await fetch('http://localhost:8000/generate-outline', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          questions: validQuestions,
          folder_name: folderName.trim()
        })
      })
      
      if (!response.ok) {
        throw new Error('Failed to generate outline')
      }
      
      const data = await response.json()
      
      if (data.error) {
        setError(data.error)
      } else {
        setOutlines(data)
      }
    } catch (err) {
      setError('Error generating outline: ' + err.message)
      console.error('Outline generation error:', err)
    } finally {
      setIsGeneratingOutline(false)
    }
  }

  return (
    <div className="app-container">
      <div className="landing-page">
        <h1>PDF Text Extractor & Chatbot</h1>
        <p className="subtitle">Upload PDFs, generate outlines, and chat with your documents</p>
        
        <div className="tabs">
          <button
            className={`tab-button ${activeTab === 'upload' ? 'active' : ''}`}
            onClick={() => setActiveTab('upload')}
          >
            PDF Upload & Outlines
          </button>
          <button
            className={`tab-button ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            Chatbot
          </button>
        </div>

        {activeTab === 'chat' ? (
          <Chatbot folderName={folderName} />
        ) : (
          <>
            <div className="upload-section">
          <div className="folder-input-group">
            <label htmlFor="folder-name" className="folder-label">Folder Name:</label>
            <input
              id="folder-name"
              type="text"
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
              placeholder="e.g., eyewitness testimony docs"
              className="folder-input"
              disabled={isLoading}
            />
          </div>

          <div className="document-metadata-group">
            <div className="metadata-header">
              <h3 className="metadata-section-title">Document Information</h3>
              <p className="metadata-help-text">Please provide the document title and author to avoid automatic parsing from the document.</p>
            </div>
            <div className="metadata-input-group">
              <label htmlFor="document-title" className="metadata-label">
                Document Title <span className="recommended-badge">Recommended</span>
              </label>
              <input
                id="document-title"
                type="text"
                value={documentTitle}
                onChange={(e) => setDocumentTitle(e.target.value)}
                placeholder="Enter document title"
                className="metadata-input"
                disabled={isLoading}
              />
            </div>

            <div className="metadata-input-group">
              <label htmlFor="document-author" className="metadata-label">
                Author <span className="recommended-badge">Recommended</span>
              </label>
              <input
                id="document-author"
                type="text"
                value={documentAuthor}
                onChange={(e) => setDocumentAuthor(e.target.value)}
                placeholder="Enter author name"
                className="metadata-input"
                disabled={isLoading}
              />
            </div>
          </div>
          
          <label htmlFor="pdf-upload" className="upload-button">
            {isLoading ? 'Processing...' : 'Choose PDF File'}
            <input
              id="pdf-upload"
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileUpload}
              disabled={isLoading || !folderName.trim()}
              style={{ display: 'none' }}
            />
          </label>
          
          {fileName && !isLoading && (
            <p className="file-name">File: {fileName}</p>
          )}
          
          {error && (
            <p className="error-message">{error}</p>
          )}
        </div>

        {isLoading && (
          <div className="loading">
            <div className="spinner"></div>
            <p>Extracting text from PDF...</p>
            <p style={{ fontSize: '0.9rem', color: '#888', marginTop: '0.5rem' }}>
              If this is a scanned PDF, OCR processing may take longer...
            </p>
          </div>
        )}

        {isProcessed && processingMessage && (
          <div className="success-message">
            <p>{processingMessage}</p>
          </div>
        )}

        {isProcessed && (
          <div className="questions-section">
            <h2>Ask Questions</h2>
            <p className="subtitle">Enter questions to find relevant chunks from the PDF</p>
            
            <form onSubmit={handleQuestionSubmit} className="questions-form">
              {questions.map((question, index) => (
                <div key={index} className="question-input-group">
                  <input
                    type="text"
                    value={question}
                    onChange={(e) => handleQuestionChange(index, e.target.value)}
                    placeholder={`Question ${index + 1}`}
                    className="question-input"
                  />
                  {questions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeQuestion(index)}
                      className="remove-question-button"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
              
              <div className="form-actions">
                <button
                  type="button"
                  onClick={addQuestion}
                  className="add-question-button"
                >
                  Add Question
                </button>
                <button
                  type="submit"
                  disabled={isGeneratingOutline}
                  className="submit-questions-button"
                >
                  {isGeneratingOutline ? 'Generating...' : 'Generate Outline'}
                </button>
              </div>
            </form>

            {isGeneratingOutline && (
              <div className="loading">
                <div className="spinner"></div>
                <p>Generating outline with AI...</p>
              </div>
            )}

            {outlines && (
              <div className="outline-results">
                <h3>Generated Outlines</h3>
                {outlines.outlines.map((outlineData, questionIndex) => (
                  <div key={questionIndex} className="outline-result">
                    <h4>Question: {outlineData.question}</h4>
                    {outlineData.error ? (
                      <p className="error-message">{outlineData.error}</p>
                    ) : outlineData.outline ? (
                      <div className="outline-content">
                        <div className="outline-meta">
                          <span>Chunks used: {outlineData.chunks_used || 'N/A'}</span>
                        </div>
                        <pre className="outline-text">{outlineData.outline}</pre>
                        <button 
                          className="copy-button"
                          onClick={() => {
                            navigator.clipboard.writeText(outlineData.outline)
                            alert('Outline copied to clipboard!')
                          }}
                        >
                          Copy Outline
                        </button>
                      </div>
                    ) : (
                      <p className="no-results">No outline generated for this question.</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
          </>
        )}
      </div>
    </div>
  )
}

export default App
