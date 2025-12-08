# Outline Generator

A web application that extracts text from PDF documents, stores them in a vector database, and generates research paper outlines using Google Gemini AI based on user questions.

## Features

- **PDF Text Extraction**: Client-side text extraction with OCR fallback for scanned documents
- **Vector Storage**: Stores document chunks in ChromaDB for semantic search
- **Folder-based Organization**: Organize documents into folders for better management
- **AI-Powered Outline Generation**: Uses Google Gemini to generate structured research paper outlines
- **Batch Processing**: Handles large PDFs (30+ pages) by processing in batches
- **Sentence-Aware Chunking**: Intelligent text chunking that preserves sentence boundaries

## Prerequisites

- **Python 3.8+**
- **Node.js 16+** and npm
- **Tesseract OCR** (for scanned PDF processing) 
  - Ubuntu/Debian: `sudo apt-get install tesseract-ocr`
  - Arch (btw): `sudo pacman -S tesseract`
  - macOS: `brew install tesseract`
  - Windows: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)

## Setup

### 1. Backend Setup

Navigate to the backend directory:

```bash
cd backend
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: venv\Scripts\activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file in the `backend` directory:

```bash
touch .env
```

Add the following environment variables:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_API_MODEL=your_model_name_here
```

**Getting a Gemini API Key:**
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Copy the key to your `.env` file

**Model Options:**
- `gemini-flash-latest` (already in `.env.example`)
- `gemini-pro-latest`

### 3. Frontend Setup

From the project root directory:

```bash
npm install
```

## Running the Application

### Start the Backend Server

From the `backend` directory (with virtual environment activated):

```bash
python app.py
```

The backend will run on `http://localhost:8000`

### Start the Frontend Development Server

From the project root directory (in a new terminal):

```bash
npm run dev
```

The frontend will run on `http://localhost:5173` (or another port if 5173 is occupied)

### Access the Application

Open your browser and navigate to:
```
http://localhost:5173
```

## Usage

1. **Enter Folder Name**: Specify a folder name to organize your documents (e.g., "Research Papers", "Legal Documents")

2. **Upload PDF**: 
   - Click "Choose File" and select a PDF document
   - The system will extract text client-side
   - If text extraction yields less than 100 characters, the PDF will be sent to the backend for OCR processing

3. **Process Document**:
   - The document will be chunked and stored in the vector database
   - You'll see a success message when processing is complete

4. **Generate Outline**:
   - Enter one or more questions about the uploaded documents
   - Click "Generate Outline"
   - The system will search relevant chunks and generate a structured outline using AI

## API Endpoints

- `POST /store-text` - Store extracted text in vector database
- `POST /ocr-pdf` - Process scanned PDFs with OCR
- `POST /search-chunks` - Search for relevant document chunks
- `POST /generate-outline` - Generate research paper outline from questions

## Project Structure

```
outline-gen/
├── backend/
│   ├── app.py              # FastAPI backend server
│   ├── requirements.txt    # Python dependencies
│   ├── chroma_db/          # ChromaDB persistent storage
│   └── .env                # Environment variables (create this)
├── src/
│   ├── App.jsx             # Main React component
│   ├── App.css             # Styles
│   └── main.jsx            # React entry point
├── package.json            # Node.js dependencies
└── README.md               # This file
```

## Technical Details

- **Frontend**: React + Vite
- **Backend**: FastAPI (Python)
- **Vector Database**: ChromaDB
- **AI Model**: Google Gemini
- **PDF Processing**: pdfjs-dist (client-side), pdf2image + pytesseract (OCR)
- **Text Chunking**: Sentence-boundary aware chunking (200 chars with 40 char overlap)

## Troubleshooting

### OCR Not Working
- Ensure Tesseract OCR is installed and accessible in your PATH
- Check that `pytesseract` can find the Tesseract executable

### Backend Connection Issues
- Verify the backend is running on port 8000
- Check CORS settings if accessing from a different origin

### Gemini API Errors
- Verify your API key is correct in the `.env` file
- Check that you have API quota remaining
- Ensure the model name matches available models

### Large PDF Processing
- PDFs longer than 30 pages are processed in batches of 30
- Processing time increases with document size
- Monitor backend logs for progress

## License

This project is open source and available for use.
