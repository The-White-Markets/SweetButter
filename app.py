import os
import json
import logging
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import re
from datetime import datetime
import tempfile
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

class PDFProcessor:
    def __init__(self):
        self.verbosity = "detailed"  # Can be "brief", "detailed", or "comprehensive"
        self.vector_store_id = None
        self.assistant_id = None
        self.uploaded_file_id = None
        self.variables = {}
        
    def upload_pdf_to_openai(self, pdf_file):
        """Upload PDF to OpenAI and create vector store"""
        try:
            # Reset file pointer to beginning
            pdf_file.seek(0)
            
            # Create a temporary file to save the uploaded PDF
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(pdf_file.read())
                temp_file_path = temp_file.name
            
            # Upload file to OpenAI
            with open(temp_file_path, 'rb') as file:
                uploaded_file = client.files.create(
                    file=file,
                    purpose='assistants'
                )
            
            self.uploaded_file_id = uploaded_file.id
            logger.info(f"File uploaded successfully: {self.uploaded_file_id}")
            
            # Create vector store
            vector_store = client.vector_stores.create(
                name=f"Medical Legal PDF - {datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            self.vector_store_id = vector_store.id
            logger.info(f"Vector store created: {self.vector_store_id}")
            
            # Add file to vector store
            client.vector_stores.files.create(
                vector_store_id=self.vector_store_id,
                file_id=self.uploaded_file_id
            )
            
            # Wait for file to be processed
            max_wait_time = 60  # Maximum wait time in seconds
            wait_time = 0
            while wait_time < max_wait_time:
                vector_store_files = client.vector_stores.files.list(
                    vector_store_id=self.vector_store_id
                )
                
                if vector_store_files.data and vector_store_files.data[0].status == 'completed':
                    logger.info("File processing completed")
                    break
                
                time.sleep(2)
                wait_time += 2
                
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
            
            # Clean up temporary file
            os.unlink(temp_file_path)
            
            return True
            
        except Exception as e:
            logger.error(f"Error uploading PDF to OpenAI: {str(e)}")
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
                - For lists, format as JSON arrays when requested
                - For dates, use mm/dd/yyyy format when specified
                - Maintain professional medical/legal terminology
                
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
    
    def query_with_file_search(self, prompt, max_tokens=1000, max_retries=3):
        """Query using OpenAI's file search with robust error handling and retries"""
        for attempt in range(max_retries):
            try:
                if not self.assistant_id:
                    return "Error: Assistant not created"
                
                # Add delay between requests to prevent rate limiting
                if attempt > 0:
                    delay = min(2 ** attempt, 10)  # Exponential backoff, max 10 seconds
                    logger.info(f"Retrying query (attempt {attempt + 1}/{max_retries}) after {delay}s delay")
                    time.sleep(delay)
                
                # Create a thread
                thread = client.beta.threads.create()
                
                # Add message to thread
                client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=prompt
                )
                
                # Run the assistant
                run = client.beta.threads.runs.create(
                    thread_id=thread.id,
                    assistant_id=self.assistant_id
                )
                
                # Wait for completion with shorter intervals
                max_wait_time = 60  # Reduced from 120 to 60 seconds
                wait_time = 0
                check_interval = 1  # Check every 1 second instead of 2
                
                while wait_time < max_wait_time:
                    run_status = client.beta.threads.runs.retrieve(
                        thread_id=thread.id,
                        run_id=run.id
                    )
                    
                    if run_status.status == 'completed':
                        # Get messages
                        messages = client.beta.threads.messages.list(thread_id=thread.id)
                        
                        # Get the assistant's response
                        for message in messages.data:
                            if message.role == 'assistant':
                                return message.content[0].text.value
                        
                        return "Error: No response from assistant"
                    
                    elif run_status.status in ['failed', 'cancelled', 'expired']:
                        logger.warning(f"Run failed with status: {run_status.status} (attempt {attempt + 1})")
                        # Log additional error details if available
                        if hasattr(run_status, 'last_error') and run_status.last_error:
                            logger.error(f"Run error details: {run_status.last_error}")
                        if attempt < max_retries - 1:
                            break  # Try again
                        else:
                            # On final attempt, return a fallback response
                            return self.get_fallback_response(prompt)
                    
                    time.sleep(check_interval)
                    wait_time += check_interval
                
                if wait_time >= max_wait_time:
                    logger.warning(f"Query timed out (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        continue  # Try again
                    else:
                        return "Error: Query timed out after multiple attempts"
                
            except Exception as e:
                logger.error(f"Error querying with file search (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    continue  # Try again
                else:
                    return f"Error processing query after {max_retries} attempts: {str(e)}"
        
        return "Error: All retry attempts failed"
    
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
    
    def extract_variables(self):
        """Extract required variables from the PDF using file search"""
        variables_config = {
            "Agreed Upon Body Parts": "List all body parts that both the applicant and defense attorney say are accepted in each of their letters. Return as a JSON array of strings.",
            "Disagreed Upon Body Parts": "List all body parts that one lawyer says is accepted and another lawyer does not. Return as a JSON array of strings.",
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
    
    def process_questions(self):
        """Process all questions according to the specification using file search"""
        logger.info("Starting question processing with improved error handling")
        total_questions = 0
        processed_questions = 0
        
        questions_config = {
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
                "a": "Describe the job description of the claimants job",
                "b": "Describe the specific job duties of the claimants job"
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
                    results[section][question_id] = self.query_with_file_search(question_data)
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
                        results[section][question_id][value] = self.query_with_file_search(prompt)
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
        
        # Process results
        for section, questions in results.items():
            # Section header
            story.append(Paragraph(section, styles['Heading2']))
            story.append(Spacer(1, 12))
            
            for question_id, answer in questions.items():
                # Question header
                story.append(Paragraph(f"{question_id}.", styles['Heading3']))
                
                if isinstance(answer, str):
                    # Simple answer
                    story.append(Paragraph(answer, styles['Normal']))
                elif isinstance(answer, dict):
                    # Variable-based answers
                    for body_part, body_part_answer in answer.items():
                        story.append(Paragraph(f"<b>{body_part}:</b>", styles['Normal']))
                        story.append(Paragraph(body_part_answer, styles['Normal']))
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

# Initialize processor
processor = PDFProcessor()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_pdf():
    try:
        if 'pdf' not in request.files:
            return jsonify({'error': 'No PDF file provided'}), 400
        
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Set verbosity if provided
        verbosity = request.form.get('verbosity', 'detailed')
        processor.verbosity = verbosity
        
        # Upload PDF to OpenAI and create vector store
        success = processor.upload_pdf_to_openai(pdf_file)
        if not success:
            return jsonify({'error': 'Failed to upload PDF to OpenAI'}), 400
        
        return jsonify({
            'message': 'PDF uploaded successfully to OpenAI File Search',
            'vector_store_id': processor.vector_store_id,
            'assistant_id': processor.assistant_id
        })
    
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/process', methods=['POST'])
def process_pdf():
    try:
        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400
        
        # Extract variables
        variables = processor.extract_variables()
        
        # Process questions
        results = processor.process_questions()
        
        return jsonify({
            'variables': variables,
            'results': results
        })
    
    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/generate-report', methods=['POST'])
def generate_report():
    try:
        if not processor.vector_store_id:
            return jsonify({'error': 'No PDF uploaded'}), 400
        
        # Extract variables if not already done
        if not processor.variables:
            processor.extract_variables()
        
        # Process questions
        results = processor.process_questions()
        
        # Generate PDF report
        pdf_buffer = processor.generate_pdf_report(results)
        
        # Create reports directory if it doesn't exist
        reports_dir = os.path.join(os.getcwd(), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        
        # Save PDF to local file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f'medical_report_{timestamp}.pdf'
        filepath = os.path.join(reports_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(pdf_buffer.getvalue())
        
        logger.info(f"PDF report saved to: {filepath}")
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
    
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/set-verbosity', methods=['POST'])
def set_verbosity():
    try:
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
                - For lists, format as JSON arrays when requested
                - For dates, use mm/dd/yyyy format when specified
                - Maintain professional medical/legal terminology
                
                Always search through the uploaded documents to find relevant information before responding."""
            )
        
        return jsonify({'message': f'Verbosity set to {verbosity}'})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Clean up OpenAI resources"""
    try:
        processor.cleanup_resources()
        return jsonify({'message': 'Resources cleaned up successfully'})
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-query', methods=['POST'])
def test_query():
    """Test a simple query to diagnose assistant issues"""
    try:
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
            'assistant_id': processor.assistant_id
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=1776)