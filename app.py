import os
import json
import logging
import secrets
import uuid
from flask import Flask, request, jsonify, render_template, send_file, session
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import re
from datetime import datetime, timedelta
import tempfile
import time
import PyPDF2
import fitz  # PyMuPDF for better PDF text extraction
from xml.sax.saxutils import escape
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure Flask for large file uploads (up to 2GB for 5000-10,000 page PDFs)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['MAX_CONTENT_PATH'] = None

# Persistent uploads directory (per-user history)
UPLOADS_ROOT = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOADS_ROOT, exist_ok=True)

# Configure session management for user isolation
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Ensure sessions persist across browser restarts for history continuity
@app.before_request
def _make_session_permanent():
    session.permanent = True

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client with longer timeout for large file uploads
# Use a very long timeout for large files (up to 30 minutes for very large files)
client = OpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    timeout=1800.0  # 30 minutes timeout for very large file operations
)

# User processor management for session isolation
user_processors = {}

def get_user_processor():
    """Get or create a processor instance for the current user session"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
        logger.info(f"Created new user session: {session['user_id']}")
    
    user_id = session['user_id']
    if user_id not in user_processors:
        user_processors[user_id] = PDFProcessor()
        logger.info(f"Created new processor for user: {user_id}")
    
    return user_processors[user_id]

def cleanup_user_processor(user_id):
    """Clean up resources for a specific user"""
    if user_id in user_processors:
        try:
            user_processors[user_id].cleanup_resources()
            logger.info(f"Cleaned up resources for user: {user_id}")
        except Exception as e:
            logger.error(f"Error cleaning up user {user_id}: {str(e)}")
        finally:
            del user_processors[user_id]
            logger.info(f"Removed processor for user: {user_id}")

def _get_user_upload_dir() -> str:
    """Return absolute path to the current user's uploads directory, creating it if needed."""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    user_dir = os.path.join(UPLOADS_ROOT, session['user_id'])
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

