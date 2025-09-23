# Medical Legal PDF Processor

A comprehensive application for processing medical legal PDFs using **OpenAI's File Search with Vector Stores**. Upload PDFs to OpenAI, let them handle chunking and embedding automatically, then query documents using intelligent file search - no custom embedding pipeline required.

## Features

- **Multi-User Support**: Session-based isolation ensures each user gets their own instance
- **OpenAI File Search Integration**: Upload PDFs directly to OpenAI's vector stores
- **Automatic Chunking & Embedding**: OpenAI handles text extraction, chunking, and embedding
- **AI-Powered Variable Extraction**: Automatically identify key variables like body parts, injuries, etc.
- **Structured Question Processing**: Process 24+ categories of medical legal questions
- **Variable Substitution**: Dynamic question processing based on extracted variables
- **PDF Report Generation**: Create professional PDF reports with all findings
- **Configurable Verbosity**: Choose between brief, detailed, or comprehensive responses
- **Modern Web Interface**: Beautiful, responsive UI with drag-and-drop functionality
- **Resource Management**: Built-in cleanup functionality for OpenAI resources
- **Concurrent User Support**: Multiple users can access the application simultaneously without interference

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up OpenAI API Key

Create a `.env` file in the project root:

```bash
cp env_example.txt .env
```

Edit the `.env` file and add your OpenAI API key and secret key:

```
OPENAI_API_KEY=your_actual_api_key_here
SECRET_KEY=your_secret_key_here_for_sessions
```

**Note**: The `SECRET_KEY` is used for session management to ensure user isolation. Generate a random string for production use.

**Note**: This application uses OpenAI's File Search with vector stores, which requires a paid OpenAI account. Vector stores incur storage costs ($0.10 per GB per day after the first 1GB free).

### 3. Run the Application

You can run the application on either port:

**Port 1776:**
```bash
python app.py
```

**Port 1789:**
```bash
python app_1789.py
```

Then open your browser and go to:
- http://localhost:1776 (for port 1776)
- http://localhost:1789 (for port 1789)

## Multi-User Support

This application now supports multiple concurrent users through session-based isolation:

- **Session Management**: Each user gets a unique session ID stored in browser cookies
- **Isolated Processors**: Each user has their own `PDFProcessor` instance
- **Resource Isolation**: Users' OpenAI resources (vector stores, assistants, files) are completely separate
- **Concurrent Access**: Multiple users can upload different PDFs and process them simultaneously
- **Automatic Cleanup**: Users can clean up their own resources without affecting others

### Testing Multi-User Support

Run the test script to verify user isolation:

```bash
python test_user_isolation.py
```

This will simulate 4 concurrent users and verify that each gets their own isolated instance.

## How It Works

### 1. PDF Upload to OpenAI

The system uploads PDFs directly to OpenAI's File Search service:

- **File Upload**: PDFs are uploaded to OpenAI's servers
- **Vector Store Creation**: OpenAI creates a vector store for the document
- **Automatic Processing**: OpenAI handles text extraction, chunking, and embedding
- **Assistant Creation**: An AI assistant is created with file search capabilities

### 2. Variable Extraction

The system extracts key variables using file search:

- **Agreed Upon Body Parts**: Body parts both attorneys agree are affected
- **Disagreed Upon Body Parts**: Body parts with attorney disagreement
- **Previous Injuries**: All previous injuries mentioned
- **Applicant Attorney Alleged Body Parts**: Combined agreed + disagreed body parts

### 3. Question Processing

The application processes 24 main categories of questions:

1. **Demographics** - Names, addresses, claim information
2. **History of Injury** - Patient and physician perspectives
3. **Chief Complaints** - Symptoms for each body part
4. **Claimant's Job** - Job description and duties
5. **Work Status** - Current work status and restrictions
6. **Previous Injuries** - Historical injury information
7. **Medical History** - Non-surgical medical background
8. **Surgical History** - Surgical procedures
9. **Allergies** - Known allergies
10. **Current Medications** - Current medication list
11. **Social History** - Substance use history
12. **Family History** - Family medical history
13. **Diagnostic Reports** - MRI, CT, X-ray, ultrasound, EMG results
14. **Doctor's Notes** - Chronological note summaries
15. **Physical Examination** - Examination findings table
16. **Diagnostic Impressions** - Medical diagnoses per body part
17. **Causation** - Work-related injury analysis
18. **Impairment** - AMA 5th edition impairment ratings
19. **Periods of Total Disability** - Time off work estimates
20. **Future Medical Care** - MTUS/ODG guideline recommendations

### 4. Variable Substitution

For questions that reference variables (e.g., `{Agreed Upon Body Parts}`), the system:

1. Identifies the variable reference in the question
2. Retrieves the list of values for that variable
3. Creates separate API calls for each value
4. Combines the results in the final report

### 5. Report Generation

The system generates a professional PDF report with:

- Structured sections and subsections
- Proper formatting and styling
- Timestamp and metadata
- All question responses organized by category

## Configuration

### Verbosity Levels

- **Brief**: Concise, essential information only
- **Detailed**: Balanced responses with good detail (default)
- **Comprehensive**: Extensive, thorough responses

### Customization

You can easily modify:

- **Questions**: Edit the `questions_config` in `app.py`
- **Variables**: Modify the `variables_config` in `app.py`
- **Report Styling**: Adjust PDF styling in the `generate_pdf_report` method
- **UI Appearance**: Customize CSS in `templates/index.html`

## API Endpoints

- `GET /` - Main interface
- `POST /upload` - Upload PDF file to OpenAI File Search
- `POST /process` - Process PDF using file search and extract information
- `POST /generate-report` - Generate and download PDF report
- `POST /set-verbosity` - Set response verbosity level
- `POST /cleanup` - Clean up OpenAI resources for current user
- `GET /api/status` - Get current user's processing status
- `GET /api/session-info` - Get current user's session information
- `POST /api/cleanup-all` - Clean up resources for all users (admin function)

## File Structure

```
SweetButter/
├── app.py                 # Main Flask application (port 1776)
├── app_1789.py           # Alternative port runner (port 1789)
├── requirements.txt       # Python dependencies
├── env_example.txt       # Environment variables example
├── README.md             # This file
└── templates/
    └── index.html        # Web interface
```

## Troubleshooting

### Common Issues

1. **OpenAI API Errors**: Ensure your API key is valid and has sufficient credits
2. **PDF Upload Issues**: Make sure the file is a valid PDF and not corrupted
3. **Vector Store Costs**: Be aware of storage costs for vector stores ($0.10 per GB per day)
4. **Processing Time**: Large PDFs may take longer to process due to OpenAI's chunking and embedding
5. **Port Conflicts**: If ports 1776/1789 are in use, modify the port numbers in the Python files
6. **Resource Cleanup**: Use the cleanup button to remove vector stores and avoid ongoing charges

### Error Handling

The application includes comprehensive error handling for:

- Invalid PDF files
- OpenAI API failures
- Vector store creation errors
- File upload timeouts
- Assistant creation failures
- Resource cleanup issues

## Contributing

To extend the application:

1. Add new questions to the `questions_config` dictionary
2. Create new variable types in the `variables_config`
3. Modify the PDF report template as needed
4. Enhance the UI for additional features

## License

This project is for educational and professional use in medical legal document processing.
