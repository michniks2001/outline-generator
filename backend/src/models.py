"""
Pydantic models for API request/response validation.
"""
from pydantic import BaseModel


class TextRequest(BaseModel):
    """Request model for storing text."""
    text: str
    folder_name: str
    filename: str
    title: str = None  # Optional: user-provided title
    author: str = None  # Optional: user-provided author


class QuestionsRequest(BaseModel):
    """Request model for questions-based queries."""
    questions: list[str]
    folder_name: str


class ChatRequest(BaseModel):
    """Request model for chat queries."""
    message: str
    folder_name: str
    conversation_history: list[dict] = []  # List of {role: "user"|"assistant", content: str}


class FolderRequest(BaseModel):
    """Request model for folder-based operations."""
    folder_name: str