class PDFProcessor:
    def __init__(self):
        self.verbosity = "detailed"  # Can be "brief", "detailed", or "comprehensive"
        self.pdf_content = None
        self.variables = {}
        self.vector_store_id = None
        self.assistant_id = None
        self.uploaded_file_id = None
        self.file_name = None
        self._pages_cache = {}
        self.chat_thread_id = None
        self._cache_size_limit = 100 * 1024 * 1024  # 100MB max cache size
        
    def _strip_inline_markers(self, text: str) -> str:
        """Remove inline source markers like [4:5†source] or 【source】 from text."""
        try:
            t = str(text or '')
            t = re.sub(r"[【\[]\d+(?::\d+)?\s*†?source[】\]]", "", t, flags=re.IGNORECASE)
            t = re.sub(r"[【\[]\s*source\s*[】\]]", "", t, flags=re.IGNORECASE)
            return t.strip()
        except Exception:
            return str(text or '')

    def _normalize_for_match(self, text: str) -> str:
        """Normalize text for fuzzy contains matching (lowercase, collapse spaces, strip punctuation)."""
        t = re.sub(r"\s+", " ", str(text or '').lower()).strip()
        # Remove most punctuation/specials; keep spaces and alphanumerics
        t = re.sub(r"[^a-z0-9 ]+", "", t)
        return t

    def extract_pdf_text(self, pdf_file, file_size_bytes=None):
        """Upload PDF to OpenAI and create vector store"""
        file_size_mb = 0  # Initialize for error handling
        try:
            # Reset file pointer to beginning
            pdf_file.seek(0)
            
            # Get file size if not provided
            if file_size_bytes is None:
                pdf_file.seek(0, 2)  # Seek to end
                file_size_bytes = pdf_file.tell()
                pdf_file.seek(0)  # Reset to beginning
            
            file_size_mb = file_size_bytes / (1024 * 1024)
            logger.info(f"Processing file: {file_size_mb:.2f} MB")
            
            # Create a temporary file to save the uploaded PDF using chunked reading for large files
            temp_file_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                    temp_file_path = temp_file.name
                    # Use chunked reading for files larger than 100MB
                    chunk_size = 10 * 1024 * 1024  # 10MB chunks
                    if file_size_bytes > 100 * 1024 * 1024:
                        logger.info("Using chunked reading for large file")
                        while True:
                            chunk = pdf_file.read(chunk_size)
                            if not chunk:
                                break
                            temp_file.write(chunk)
                    else:
                        temp_file.write(pdf_file.read())
            except Exception as e:
                logger.error(f"Error creating temporary file: {e}")
                raise
            
            # Upload file to OpenAI with progress logging
            logger.info(f"Uploading file to OpenAI (size: {file_size_mb:.2f} MB)...")
            
            # Adjust timeout based on file size for very large files
            # OpenAI API uploads can take a long time for large files
            max_retries = 3
            retry_delay = 5  # seconds
            uploaded_file = None
            
            for attempt in range(max_retries):
                try:
                    with open(temp_file_path, 'rb') as file:
                        # Create a client instance with dynamic timeout for this specific upload
                        # For files over 100MB, use longer timeout
                        upload_timeout = 1800.0 if file_size_mb > 100 else 600.0
                        upload_client = OpenAI(
                            api_key=os.getenv('OPENAI_API_KEY'),
                            timeout=upload_timeout
                        )
                        uploaded_file = upload_client.files.create(
                            file=file,
                            purpose='assistants'
                        )
                    break  # Success, exit retry loop
                except Exception as upload_error:
                    error_str = str(upload_error)
                    # Check if it's a timeout or gateway error
                    is_timeout = any(keyword in error_str.lower() for keyword in [
                        'timeout', 'gateway', '504', 'timed out'
                    ])
                    
                    if is_timeout and attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Upload attempt {attempt + 1} timed out. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Last attempt failed or non-timeout error
                        raise
            
            if not uploaded_file:
                raise Exception("Failed to upload file after multiple attempts")
            
            self.uploaded_file_id = uploaded_file.id
            self.file_name = getattr(pdf_file, 'filename', None) or getattr(pdf_file, 'name', None)
            logger.info(f"File uploaded successfully: {self.uploaded_file_id}")
            
            # Create vector store
            vector_store = client.vector_stores.create(
                name=f"Medical Legal PDF - {datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            self.vector_store_id = vector_store.id
            logger.info(f"Vector store created: {self.vector_store_id}")
            
            # Add file to vector store
            logger.info("Adding file to vector store...")
            client.vector_stores.files.create(
                vector_store_id=self.vector_store_id,
                file_id=self.uploaded_file_id
            )
            
            # Calculate wait time based on file size (allow more time for larger files)
            # Base time: 60 seconds, add 2 seconds per MB for files over 100MB
            base_wait_time = 60
            additional_time = max(0, (file_size_mb - 100) * 2) if file_size_mb > 100 else 0
            max_wait_time = int(base_wait_time + additional_time)
            max_wait_time = min(max_wait_time, 1800)  # Cap at 30 minutes
            
            logger.info(f"Waiting for vector store processing (max {max_wait_time}s)...")
            wait_time = 0
            check_interval = 5  # Check every 5 seconds
            last_status = None
            
            while wait_time < max_wait_time:
                try:
                    vector_store_files = client.vector_stores.files.list(
                        vector_store_id=self.vector_store_id
                    )
                    
                    if vector_store_files.data:
                        current_status = vector_store_files.data[0].status
                        if current_status != last_status:
                            logger.info(f"Vector store file status: {current_status}")
                            last_status = current_status
                        
                        if current_status == 'completed':
                            logger.info("File processing completed")
                            break
                        elif current_status == 'failed':
                            logger.error("Vector store processing failed")
                            raise Exception("Vector store processing failed")
                    else:
                        if last_status != 'processing':
                            logger.info("Vector store processing...")
                            last_status = 'processing'
                    
                    time.sleep(check_interval)
                    wait_time += check_interval
                    
                    # Log progress every 30 seconds
                    if wait_time % 30 == 0:
                        logger.info(f"Still processing... ({wait_time}s / {max_wait_time}s)")
                except Exception as e:
                    logger.error(f"Error checking vector store status: {e}")
                    time.sleep(check_interval)
                    wait_time += check_interval
            
            if wait_time >= max_wait_time:
                logger.warning(f"Vector store processing timed out after {max_wait_time}s")
                # Don't fail immediately - processing might still complete in background
                # But log a warning
                
            # Create assistant with file search capability
            self.assistant_id = self.create_assistant()
            
            if not self.assistant_id:
                logger.error("Failed to create assistant")
                # Clean up vector store and file if assistant creation failed
                try:
                    client.vector_stores.delete(self.vector_store_id)
                    client.files.delete(self.uploaded_file_id)
                except:
                    pass
                return False
            
            # Clean up temporary file immediately after upload to free memory
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    temp_file_path = None
                    logger.info("Temporary file cleaned up")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp file: {e}")
            
            # Force garbage collection after large file operations
            if file_size_mb > 100:
                import gc
                gc.collect()
                logger.info("Garbage collection triggered after large file upload")
            
            return True
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error uploading PDF to OpenAI: {error_str}")
            
            # Provide user-friendly error messages for common issues
            if any(keyword in error_str.lower() for keyword in ['timeout', 'gateway', '504', 'timed out']):
                logger.error("Upload timed out - file may be too large or network connection slow")
                # Don't return False here - let the outer handler provide a better message
                raise Exception(f"Upload timed out. Large files ({file_size_mb:.1f} MB) may take longer to process. Please try again or split the file into smaller parts.")
            
            # Clean up temporary file in case of error
            if 'temp_file_path' in locals() and temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
            return False
    
    def create_assistant(self):
        """Create an assistant with file search capability"""
        try:
            # Ensure vector store exists before creating assistant
            if not self.vector_store_id:
                logger.error("Cannot create assistant: No vector store ID")
                return None
            
            # Verify vector store exists
            try:
                vector_store = client.vector_stores.retrieve(self.vector_store_id)
                logger.info(f"Vector store verified: {vector_store.id}")
            except Exception as e:
                logger.error(f"Vector store verification failed: {str(e)}")
                return None
            
            assistant = client.beta.assistants.create(
                name="Medical Legal Document Analyzer",
                instructions=f"""You are a medical legal document analyzer. Analyze uploaded medical documents with {self.verbosity} responses. 
                
                When extracting information:
                - Be thorough and accurate
                - Use the exact information from the documents
                - For variable extraction prompts only, output ONLY a JSON array of strings
                - For dates, use mm/dd/yyyy format when specified
                - Maintain professional medical/legal terminology
                - Provide ONLY the requested information without any introductory phrases like "Here is the extracted information from the document:" or similar
                - Start your response directly with the actual content
                - For ALL normal questions/answers (i.e., anything other than variable extraction), respond in natural prose. Do NOT return JSON, YAML, code blocks, or tables. Use short paragraphs and simple bullet lists where appropriate.
                - Do NOT wrap answers in triple backticks or any code fences.
                - Do NOT insert inline [source] markers; citations will be attached separately.
                
                Always search through the uploaded documents to find relevant information before responding.""",
                model="gpt-4o",
                tools=[{"type": "file_search"}],
                tool_resources={
                    "file_search": {
                        "vector_store_ids": [self.vector_store_id]
                    }
                }
            )
            logger.info(f"Assistant created successfully: {assistant.id}")
            return assistant.id
        except Exception as e:
            logger.error(f"Error creating assistant: {str(e)}")
            return None

    def _get_file_pages(self, file_id):
        """Download an uploaded file and return its per-page text for citation lookup.
        Uses temporary file to avoid loading entire PDF into memory."""
        temp_file_path = None
        try:
            # Check if we have a cached version (but limit cache size for memory)
            if hasattr(self, "_pages_cache") and file_id in self._pages_cache:
                cached_pages = self._pages_cache[file_id]
                # Only use cache if it's reasonable size (less than 50MB of text)
                total_size = sum(len(str(p)) for p in cached_pages)
                if total_size < 50 * 1024 * 1024:  # 50MB limit
                    return cached_pages
            
            # Download file to temporary disk file instead of memory
            stream = client.files.content(file_id)
            temp_file_path = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf').name
            
            # Write stream to disk in chunks to avoid memory issues
            chunk_size = 8 * 1024 * 1024  # 8MB chunks
            with open(temp_file_path, 'wb') as f:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
            
            # Open PDF from disk file
            doc = fitz.open(temp_file_path)
            pages = []
            
            # Process pages one at a time and only keep text (not full page objects)
            for i in range(doc.page_count):
                page_text = doc[i].get_text()
                pages.append(page_text)
                
                # Don't cache if file is too large (more than 1000 pages or estimated > 100MB)
                if len(pages) > 1000:
                    logger.warning(f"File has {doc.page_count} pages, skipping cache to save memory")
                    doc.close()
                    # Clean up temp file
                    if temp_file_path and os.path.exists(temp_file_path):
                        os.unlink(temp_file_path)
                    return pages  # Return what we have without caching
            
            doc.close()
            
            # Clean up temp file immediately
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                temp_file_path = None
            
            # Only cache if reasonable size
            total_size = sum(len(str(p)) for p in pages)
            if total_size < 50 * 1024 * 1024:  # 50MB limit
                if not hasattr(self, "_pages_cache"):
                    self._pages_cache = {}
                self._pages_cache[file_id] = pages
            else:
                logger.info(f"File too large to cache ({total_size / (1024*1024):.1f}MB), skipping cache")
            
            return pages
            
        except Exception as e:
            logger.error(f"Failed to download/parse file {file_id} for citations: {e}")
            # Clean up temp file on error
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
            
            # Fallback: try the originally uploaded file (same content, different id than vector store file)
            try:
                if getattr(self, 'uploaded_file_id', None) and self.uploaded_file_id != file_id:
                    return self._get_file_pages(self.uploaded_file_id)
            except Exception as e2:
                logger.error(f"Fallback download failed for citations: {e2}")
            return []

    def _find_quote_pages(self, file_id, quote):
        """Return 1-based page numbers where the quoted text appears."""
        if not quote:
            return []
        if not hasattr(self, "_pages_cache"):
            self._pages_cache = {}
        
        # For very large files, don't cache - process on demand
        if file_id not in self._pages_cache:
            # Check if we should skip caching (if file is large)
            try:
                # Get file info to check size
                file_info = client.files.retrieve(file_id)
                file_size_bytes = getattr(file_info, 'bytes', 0)
                if file_size_bytes > 100 * 1024 * 1024:  # 100MB
                    logger.info(f"Large file detected ({file_size_bytes / (1024*1024):.1f}MB), processing without cache")
                    pages = self._get_file_pages(file_id)
                    # Don't cache it, just use it
                    if pages:
                        q = self._strip_inline_markers(quote)
                        qn = re.sub(r"\s+", " ", q).strip()
                        qn_norm = self._normalize_for_match(qn)
                        hits = []
                        for i, txt in enumerate(pages):
                            tn = re.sub(r"\s+", " ", (txt or ""))
                            if qn and qn in tn:
                                hits.append(i + 1)
                                continue
                            tn_norm = self._normalize_for_match(tn)
                            if qn_norm and qn_norm in tn_norm:
                                hits.append(i + 1)
                        return hits
            except Exception:
                pass  # Fall through to normal caching behavior
        
        # Strip inline source markers like [4:5†source] or 【source】 before searching
        q = self._strip_inline_markers(quote)
        if file_id not in self._pages_cache:
            self._pages_cache[file_id] = self._get_file_pages(file_id)
        pages = self._pages_cache[file_id] or []
        # Normalize whitespace for comparison
        qn = re.sub(r"\s+", " ", q).strip()
        qn_norm = self._normalize_for_match(qn)
        hits = []
        for i, txt in enumerate(pages):
            tn = re.sub(r"\s+", " ", (txt or ""))
            if qn and qn in tn:
                hits.append(i + 1)
                continue
            # Fuzzy contains: compare normalized strings
            tn_norm = self._normalize_for_match(tn)
            if qn_norm and qn_norm in tn_norm:
                hits.append(i + 1)
        return hits
    
    def query_with_file_search(self, prompt, max_tokens=1000, max_retries=3, return_citations=False, thread_id=None):
        """Query using OpenAI's file search with robust error handling and optional citations"""
        for attempt in range(max_retries):
            try:
                if not self.assistant_id:
                    return {"text": "Error: Assistant not created", "citations": []} if return_citations else "Error: Assistant not created"
                
                # Add delay between requests to prevent rate limiting
                if attempt > 0:
                    delay = min(2 ** attempt, 10)  # Exponential backoff, max 10 seconds
                    logger.info(f"Retrying query (attempt {attempt + 1}/{max_retries}) after {delay}s delay")
                    time.sleep(delay)
                
                # Use provided thread if available, otherwise create a fresh one
                if thread_id:
                    thread_id_to_use = thread_id
                else:
                    thread_obj = client.beta.threads.create()
                    thread_id_to_use = thread_obj.id
                
                # Add message to thread
                client.beta.threads.messages.create(
                    thread_id=thread_id_to_use,
                    role="user",
                    content=prompt
                )
                
                # Run the assistant
                run = client.beta.threads.runs.create(
                    thread_id=thread_id_to_use,
                    assistant_id=self.assistant_id
                )
                
                # Wait for completion with shorter intervals
                max_wait_time = 60  # Reduced from 120 to 60 seconds
                wait_time = 0
                check_interval = 1  # Check every 1 second instead of 2
                
                while wait_time < max_wait_time:
                    run_status = client.beta.threads.runs.retrieve(
                        thread_id=thread_id_to_use,
                        run_id=run.id
                    )
                    
                    if run_status.status == 'completed':
                        # Get messages
                        messages = client.beta.threads.messages.list(thread_id=thread_id_to_use)

                        # Get the assistant's response
                        for message in messages.data:
                            if message.role == 'assistant':
                                # Extract primary text
                                if not return_citations:
                                    try:
                                        return message.content[0].text.value
                                    except Exception:
                                        return "Error: No response from assistant"

                                # Aggregate text and annotations across all content parts; keep raw text for index extraction
                                text_parts = []
                                ann_list = []
                                try:
                                    for item in (getattr(message, "content", []) or []):
                                        try:
                                            if hasattr(item, "text") and getattr(item.text, "value", None):
                                                text_parts.append(item.text.value)
                                                anns = getattr(item.text, "annotations", []) or []
                                                if anns:
                                                    # Attach the container text alongside each annotation when available
                                                    for a in anns:
                                                        try:
                                                            if not hasattr(a, "_container_text"):
                                                                setattr(a, "_container_text", item.text.value)
                                                        except Exception:
                                                            pass
                                                    ann_list.extend(anns)
                                        except Exception:
                                            continue
                                except Exception:
                                    pass
                                text_val = "\n\n".join(text_parts) if text_parts else None

                                cites = []
                                for ann in ann_list:
                                    try:
                                        # Normalize various annotation shapes
                                        ann_type = getattr(ann, "type", "") or ""
                                        if ann_type and ann_type != "file_citation":
                                            # Only handle file citations
                                            continue
                                        file_citation_obj = getattr(ann, "file_citation", None)
                                        fid = None
                                        quote = None
                                        if file_citation_obj is not None:
                                            fid = getattr(file_citation_obj, "file_id", None)
                                            quote = getattr(file_citation_obj, "quote", None)
                                            # If indices are available, prefer slicing from container text to avoid artifacts
                                            try:
                                                start_idx = getattr(file_citation_obj, "start_index", None)
                                                end_idx = getattr(file_citation_obj, "end_index", None)
                                                container = getattr(ann, "_container_text", None)
                                                if container is None and isinstance(text_parts, list) and text_parts:
                                                    container = text_parts[0]
                                                if isinstance(start_idx, int) and isinstance(end_idx, int) and container:
                                                    sliced = container[start_idx:end_idx]
                                                    if sliced:
                                                        quote = sliced
                                            except Exception:
                                                pass
                                        # Fallbacks
                                        if not fid:
                                            fid = getattr(ann, "file_id", None)
                                        if not quote:
                                            quote = getattr(ann, "quote", None) or getattr(ann, "text", None)
                                        # Final cleanup of quote before lookup
                                        if quote:
                                            quote = self._strip_inline_markers(quote)
                                        pages = self._find_quote_pages(fid, quote) if (fid and quote) else []
                                        cites.append({"file_id": fid, "pages": pages, "quote": quote})
                                    except Exception:
                                        continue

                                # If no citations found, attempt heuristic inference as a fallback
                                if not cites:
                                    inferred = self._infer_citations_from_text(text_val or "")
                                else:
                                    inferred = []
                                return {"text": text_val or "", "citations": (cites or inferred)}

                        # Fallback if no assistant message found
                        return {"text": "Error: No response from assistant", "citations": []} if return_citations else "Error: No response from assistant"
                    
                    elif run_status.status in ['failed', 'cancelled', 'expired']:
                        logger.warning(f"Run failed with status: {run_status.status} (attempt {attempt + 1})")
                        # Log additional error details if available
                        if hasattr(run_status, 'last_error') and run_status.last_error:
                            logger.error(f"Run error details: {run_status.last_error}")
                        if attempt < max_retries - 1:
                            break  # Try again
                        else:
                            # On final attempt, return a fallback response
                            fallback = self.get_fallback_response(prompt)
                            return {"text": fallback, "citations": []} if return_citations else fallback
                    
                    time.sleep(check_interval)
                    wait_time += check_interval
                
                if wait_time >= max_wait_time:
                    logger.warning(f"Query timed out (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        continue  # Try again
                    else:
                        return {"text": "Error: Query timed out after multiple attempts", "citations": []} if return_citations else "Error: Query timed out after multiple attempts"
                
            except Exception as e:
                logger.error(f"Error querying with file search (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    continue  # Try again
                else:
                    err = f"Error processing query after {max_retries} attempts: {str(e)}"
                    return {"text": err, "citations": []} if return_citations else err
        
        return {"text": "Error: All retry attempts failed", "citations": []} if return_citations else "Error: All retry attempts failed"
    
    def _infer_citations_from_text(self, text: str, max_items: int = 3):
        """Infer likely citation pages by keyword overlap when model did not return citations.

        Heuristic: split answer into sentences, extract keywords (words length>=5),
        and find pages that contain at least 3 of those keywords. Produce a short
        snippet from the first matched keyword as the quote.
        """
        try:
            if not text or not getattr(self, 'uploaded_file_id', None):
                return []

            pages = self._get_file_pages(self.uploaded_file_id)
            if not pages:
                return []
            
            # Limit pages processed for very large files to save memory
            max_pages_to_check = 500  # Don't check more than 500 pages
            if len(pages) > max_pages_to_check:
                logger.info(f"File has {len(pages)} pages, limiting citation inference to first {max_pages_to_check} pages")
                pages = pages[:max_pages_to_check]

            # Prepare sentences and keywords
            raw = str(text)
            # Basic sentence split
            sentences = re.split(r"(?<=[.!?])\s+", raw)
            # Build keyword set from top sentences
            keywords = []
            for s in sentences:
                s_clean = re.sub(r"[^A-Za-z0-9\s]", " ", s)
                words = [w.lower() for w in s_clean.split() if len(w) >= 5]
                for w in words:
                    if w not in keywords:
                        keywords.append(w)
                if len(keywords) >= 40:
                    break

            if not keywords:
                return []

            results = []
            for idx, page_text in enumerate(pages):
                if not page_text:
                    continue
                page_lower = page_text.lower()
                hits = [kw for kw in keywords if kw in page_lower]
                if len(hits) >= 3:
                    # Build a small quote snippet around the first hit
                    first = hits[0]
                    pos = page_lower.find(first)
                    if pos != -1:
                        start = max(0, pos - 120)
                        end = min(len(page_text), pos + 120)
                        snippet = page_text[start:end].strip()
                    else:
                        snippet = page_text[:240].strip()
                    results.append({
                        "file_id": self.uploaded_file_id,
                        "pages": [idx + 1],
                        "quote": snippet
                    })
                if len(results) >= max_items:
                    break
            return results
        except Exception as e:
            logger.error(f"Error inferring citations: {e}")
            return []

    def get_fallback_response(self, prompt):
        """Provide a fallback response when assistant runs fail"""
        # Extract key terms from the prompt for a basic response
        prompt_lower = prompt.lower()
        
        if "body parts" in prompt_lower:
            return "Unable to extract body parts information from the document. Please review the PDF manually."
        elif "demographics" in prompt_lower or "claimant" in prompt_lower:
            return "Unable to extract demographic information from the document. Please review the PDF manually."
        elif "history" in prompt_lower:
            return "Unable to extract injury history from the document. Please review the PDF manually."
        elif "medications" in prompt_lower:
            return "Unable to extract medication information from the document. Please review the PDF manually."
        elif "diagnostic" in prompt_lower:
            return "Unable to extract diagnostic information from the document. Please review the PDF manually."
        else:
            return "Unable to process this query due to technical issues. Please review the document manually."
    
    def extract_variables(self, variables_config=None):
        """Extract required variables from the PDF using file search"""
        variables_config = variables_config or {
            "Agreed Upon Body Parts": "list all body parts that both the applicant and defense attorney say are accepted in each of their letters. Please confirm you only look at the exact body parts listed and their names.",
            "Disagreed Upon Body Parts": "List all body parts that one lawyer says is accepted and another lawyer does not. Please confirm you only look at the exact body parts listed and their names.",
            "Previous Injuries": "List all the previous injuries the patient has had, if they have had none then return an empty array. Return as a JSON array of strings."
        }
        
        for var_name, prompt in variables_config.items():
            try:
                response = self.query_with_file_search(prompt, max_tokens=500)                # Try to parse JSON response
                try:
                    # Look for JSON array in the response
                    json_match = re.search(r'\[.*?\]', response, re.DOTALL)
                    if json_match:
                        parsed_response = json.loads(json_match.group())
                        if isinstance(parsed_response, list):
                            self.variables[var_name] = parsed_response
                        else:
                            self.variables[var_name] = [item.strip() for item in response.split(',') if item.strip()]
                    else:
                        # Fallback: parse comma-separated values
                        self.variables[var_name] = [item.strip() for item in response.split(',') if item.strip()]
                except (json.JSONDecodeError, AttributeError):
                    # Fallback: parse comma-separated values
                    self.variables[var_name] = [item.strip() for item in response.split(',') if item.strip()]

                # Add delay between variable extractions
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error extracting variable {var_name}: {str(e)}")
                self.variables[var_name] = []
        
        # Combine for Applicant Attorney Alleged Body Parts
        self.variables["Applicant Attorney Alleged Body Parts"] = (
            self.variables.get("Agreed Upon Body Parts", []) + 
            self.variables.get("Disagreed Upon Body Parts", [])
        )
        
        return self.variables
    
    def process_questions(self, questions_config=None):
        """Process all questions according to the specification using file search"""
        logger.info("Starting question processing with improved error handling")
        total_questions = 0
        processed_questions = 0
        
        questions_config = questions_config or {
            "1. Demographics": {
                "a": "Look at the defense attorney, applicant attorney letter and insurance company and itemize all the names and addresses of them.",
                "b": """Look throughout the document and fill in the following, note that most information but sometimes not all can be found in notes, usually applicant or defense attorney letters:
                1. Claimant Name: (Last, First)
                2. Claimant Date of Birth: (mm/dd/yyyy)
                3. Claimant Employer: 
                4. Claimant Occupation:
                5. Claimant Date of Injury: (mm/dd/yyyy)
                6. Claim number:
                7. WCAB Number: 
                8. Date of Exam: (Leave this empty)"""
            },
            "2. History of Injury (Patients Perspective)": {
                "a": "Review the patients entire history of injury as described from the patients perspective and summarize it in a single paragraph."
            },
            "3. History of Injury (Physicians Perspective)": {
                "a": "Review the patients entire history of injury as described from the physicans notes and summarize it in a single paragraph"
            },
            "4. Chief Complaints": {
                "a": {"template": "Describe the patients chief complaints for all the {body_part}", "variable": "Agreed Upon Body Parts"},
                "b": {"template": "Describe the patients chief complaints for all the {body_part}", "variable": "Disagreed Upon Body Parts"}
            },
            "5. Claimants Job": {
                "a": "Describe the job description of the claimants job and describe the specific job duties of the claimants job"
            },
            "6. Work Status": {
                "a": "Find the most recent work status and any work restrictions the claimant has",
                "b": "Has the patient been taken off work? (If true write \"Patient is still working\" if false write Patient stopped working on (date) + write a 2 sentence explanation)"
            },
            "7. Previous Injuries": {
                "a": """Has the patient described any previous injuries
                If no then write "Patient has has to previous injuries" 
                If yes then for each of the previous injuries reiterate how the patient described the injuries in a few sentences."""
            },
            "8. Medical History": {
                "a": "Write a list of the entire non surgical medical history of the patient if applicable, if not, write \"No past medical history\""
            },
            "9. Surgical History": {
                "a": "Write a list of the entire surgical history of the patient if applicable, if not, write \"No past surgical history\""
            },
            "10. Allergies": {
                "a": "Write a list of all the patients allergies if applicable, if not, write \"Patient has no provided allergies\""
            },
            "11. Current Medications": {
                "a": "Write a list of all the medications the claimant is currently taking"
            },
            "12. Social History": {
                "a": "Write a list of any alcohol recreational drug, recreational tabaco, or vape use the patient has had, as well as when they did it according to the medical record."
            },
            "13. Family history of illness": {
                "a": "Write a list of any past medical or surgical history of family members"
            },
            "16. Diagnostic Reports": {
                "a": "Summarize each and every MRI with the diagnostic results of the MRI, in 5 or less sentences in chronological order. If there are no studies/results output \"none of these studies were completed\" with a brief explanation",
                "b": "Summarize each and every CT or CAT scan with the diagnostic results of the CT or CAT scan, in 5 or less sentences in chronological order.",
                "c": "Summarize each and every X-Rays with the diagnostic results of the X-Rays, in 5 or less sentences in chronological order.",
                "d": "Summarize each and every Ultra Sound with the diagnostic results of the Ultra Sound, in 5 or less sentences in chronological order.",
                "e": "Summarize each and every electro diagnostics (also including EMG, NCV, or NCS) with the diagnostic results of the electro diagnostics (also including EMG, NCV, or NCS), in 5 or less sentences in chronological order."
            },
            "17. Doctors Notes": {
                "a": "Summarize every individual dated note in about 7 sentences each, with the date first in chronological order."
            },
            "20. Diagnostic impressions": {
                "a": {"template": "Look through all the medical records and identify the diagnostic impressions for {body_part}", "variable": "Applicant Attorney Alleged Body Parts"}
            },
            "21. Causation": {
                "a": "Evaluate how and why this patients injury would be related to a specific injury at work",
                "b": "Evaluate how and why this patients injury is secondary to cumulative trauma at work"
            },
            "22. Impairment": {
                "a": {"template": "For {body_part} go to the AMA 5th addition guidelines, find the appropriate impairment rating, and give a detailed description on how and why it has that impairment rating.", "variable": "Applicant Attorney Alleged Body Parts"}
            },
            "23. Periods Of Total Disability": {
                "a": {"template": "For {body_part} explain how much time the average American would have to be completely off of work before they are transitioned to light duty.", "variable": "Applicant Attorney Alleged Body Parts"}
            },
            "24. Future Medical Care": {
                "a": {"template": "For {body_part} define what future medical care would be needed according to the MTUS and ODG guidelines that would help cure or relieve current symptoms or future exacerbations.", "variable": "Applicant Attorney Alleged Body Parts"}
            }
        }
        
        # Count total questions for progress tracking
        for section, questions in questions_config.items():
            for question_id, question_data in questions.items():
                if isinstance(question_data, str):
                    total_questions += 1
                elif isinstance(question_data, dict) and "template" in question_data:
                    variable_name = question_data["variable"]
                    variable_values = self.variables.get(variable_name, [])
                    total_questions += len(variable_values)
        
        logger.info(f"Processing {total_questions} total questions")
        
        results = {}
        
        for section, questions in questions_config.items():
            logger.info(f"Processing section: {section}")
            results[section] = {}
            
            for question_id, question_data in questions.items():
                if isinstance(question_data, str):
                    # Simple question
                    processed_questions += 1
                    logger.info(f"Processing question {processed_questions}/{total_questions}: {section} - {question_id}")
                    results[section][question_id] = self.query_with_file_search(question_data, return_citations=True)
                    # Add small delay between questions to prevent rate limiting
                    time.sleep(0.5)
                elif isinstance(question_data, dict) and "template" in question_data:
                    # Variable-based question
                    template = question_data["template"]
                    variable_name = question_data["variable"]
                    variable_values = self.variables.get(variable_name, [])
                    
                    results[section][question_id] = {}
                    for i, value in enumerate(variable_values):
                        processed_questions += 1
                        logger.info(f"Processing question {processed_questions}/{total_questions}: {section} - {question_id} for {value}")
                        prompt = template.replace("{body_part}", value)
                        results[section][question_id][value] = self.query_with_file_search(prompt, return_citations=True)
                        # Add delay between variable-based questions
                        if i < len(variable_values) - 1:  # Don't delay after the last item
                            time.sleep(0.5)
        
        logger.info(f"Completed processing {processed_questions} questions")
        return results
    
    def generate_pdf_report(self, results):
        """Generate PDF report from results"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        story.append(Paragraph("Medical Legal Report", title_style))
        story.append(Spacer(1, 20))
        
        # Add timestamp
        timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        story.append(Paragraph(f"Generated on: {timestamp}", styles['Normal']))
        story.append(Spacer(1, 30))
        
        # Add note about file search
        story.append(Paragraph("Generated using OpenAI File Search with Vector Stores", styles['Italic']))
        story.append(Spacer(1, 30))
        
        # Helpers
        def extract_section_number(name: str) -> int:
            match = re.match(r"^(\d+)", str(name))
            return int(match.group(1)) if match else 10**9

        def format_text(text: str) -> str:
            if text is None:
                return ""
            # Escape HTML then convert newlines to <br/>
            return escape(str(text)).replace("\n", "<br/>")

        # Process results in natural numeric order by leading section number
        for section, questions in sorted(results.items(), key=lambda kv: (extract_section_number(kv[0]), str(kv[0]))):
            # Section header
            story.append(Paragraph(section, styles['Heading2']))
            story.append(Spacer(1, 12))
            
            for question_id, answer in questions.items():
                # Question header
                story.append(Paragraph(f"{question_id}.", styles['Heading3']))
                
                if isinstance(answer, str):
                    # Simple answer
                    story.append(Paragraph(format_text(answer), styles['Normal']))
                elif isinstance(answer, dict) and 'text' in answer:
                    # Answer with citations
                    story.append(Paragraph(format_text(answer['text']), styles['Normal']))
                    if answer.get('citations'):
                        story.append(Paragraph("<b>Sources:</b>", styles['Normal']))
                        for i, c in enumerate(answer['citations'], 1):
                            pages = ", ".join(str(p) for p in (c.get('pages') or [])) or "n/a"
                            quote = (c.get('quote') or '').strip()
                            story.append(Paragraph(f"[{i}] Page {pages}: {escape(quote)}", styles['Italic']))
                        story.append(Spacer(1, 6))
                elif isinstance(answer, dict):
                    # Variable-based answers
                    for body_part, body_part_answer in answer.items():
                        story.append(Paragraph(f"<b>{body_part}:</b>", styles['Normal']))
                        if isinstance(body_part_answer, dict) and 'text' in body_part_answer:
                            story.append(Paragraph(format_text(body_part_answer['text']), styles['Normal']))
                            if body_part_answer.get('citations'):
                                story.append(Paragraph("<b>Sources:</b>", styles['Normal']))
                                for i, c in enumerate(body_part_answer['citations'], 1):
                                    pages = ", ".join(str(p) for p in (c.get('pages') or [])) or "n/a"
                                    quote = (c.get('quote') or '').strip()
                                    story.append(Paragraph(f"[{i}] Page {pages}: {escape(quote)}", styles['Italic']))
                        else:
                            story.append(Paragraph(format_text(str(body_part_answer)), styles['Normal']))
                        story.append(Spacer(1, 6))
                
                story.append(Spacer(1, 12))
            
            story.append(Spacer(1, 20))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def cleanup_resources(self):
        """Clean up OpenAI resources"""
        try:
            if self.vector_store_id:
                client.vector_stores.delete(self.vector_store_id)
                logger.info(f"Vector store deleted: {self.vector_store_id}")
            
            if self.assistant_id:
                client.beta.assistants.delete(self.assistant_id)
                logger.info(f"Assistant deleted: {self.assistant_id}")
                
            if self.uploaded_file_id:
                client.files.delete(self.uploaded_file_id)
                logger.info(f"File deleted: {self.uploaded_file_id}")
                
        except Exception as e:
            logger.error(f"Error cleaning up resources: {str(e)}")
        finally:
            # Reset local state regardless of cleanup outcome
            self.vector_store_id = None
            self.assistant_id = None
            self.uploaded_file_id = None
            self.file_name = None
            self.variables = {}
            # Clear pages cache to free memory
            self._pages_cache = {}
            
            # Force garbage collection to free memory
            import gc
            gc.collect()

# Note: Global processor removed - now using session-based processors

@app.route('/')
def index():
    # Embed prompts.json inline to avoid fetch issues in some environments
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompts_path = os.path.join(base_dir, 'prompts.json')
        with open(prompts_path, 'r') as f:
            prompts_data = json.load(f)
    except Exception:
        prompts_data = {}
    # Allow frontend to call an external backend (e.g., Render) when set
    api_base_url = os.getenv('API_BASE_URL', '')
    return render_template('index.html', prompts_json=json.dumps(prompts_data), api_base_url=api_base_url)

@app.route('/upload', methods=['POST'])
def upload_pdf():
    try:
        if 'pdf' not in request.files:
            return jsonify({'error': 'No PDF file provided'}), 400
        
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Check file size and log for large files
        pdf_file.seek(0, 2)  # Seek to end
        file_size = pdf_file.tell()
        pdf_file.seek(0)  # Reset to beginning
        file_size_mb = file_size / (1024 * 1024)

        logger.info(f"Receiving PDF upload: {pdf_file.filename} ({file_size_mb:.2f} MB)")

        # Warn if file is very large
        if file_size_mb > 500:
            logger.warning(f"Large file upload detected: {file_size_mb:.2f} MB - may take several minutes to process")

        # Get user-specific processor and ensure user history dir exists
        processor = get_user_processor()
        user_dir = _get_user_upload_dir()

        # Set verbosity if provided
        verbosity = request.form.get('verbosity', 'detailed')
        processor.verbosity = verbosity

        # Persist a copy into user's history before processing
        safe_name = secure_filename(pdf_file.filename or 'document.pdf') or 'document.pdf'
        history_id = uuid.uuid4().hex[:12]
        saved_basename = f"{history_id}__{safe_name}"
        saved_path = os.path.join(user_dir, saved_basename)
        try:
            with open(saved_path, 'wb') as out_f:
                pdf_file.stream.seek(0)
                chunk = pdf_file.stream.read(8 * 1024 * 1024)
                while chunk:
                    out_f.write(chunk)
                    chunk = pdf_file.stream.read(8 * 1024 * 1024)
        except Exception as e:
            logger.error(f"Failed to persist upload into history: {e}")
            saved_path = None

        # Upload PDF to OpenAI and create vector store (with local fallback inside)
        logger.info(f"Starting PDF extraction and upload to OpenAI for user {session.get('user_id', 'unknown')}")
        try:
            if saved_path and os.path.exists(saved_path):
                file_size = os.path.getsize(saved_path)
                with open(saved_path, 'rb') as persisted_file:
                    success = processor.extract_pdf_text(persisted_file, file_size_bytes=file_size)
            else:
                pdf_file.stream.seek(0)
                success = processor.extract_pdf_text(pdf_file, file_size_bytes=file_size)
        except Exception:
            pdf_file.stream.seek(0)
            success = processor.extract_pdf_text(pdf_file, file_size_bytes=file_size)
        if not success:
            error_msg = 'Failed to handle PDF upload'
            # Check if it's a timeout issue
            if file_size_mb > 500:
                error_msg += f'. Large files ({file_size_mb:.1f} MB) may take longer to process. Please try again or contact support if the issue persists.'
            return jsonify({'error': error_msg}), 400

        logger.info(f"PDF upload completed successfully for {pdf_file.filename}")
        # Ensure a friendly file name is tracked server-side
        try:
            processor.file_name = pdf_file.filename
        except Exception:
            pass
        return jsonify({
            'message': 'PDF ready (OpenAI or local OCR mode)',
            'vector_store_id': processor.vector_store_id,
            'assistant_id': processor.assistant_id,
            'local_mode': bool(getattr(processor, 'local_pdf_path', None)),
            'file_size_mb': round(file_size_mb, 2),
            'user_id': session.get('user_id', 'unknown'),
            'file_name': pdf_file.filename,
            'history_id': history_id
        })

    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        error_message = str(e)
        
        # Check if it's a file size error
        if 'MAX_CONTENT_LENGTH' in error_message or 'too large' in error_message.lower():
            return jsonify({'error': f'File too large. Maximum size is {app.config["MAX_CONTENT_LENGTH"] / (1024*1024*1024):.1f}GB'}), 413
        
        # Check if it's a timeout error
        if 'timeout' in error_message.lower() or 'timed out' in error_message.lower():
            return jsonify({'error': 'Upload timed out. Large files may take longer to process. Please try again.'}), 504
        
        # Check if it's a connection error
        if 'connection' in error_message.lower() or 'network' in error_message.lower():
            return jsonify({'error': 'Network error during upload. Please check your connection and try again.'}), 503
        
        return jsonify({'error': f'Upload failed: {error_message}'}), 500

@app.route('/api/files/history', methods=['GET'])
def list_file_history():
    """List previously uploaded files for the current user (server-side history)."""
    try:
        user_dir = _get_user_upload_dir()
        items = []
        if os.path.exists(user_dir):
            for name in os.listdir(user_dir):
                if not name.lower().endswith('.pdf'):
                    continue
                if '__' not in name:
                    continue
                fid, original = name.split('__', 1)
                path = os.path.join(user_dir, name)
                try:
                    st = os.stat(path)
                    items.append({
                        'id': fid,
                        'name': original,
                        'size_mb': round(st.st_size / (1024 * 1024), 2),
                        'created': datetime.fromtimestamp(st.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                    })
                except Exception:
                    continue
        items.sort(key=lambda x: x.get('created', ''), reverse=True)
        return jsonify({'files': items})
    except Exception as e:
        logger.error(f"History list error: {e}")
        return jsonify({'error': 'Failed to list history'}), 500

@app.route('/api/files/use', methods=['POST'])
def use_file_from_history():
    """Load a file from the user's server-side history and set it as the active document."""
    try:
        data = request.get_json(silent=True) or {}
        fid = str(data.get('id') or '').strip()
        if not fid:
            return jsonify({'error': 'Missing id'}), 400

        user_dir = _get_user_upload_dir()
        target_path = None
        original_name = None
        for name in os.listdir(user_dir):
            if name.startswith(fid + '__') and name.lower().endswith('.pdf'):
                target_path = os.path.join(user_dir, name)
                original_name = name.split('__', 1)[1]
                break
        if not target_path or not os.path.exists(target_path):
            return jsonify({'error': 'File not found'}), 404

        file_size_mb = round(os.stat(target_path).st_size / (1024 * 1024), 2)

        # Reset any previous processor resources, then (re)load this file
        user_id = session.get('user_id')
        if user_id:
            try:
                cleanup_user_processor(user_id)
            except Exception:
                pass
        processor = get_user_processor()

        logger.info(f"Loading history file for user {session.get('user_id', 'unknown')}: {original_name}")
        file_size = os.path.getsize(target_path)
        with open(target_path, 'rb') as f:
            success = processor.extract_pdf_text(f, file_size_bytes=file_size)
        if not success:
            return jsonify({'error': 'Failed to load file from history'}), 400

        # Prefer displaying the original filename to the client
        processor.file_name = original_name

        return jsonify({
            'message': 'PDF loaded from history',
            'vector_store_id': processor.vector_store_id,
            'assistant_id': processor.assistant_id,
            'local_mode': bool(getattr(processor, 'local_pdf_path', None)),
            'file_size_mb': file_size_mb,
            'user_id': session.get('user_id', 'unknown'),
            'file_name': original_name,
            'history_id': fid
        })
    except Exception as e:
        logger.error(f"Use history error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/process', methods=['POST'])
def process_pdf():
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400
        
        # Extract variables
        variables = processor.extract_variables()
        
        # Process questions
        results = processor.process_questions()
        
        return jsonify({
            'variables': variables,
            'results': results,
            'user_id': session.get('user_id', 'unknown')
        })
    
    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/generate-report', methods=['POST'])
def generate_report():
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        # Allow direct PDF generation from provided results to support custom prompts
        req_json = None
        try:
            req_json = request.get_json(silent=True) or {}
        except Exception:
            req_json = {}
        provided_results = req_json.get('results') if isinstance(req_json, dict) else None
        
        if provided_results is None:
            if not processor.vector_store_id:
                return jsonify({'error': 'No PDF uploaded'}), 400
            # Extract variables if not already done
            if not processor.variables:
                processor.extract_variables()
            # Process questions
            results = processor.process_questions()
        else:
            results = provided_results
        
        # Generate PDF report
        pdf_buffer = processor.generate_pdf_report(results)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_id = session.get('user_id', 'unknown')[:8]  # Use first 8 chars of user ID
        filename = f'medical_report_{user_id}_{timestamp}.pdf'
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
    
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/default', methods=['GET'])
def get_default_prompts():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompts_path = os.path.join(base_dir, 'prompts.json')
        with open(prompts_path, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error reading prompts.json: {e}")
        return jsonify({'error': 'Failed to load default prompts'}), 500

@app.route('/prompts.json', methods=['GET'])
def serve_prompts_json():
    """Serve prompts.json for local development convenience."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompts_path = os.path.join(base_dir, 'prompts.json')
        return send_file(prompts_path, mimetype='application/json')
    except Exception as e:
        logger.error(f"Error serving prompts.json: {e}")
        return jsonify({'error': 'prompts.json not found'}), 404

@app.route('/api/variables', methods=['GET'])
def get_variables_pallete():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        prompts_path = os.path.join(base_dir, 'prompts.json')
        placeholders = []
        variables = []
        try:
            with open(prompts_path, 'r') as f:
                data = json.load(f)
                placeholders = data.get('placeholders', [])
                variables = [
                    {"name": k, "description": v}
                    for k, v in (data.get('variablesPrompts', {}) or {}).items()
                ]
        except Exception:
            pass
        return jsonify({
            'placeholders': placeholders,
            'variables': variables
        })
    except Exception as e:
        logger.error(f"Error building variables palette: {e}")
        return jsonify({'error': 'Failed to load variables'}), 500

@app.route('/api/status', methods=['GET'])
def api_status():
    """Report current server-side processing state so the UI can reuse uploaded PDFs."""
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        has_pdf = bool(getattr(processor, 'vector_store_id', None))
        return jsonify({
            'has_pdf': has_pdf,
            'vector_store_id': getattr(processor, 'vector_store_id', None),
            'assistant_id': getattr(processor, 'assistant_id', None),
            'uploaded_file_id': getattr(processor, 'uploaded_file_id', None),
            'file_name': getattr(processor, 'file_name', None),
            'verbosity': getattr(processor, 'verbosity', None),
            'chat_thread_id': getattr(processor, 'chat_thread_id', None),
            'user_id': session.get('user_id', 'unknown'),
            'active_users': len(user_processors)
        })
    except Exception as e:
        logger.error(f"Status error: {str(e)}")
        return jsonify({'error': 'Failed to get status'}), 500

@app.route('/api/run', methods=['POST'])
def run_with_custom_prompts():
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON body'}), 400

        prompts = data.get('prompts')
        if not prompts or not isinstance(prompts, dict):
            return jsonify({'error': 'Missing prompts'}), 400

        variables_prompts = prompts.get('variablesPrompts') or {}
        questions = prompts.get('questions') or {}

        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400

        # Append fixed, non-editable output format to variable prompts at runtime
        fixed_suffix = " Return ONLY a JSON array of strings. No explanations."
        variables_prompts_with_format = {
            key: (str(val or '').strip() + fixed_suffix)
            for key, val in variables_prompts.items()
        }

        # Extract variables and process questions based on provided prompts
        variables = processor.extract_variables(variables_prompts_with_format)
        results = processor.process_questions(questions)

        return jsonify({
            'variables': variables,
            'results': results,
            'echo': {
                'prompts': prompts
            },
            'user_id': session.get('user_id', 'unknown')
        })
    except Exception as e:
        logger.error(f"Run with custom prompts error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/run-one', methods=['POST'])
def run_single_prompt():
    """Run a single prompt (simple or templated) and return its output.

    Request JSON formats:
    - { "type": "simple", "prompt": "..." }
    - { "type": "templated", "template": "...{body_part}...", "variableName": "Agreed Upon Body Parts", "variablesPrompts": { ... } }
    """
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON body'}), 400

        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400

        run_type = str(data.get('type') or '').strip().lower()
        if run_type not in ('simple', 'templated'):
            return jsonify({'error': 'Invalid type. Expected "simple" or "templated"'}), 400

        if run_type == 'simple':
            prompt = (data.get('prompt') or '').strip()
            if not prompt:
                return jsonify({'error': 'Missing prompt'}), 400
            result = processor.query_with_file_search(prompt, return_citations=True)
            return jsonify({
                'kind': 'simple', 
                'result': result,
                'user_id': session.get('user_id', 'unknown')
            })

        # Templated
        template = (data.get('template') or '').strip()
        variable_name = (data.get('variableName') or '').strip()
        if not template or not variable_name:
            return jsonify({'error': 'Missing template or variableName'}), 400

        # Ensure variables are available; extract if missing using provided variablesPrompts
        if not processor.variables:
            variables_prompts = (data.get('variablesPrompts') or {})
            fixed_suffix = " Return ONLY a JSON array of strings. No explanations."
            variables_prompts_with_format = {
                key: (str(val or '').strip() + fixed_suffix)
                for key, val in (variables_prompts.items() if isinstance(variables_prompts, dict) else [])
            }
            try:
                processor.extract_variables(variables_prompts_with_format)
            except Exception:
                # continue even if extraction fails; we'll default to empty
                pass

        values = processor.variables.get(variable_name, []) or []
        # If this is the combined key that depends on other vars and it's still empty, try to synthesize it
        if not values and variable_name == "Applicant Attorney Alleged Body Parts":
            combined = (processor.variables.get("Agreed Upon Body Parts", []) or []) + (processor.variables.get("Disagreed Upon Body Parts", []) or [])
            values = combined

        results_by_value = {}
        if values:
            for i, value in enumerate(values):
                try:
                    prompt = template.replace('{body_part}', str(value))
                    results_by_value[value] = processor.query_with_file_search(prompt, return_citations=True)
                    if i < len(values) - 1:
                        time.sleep(0.3)
                except Exception as e:
                    results_by_value[value] = {'text': f'Error: {str(e)}', 'citations': []}
        else:
            # If no values, run once with a placeholder to at least return something useful
            placeholder_prompt = template.replace('{body_part}', '(no variable values)')
            results_by_value['(no values)'] = processor.query_with_file_search(placeholder_prompt, return_citations=True)

        return jsonify({
            'kind': 'templated', 
            'resultsByValue': results_by_value, 
            'variableName': variable_name,
            'user_id': session.get('user_id', 'unknown')
        })
    except Exception as e:
        logger.error(f"Run single prompt error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat_with_context():
    """Send a chat message and maintain conversation context via a reusable thread.

    Request JSON:
    {
      "message": "...",                # required
      "reset": false                    # optional: if true, start a new thread
    }

    Response JSON:
    {
      "threadId": "...",
      "answer": { "text": "...", "citations": [...] }
    }
    """
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON body'}), 400

        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400

        user_message = (data.get('message') or '').strip()
        if not user_message:
            return jsonify({'error': 'Missing message'}), 400

        # Optionally reset the chat thread
        if bool(data.get('reset')):
            processor.chat_thread_id = None

        # Ensure we have a thread id to keep context
        if not processor.chat_thread_id:
            thread_obj = client.beta.threads.create()
            processor.chat_thread_id = thread_obj.id

        result = processor.query_with_file_search(
            user_message,
            return_citations=True,
            thread_id=processor.chat_thread_id
        )

        return jsonify({
            'threadId': processor.chat_thread_id,
            'answer': result,
            'user_id': session.get('user_id', 'unknown')
        })
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/set-verbosity', methods=['POST'])
def set_verbosity():
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        data = request.get_json()
        verbosity = data.get('verbosity', 'detailed')
        
        if verbosity not in ['brief', 'detailed', 'comprehensive']:
            return jsonify({'error': 'Invalid verbosity level'}), 400
        
        processor.verbosity = verbosity
        
        # Update assistant if it exists
        if processor.assistant_id:
            client.beta.assistants.update(
                assistant_id=processor.assistant_id,
                instructions=f"""You are a medical legal document analyzer. Analyze uploaded medical documents with {verbosity} responses. 
                
                When extracting information:
                - Be thorough and accurate
                - Use the exact information from the documents
                - For variable extraction prompts only, output ONLY a JSON array of strings
                - For dates, use mm/dd/yyyy format when specified
                - Maintain professional medical/legal terminology
                - Provide ONLY the requested information without any introductory phrases like "Here is the extracted information from the document:" or similar
                - Start your response directly with the actual content
                - For ALL normal questions/answers (i.e., anything other than variable extraction), respond in natural prose. Do NOT return JSON, YAML, code blocks, or tables. Use short paragraphs and simple bullet lists where appropriate.
                - Do NOT wrap answers in triple backticks or any code fences.
                - Do NOT insert inline [source] markers; citations will be attached separately.
                
                Always search through the uploaded documents to find relevant information before responding."""
            )
        
        return jsonify({
            'message': f'Verbosity set to {verbosity}',
            'user_id': session.get('user_id', 'unknown')
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Clean up OpenAI resources for the current user"""
    try:
        user_id = session.get('user_id')
        if user_id:
            cleanup_user_processor(user_id)
            return jsonify({
                'message': 'Resources cleaned up successfully',
                'user_id': user_id
            })
        else:
            return jsonify({'message': 'No active session to clean up'})
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-query', methods=['POST'])
def test_query():
    """Test a simple query to diagnose assistant issues"""
    try:
        # Get user-specific processor
        processor = get_user_processor()
        
        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400
        
        if not processor.assistant_id:
            return jsonify({'error': 'No assistant created'}), 400
        
        # Test with a very simple query
        test_prompt = "What is the patient's name mentioned in this document?"
        
        logger.info(f"Testing simple query: {test_prompt}")
        response = processor.query_with_file_search(test_prompt, max_tokens=200, max_retries=1)
        
        return jsonify({
            'query': test_prompt,
            'response': response,
            'vector_store_id': processor.vector_store_id,
            'assistant_id': processor.assistant_id,
            'user_id': session.get('user_id', 'unknown')
        })
    
    except Exception as e:
        logger.error(f"Test query error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/reports', methods=['GET'])
def list_reports():
    """List all generated PDF reports"""
    try:
        reports_dir = os.path.join(os.getcwd(), 'reports')
        
        if not os.path.exists(reports_dir):
            return jsonify({'reports': [], 'message': 'No reports directory found'})
        
        reports = []
        for filename in os.listdir(reports_dir):
            if filename.endswith('.pdf'):
                filepath = os.path.join(reports_dir, filename)
                file_stats = os.stat(filepath)
                reports.append({
                    'filename': filename,
                    'filepath': filepath,
                    'size': file_stats.st_size,
                    'created': datetime.fromtimestamp(file_stats.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                })
        
        # Sort by creation time (newest first)
        reports.sort(key=lambda x: x['created'], reverse=True)
        
        return jsonify({'reports': reports})
    
    except Exception as e:
        logger.error(f"List reports error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/session-info', methods=['GET'])
def session_info():
    """Get information about the current user session"""
    try:
        user_id = session.get('user_id')
        processor = get_user_processor() if user_id else None
        
        return jsonify({
            'user_id': user_id,
            'has_pdf': bool(processor and processor.vector_store_id),
            'active_users': len(user_processors),
            'session_active': bool(user_id),
            'file_name': getattr(processor, 'file_name', None) if processor else None,
            'verbosity': getattr(processor, 'verbosity', None) if processor else None
        })
    except Exception as e:
        logger.error(f"Session info error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup-all', methods=['POST'])
def cleanup_all_users():
    """Clean up resources for all users (admin function)"""
    try:
        cleaned_users = []
        for user_id in list(user_processors.keys()):
            cleanup_user_processor(user_id)
            cleaned_users.append(user_id)
        
        return jsonify({
            'message': f'Cleaned up {len(cleaned_users)} user sessions',
            'cleaned_users': cleaned_users
        })
    except Exception as e:
        logger.error(f"Cleanup all error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=8080)