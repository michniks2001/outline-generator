import { useState, useEffect, useRef, useCallback } from 'react'
import SourceModal from './SourceModal'
import './Chatbot.css'

function Chatbot({ folderName }) {
  const [sessions, setSessions] = useState([])
  const [currentSessionId, setCurrentSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [selectedSource, setSelectedSource] = useState(null)
  const [selectedChunks, setSelectedChunks] = useState(null)
  const [selectedAuthor, setSelectedAuthor] = useState(null)
  const messagesEndRef = useRef(null)
  const lastFolderNameRef = useRef(folderName)

  const createNewSession = useCallback(() => {
    const newSession = {
      id: Date.now().toString(),
      folderName: folderName,
      title: folderName ? `Chat - ${folderName}` : 'New Chat',
      createdAt: new Date().toISOString(),
      messages: []
    }
    setSessions(prev => [newSession, ...prev])
    setCurrentSessionId(newSession.id)
    setMessages([])
    setError('')
  }, [folderName])

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Create new session when folder changes
  useEffect(() => {
    if (folderName && folderName !== lastFolderNameRef.current) {
      lastFolderNameRef.current = folderName
      createNewSession()
    }
  }, [folderName, createNewSession])

  // Load messages for current session
  useEffect(() => {
    if (currentSessionId) {
      const session = sessions.find(s => s.id === currentSessionId)
      if (session) {
        setMessages(session.messages || [])
      }
    } else {
      setMessages([])
    }
  }, [currentSessionId, sessions])

  const switchSession = (sessionId) => {
    setCurrentSessionId(sessionId)
    setError('')
  }

  const deleteSession = (sessionId, e) => {
    e.stopPropagation()
    const newSessions = sessions.filter(s => s.id !== sessionId)
    setSessions(newSessions)
    
    if (sessionId === currentSessionId) {
      if (newSessions.length > 0) {
        setCurrentSessionId(newSessions[0].id)
      } else {
        setCurrentSessionId(null)
        setMessages([])
      }
    }
  }

  const sendMessage = async () => {
    if (!inputMessage.trim() || !folderName.trim()) {
      setError('Please enter a message and folder name')
      return
    }

    if (!currentSessionId) {
      createNewSession()
      // Wait a bit for session to be created
      await new Promise(resolve => setTimeout(resolve, 100))
    }

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: inputMessage.trim(),
      timestamp: new Date().toISOString()
    }

    // Add user message immediately
    const updatedMessages = [...messages, userMessage]
    setMessages(updatedMessages)
    setInputMessage('')
    setIsLoading(true)
    setError('')

    // Update session with user message
    updateSessionMessages(currentSessionId, updatedMessages)

    try {
      // Build conversation history (excluding the current message we just added)
      const conversationHistory = updatedMessages.slice(0, -1).map(msg => ({
        role: msg.role,
        content: msg.content
      }))

      // Create assistant message placeholder for streaming
      const assistantMessageId = Date.now()
      const assistantMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        sources: [],
        sourceChunks: {},
        sourceAuthors: {},
        timestamp: new Date().toISOString()
      }

      const messagesWithPlaceholder = [...updatedMessages, assistantMessage]
      setMessages(messagesWithPlaceholder)

      const response = await fetch('http://localhost:8000/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: inputMessage.trim(),
          folder_name: folderName.trim(),
          conversation_history: conversationHistory
        })
      })

      if (!response.ok) {
        throw new Error('Failed to get response')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let fullResponse = ''
      let sources = []
      let sourceChunks = {}
      let sourceAuthors = {}

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue

          try {
            const data = JSON.parse(line)
            
            if (data.type === 'metadata') {
              sources = data.sources || []
              sourceAuthors = data.source_authors || {}
            } else if (data.type === 'chunk') {
              fullResponse += data.content
              // Update the message in real-time
              setMessages(prev => prev.map(msg => 
                msg.id === assistantMessageId
                  ? { ...msg, content: fullResponse }
                  : msg
              ))
            } else if (data.type === 'complete') {
              sources = data.sources || sources
              sourceChunks = data.source_chunks || sourceChunks
              // Update message with sources
              setMessages(prev => prev.map(msg => 
                msg.id === assistantMessageId
                  ? { ...msg, sources: sources, sourceChunks: sourceChunks, sourceAuthors: sourceAuthors }
                  : msg
              ))
            } else if (data.type === 'error') {
              throw new Error(data.error)
            } else if (data.error) {
              throw new Error(data.error)
            }
          } catch (e) {
            // Skip invalid JSON lines
            if (e.message.includes('JSON')) continue
            throw e
          }
        }
      }

      // Finalize the message with all data (sources already updated in complete handler)
      const finalAssistantMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: fullResponse,
        sources: sources,
        sourceChunks: sourceChunks,
        sourceAuthors: sourceAuthors,
        timestamp: new Date().toISOString()
      }

      const finalMessages = [...updatedMessages, finalAssistantMessage]
      setMessages(finalMessages)
      updateSessionMessages(currentSessionId, finalMessages)

      // Update session title if it's the first message
      if (updatedMessages.length === 1) {
        updateSessionTitle(currentSessionId, inputMessage.trim().substring(0, 50))
      }

    } catch (err) {
      setError('Error: ' + err.message)
      console.error('Chat error:', err)
      // Remove the user message on error
      setMessages(messages)
      updateSessionMessages(currentSessionId, messages)
    } finally {
      setIsLoading(false)
    }
  }

  const updateSessionMessages = (sessionId, newMessages) => {
    setSessions(prevSessions =>
      prevSessions.map(session =>
        session.id === sessionId
          ? { ...session, messages: newMessages }
          : session
      )
    )
  }

  const updateSessionTitle = (sessionId, title) => {
    setSessions(prevSessions =>
      prevSessions.map(session =>
        session.id === sessionId
          ? { ...session, title: title.length > 50 ? title.substring(0, 50) + '...' : title }
          : session
      )
    )
  }

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="chatbot-container">
      <div className="chatbot-sidebar">
        <div className="sidebar-header">
          <h3>Chat Sessions</h3>
          <button className="new-chat-button" onClick={createNewSession}>
            + New Chat
          </button>
        </div>
        <div className="sessions-list">
          {sessions.length === 0 ? (
            <p className="no-sessions">No chat sessions yet</p>
          ) : (
            sessions.map(session => (
              <div
                key={session.id}
                className={`session-item ${session.id === currentSessionId ? 'active' : ''}`}
                onClick={() => switchSession(session.id)}
              >
                <div className="session-content">
                  <div className="session-title">{session.title}</div>
                  <div className="session-meta">
                    {session.folderName && (
                      <span className="session-folder">{session.folderName}</span>
                    )}
                  </div>
                </div>
                <button
                  className="delete-session-button"
                  onClick={(e) => deleteSession(session.id, e)}
                  title="Delete session"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="chatbot-main">
        {!currentSessionId ? (
          <div className="chatbot-welcome">
            <h2>Start a Conversation</h2>
            <p>Create a new chat session to ask questions about your documents</p>
            <button className="start-chat-button" onClick={createNewSession}>
              New Chat
            </button>
          </div>
        ) : (
          <>
            <div className="chatbot-header">
              <h3>{sessions.find(s => s.id === currentSessionId)?.title || 'Chat'}</h3>
              {folderName && (
                <span className="current-folder">Folder: {folderName}</span>
              )}
            </div>

            <div className="messages-container">
              {messages.length === 0 ? (
                <div className="empty-chat">
                  <p>Start a conversation by asking a question about your documents</p>
                </div>
              ) : (
                messages.map((message, index) => (
                  <div key={message.id || index} className={`message ${message.role}`}>
                    <div className="message-header">
                      <span className="message-role">
                        {message.role === 'user' ? 'You' : 'Assistant'}
                      </span>
                      {message.sources && message.sources.length > 0 && (
                        <div className="message-sources">
                          <span className="sources-label">Sources:</span>
                          {message.sources.map((source, i) => {
                            const sourceData = message.sourceChunks?.[source]
                            const chunks = sourceData?.chunks || null
                            const author = message.sourceAuthors?.[source] || sourceData?.author || null
                            const displayText = author ? `${source} (${author})` : source
                            return (
                              <span
                                key={i}
                                className={`source-tag ${chunks ? 'clickable' : ''}`}
                                title={chunks ? `Click to view source text` : displayText}
                                onClick={() => {
                                  if (chunks) {
                                    setSelectedSource(source)
                                    setSelectedChunks(chunks)
                                    setSelectedAuthor(author)
                                    setIsModalOpen(true)
                                  }
                                }}
                              >
                                {displayText}
                              </span>
                            )
                          })}
                        </div>
                      )}
                    </div>
                    <div className="message-content">
                      {message.content.split('\n').map((line, i) => (
                        <div key={i}>{line}</div>
                      ))}
                    </div>
                  </div>
                ))
              )}
              {isLoading && (
                <div className="message assistant">
                  <div className="message-header">
                    <span className="message-role">Assistant</span>
                  </div>
                  <div className="message-content">
                    <div className="typing-indicator">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {error && (
              <div className="chatbot-error">{error}</div>
            )}

            <div className="chatbot-input-container">
              <textarea
                className="chatbot-input"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Ask a question or request a quote..."
                disabled={isLoading || !folderName.trim()}
                rows={3}
              />
              <button
                className="send-button"
                onClick={sendMessage}
                disabled={isLoading || !inputMessage.trim() || !folderName.trim()}
              >
                Send
              </button>
            </div>
          </>
        )}
      </div>

      <SourceModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        sourceTitle={selectedSource}
        chunks={selectedChunks}
        author={selectedAuthor}
      />
    </div>
  )
}

export default Chatbot

