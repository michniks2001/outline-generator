import { useEffect } from 'react'
import './SourceModal.css'

function SourceModal({ isOpen, onClose, sourceTitle, chunks, author }) {
  // Handle ESC key to close modal
  useEffect(() => {
    const handleEsc = (event) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    if (isOpen) {
      document.addEventListener('keydown', handleEsc)
      // Prevent body scroll when modal is open
      document.body.style.overflow = 'hidden'
    }

    return () => {
      document.removeEventListener('keydown', handleEsc)
      document.body.style.overflow = 'unset'
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 className="modal-title">{sourceTitle || 'Unknown'}</h2>
            {author && (
              <p className="modal-author">by {author}</p>
            )}
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal-body">
          {chunks && chunks.length > 0 ? (
            <div className="chunks-list">
              {chunks.map((chunk, index) => (
                <div key={index} className="chunk-display">
                  <div className="chunk-header">
                    <span className="chunk-number">Chunk {index + 1}</span>
                    {chunk.distance !== undefined && (
                      <span className="chunk-relevance">
                        Relevance: {(1 - chunk.distance).toFixed(2)}
                      </span>
                    )}
                  </div>
                  <div className="chunk-text">{chunk.text}</div>
                  {chunk.metadata && (
                    <div className="chunk-metadata">
                      {chunk.metadata.filename && (
                        <span>File: {chunk.metadata.filename}</span>
                      )}
                      {chunk.metadata.chunk_index !== undefined && (
                        <span>Chunk {chunk.metadata.chunk_index + 1} of {chunk.metadata.total_chunks}</span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="no-chunks">
              <p>No chunks available for this source.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default SourceModal

