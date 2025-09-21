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
import fitz  # PyMuPDF for better PDF text extraction

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
        self.pdf_content = None
        self.variables = {}
        self.results = {}  # Store processing results for report generation
        # Limit input size to avoid context window and rate limit issues
        self.max_input_chars = 120_000
        
    def extract_pdf_text(self, pdf_file):
        """Extract text from PDF using PyMuPDF"""
        try:
            # Reset file pointer to beginning
            pdf_file.seek(0)
            
            # Create a temporary file to save the uploaded PDF
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(pdf_file.read())
                temp_file_path = temp_file.name
            
            # Extract text using PyMuPDF
            doc = fitz.open(temp_file_path)
            text_content = ""
            
            for page_num in range(doc.page_count):
                page = doc[page_num]
                text_content += f"\n--- Page {page_num + 1} ---\n"
                text_content += page.get_text()
            
            doc.close()
            self.pdf_content = text_content
            logger.info(f"PDF text extracted successfully: {len(text_content)} characters")
            
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except:
                pass
            
            return True
            
        except Exception as e:
            logger.error(f"Error extracting PDF text: {str(e)}")
            return False
    
    def _reduce_content(self, full_text: str) -> str:
        """Reduce the document text to fit within a safe character budget.

        Strategy: keep head and tail parts with an ellipsis marker in between.
        """
        if not full_text:
            return ""
        if len(full_text) <= self.max_input_chars:
            return full_text
        # Split budget between head and tail
        half = self.max_input_chars // 2
        head = full_text[:half]
        tail = full_text[-half:]
        return head + "\n\n...[CONTENT TRUNCATED FOR CONTEXT LIMIT]...\n\n" + tail

    def query_with_responses_api(self, prompt, max_tokens=1000):
        """Query using OpenAI's Responses API with GPT-5"""
        try:
            if not self.pdf_content:
                return "Error: No PDF content available"
            
            # Reduce content to stay within context limits
            reduced_content = self._reduce_content(self.pdf_content)

            # Prepare the input message with PDF content and user prompt
            input_message = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text", 
                            "text": f"""You are a medical legal document analyzer. Analyze the following medical document with {self.verbosity} responses.

When extracting information:
- Be thorough and accurate
- Use the exact information from the documents
- For lists, format as JSON arrays when requested
- For dates, use mm/dd/yyyy format when specified
- Maintain professional medical/legal terminology

DOCUMENT CONTENT:
{reduced_content}

QUESTION: {prompt}"""
                        }
                    ]
                }
            ]
            
            # Make the API call using Responses API with basic retry on 429
            last_err = None
            for attempt in range(3):
                try:
                    response = client.responses.create(
                        model="gpt-5",
                        input=input_message
                    )
                    break
                except Exception as api_err:
                    err_text = str(api_err)
                    last_err = api_err
                    if "429" in err_text or "rate limit" in err_text.lower():
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    else:
                        raise
            
            # Extract the response text
            if hasattr(response, 'output_text'):
                return response.output_text
            elif hasattr(response, 'output') and hasattr(response.output, 'text'):
                return response.output.text
            else:
                # Fallback to accessing response data
                return str(response)
                
        except Exception as e:
            logger.error(f"Error querying with Responses API: {str(e)}")
            return f"Error: {str(e)}"
    
    def extract_variables(self):
        """Extract key variables from the document"""
        try:
            variables_prompt = """Extract the following key variables from this medical legal document. Return your response in JSON format:

{
    "agreed_upon_body_parts": ["list of body parts both attorneys agree are affected"],
    "disagreed_upon_body_parts": ["list of body parts with attorney disagreement"],
    "previous_injuries": ["list of all previous injuries mentioned"],
    "applicant_attorney_alleged_body_parts": ["combined agreed + disagreed body parts"]
}

If any category has no relevant information, use an empty array []."""

            result = self.query_with_responses_api(variables_prompt)
            
            try:
                # Try to parse as JSON
                self.variables = json.loads(result)
                logger.info(f"Variables extracted successfully: {list(self.variables.keys())}")
            except json.JSONDecodeError:
                # If not valid JSON, extract manually
                logger.warning("Could not parse variables as JSON, using text response")
                self.variables = {"raw_response": result}
            
            return self.variables
            
        except Exception as e:
            logger.error(f"Error extracting variables: {str(e)}")
            return {}
    
    def cleanup(self):
        """Clean up resources (not needed for Responses API, but keeping for compatibility)"""
        logger.info("Cleanup completed (no resources to clean for Responses API)")
        return True

# Global processor instance
processor = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_pdf():
    global processor
    try:
        if 'pdf' not in request.files:
            return jsonify({'error': 'No PDF file provided'}), 400
        
        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Create new processor instance
        processor = PDFProcessor()
        
        # Extract PDF text
        success = processor.extract_pdf_text(pdf_file)
        
        if not success:
            return jsonify({'error': 'Failed to extract PDF text'}), 400
        
        return jsonify({'message': 'PDF uploaded and text extracted successfully'})
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/process', methods=['POST'])
def process_pdf():
    global processor
    try:
        if not processor or not processor.pdf_content:
            return jsonify({'error': 'No PDF content available. Please upload a PDF first.'}), 400
        
        # Extract variables
        variables = processor.extract_variables()
        
        # Process main questions
        questions = get_medical_questions()
        results = {}
        
        for category, question_list in questions.items():
            logger.info(f"Processing category: {category}")
            category_results = []
            
            for question in question_list:
                # Substitute variables in questions
                processed_question = substitute_variables(question, variables)
                
                # Get answer using Responses API
                answer = processor.query_with_responses_api(processed_question)
                
                category_results.append({
                    'question': processed_question,
                    'answer': answer
                })
            
            results[category] = category_results
        
        # Store results in processor for report generation
        processor.results = results
        
        return jsonify({
            'variables': variables,
            'results': results,
            'status': 'completed'
        })
        
    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/generate_report', methods=['POST'])
@app.route('/generate-report', methods=['POST'])
def generate_report():
    global processor
    try:
        if not processor:
            return jsonify({'error': 'No processor available'}), 400
        
        # Get data from request
        if request.is_json:
            data = request.get_json()
        else:
            # Fallback: get from form data or use defaults
            data = request.form.to_dict()
        
        variables = data.get('variables', {})
        results = data.get('results', {})
        
        # If no data provided, use processor's current data
        if not variables and not results:
            variables = processor.variables if processor else {}
            results = processor.results if processor else {}
        
        # Generate PDF report
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1*inch)
        story = []
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=20,
            alignment=1  # Center alignment
        )
        
        # Title
        story.append(Paragraph("Medical Legal Document Analysis Report", title_style))
        story.append(Spacer(1, 20))
        
        # Variables section
        if variables:
            story.append(Paragraph("Extracted Variables", styles['Heading2']))
            for key, value in variables.items():
                if isinstance(value, list):
                    value_str = ', '.join(value) if value else 'None'
                else:
                    value_str = str(value)
                story.append(Paragraph(f"<b>{key.replace('_', ' ').title()}:</b> {value_str}", styles['Normal']))
            story.append(Spacer(1, 20))
        
        # Results section
        for category, questions in results.items():
            story.append(Paragraph(category.replace('_', ' ').title(), styles['Heading2']))
            for i, qa in enumerate(questions, 1):
                story.append(Paragraph(f"<b>Q{i}:</b> {qa['question']}", styles['Normal']))
                story.append(Paragraph(f"<b>A:</b> {qa['answer']}", styles['Normal']))
                story.append(Spacer(1, 12))
        
        doc.build(story)
        buffer.seek(0)
        
        # Save report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"medical_report_{timestamp}.pdf"
        filepath = os.path.join("reports", filename)
        
        os.makedirs("reports", exist_ok=True)
        with open(filepath, 'wb') as f:
            f.write(buffer.getvalue())
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup_resources():
    global processor
    try:
        if processor:
            processor.cleanup()
            processor = None
        return jsonify({'message': 'Resources cleaned up successfully'})
    except Exception as e:
        logger.error(f"Cleanup error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def get_medical_questions():
    """Return the medical legal questions organized by category"""
    return {
        "1. Demographics": [
            "Look at the defense attorney, applicant attorney letter and insurance company and itemize all the names and addresses of them.",
            """Look throughout the document and fill in the following, note that most information but sometimes not all can be found in notes, usually applicant or defense attorney letters:
            1. Claimant Name: (Last, First)
            2. Claimant Date of Birth: (mm/dd/yyyy)
            3. Claimant Employer: 
            4. Claimant Occupation:
            5. Claimant Date of Injury: (mm/dd/yyyy)
            6. Claim number:
            7. WCAB Number: 
            8. Date of Exam: (Leave this empty)"""
        ],
        "2. History of Injury (Patients Perspective)": [
            "Review the patients entire history of injury as described from the patients perspective and summarize it in a single paragraph."
        ],
        "3. History of Injury (Physicians Perspective)": [
            "Review the patients entire history of injury as described from the physicans notes and summarize it in a single paragraph"
        ],
        "4. Chief Complaints": [
            "Describe the patients chief complaints for all the agreed upon body parts",
            "Describe the patients chief complaints for all the disagreed upon body parts"
        ],
        "5. Claimants Job": [
            "Describe the job description of the claimants job",
            "Describe the specific job duties of the claimants job"
        ],
        "6. Work Status": [
            "Find the most recent work status and any work restrictions the claimant has",
            "Has the patient been taken off work? (If true write \"Patient is still working\" if false write Patient stopped working on (date) + write a 2 sentence explanation)"
        ],
        "7. Previous Injuries": [
            """Has the patient described any previous injuries
            If no then write "Patient has has to previous injuries" 
            If yes then for each of the previous injuries reiterate how the patient described the injuries in a few sentences."""
        ],
        "8. Medical History": [
            "Write a list of the entire non surgical medical history of the patient if applicable, if not, write \"No past medical history\""
        ],
        "9. Surgical History": [
            "Write a list of the entire surgical history of the patient if applicable, if not, write \"No past surgical history\""
        ],
        "10. Allergies": [
            "Write a list of all the patients allergies if applicable, if not, write \"Patient has no provided allergies\""
        ],
        "11. Current Medications": [
            "Write a list of all the medications the claimant is currently taking"
        ],
        "12. Social History": [
            "Write a list of any alcohol recreational drug, recreational tabaco, or vape use the patient has had, as well as when they did it according to the medical record."
        ],
        "13. Family history of illness": [
            "Write a list of any past medical or surgical history of family members"
        ],
        "16. Diagnostic Reports": [
            "Summarize each and every MRI with the diagnostic results of the MRI, in 5 or less sentences in chronological order. If there are no studies/results output \"none of these studies were completed\" with a brief explanation",
            "Summarize each and every CT or CAT scan with the diagnostic results of the CT or CAT scan, in 5 or less sentences in chronological order.",
            "Summarize each and every X-Rays with the diagnostic results of the X-Rays, in 5 or less sentences in chronological order.",
            "Summarize each and every Ultra Sound with the diagnostic results of the Ultra Sound, in 5 or less sentences in chronological order.",
            "Summarize each and every electro diagnostics (also including EMG, NCV, or NCS) with the diagnostic results of the electro diagnostics (also including EMG, NCV, or NCS), in 5 or less sentences in chronological order."
        ],
        "17. Doctors Notes": [
            "Summarize every individual dated note in about 7 sentences each, with the date first in chronological order."
        ],
        "20. Diagnostic impressions": [
            "Look through all the medical records and identify the diagnostic impressions for all applicant attorney alleged body parts"
        ],
        "21. Causation": [
            "Evaluate how and why this patients injury would be related to a specific injury at work",
            "Evaluate how and why this patients injury is secondary to cumulative trauma at work"
        ],
        "22. Impairment": [
            "For all applicant attorney alleged body parts go to the AMA 5th addition guidelines, find the appropriate impairment rating, and give a detailed description on how and why it has that impairment rating."
        ],
        "23. Periods Of Total Disability": [
            "For all applicant attorney alleged body parts explain how much time the average American would have to be completely off of work before they are transitioned to light duty."
        ],
        "24. Future Medical Care": [
            "For all applicant attorney alleged body parts define what future medical care would be needed according to the MTUS and ODG guidelines that would help cure or relieve current symptoms or future exacerbations."
        ]
    }

def substitute_variables(question, variables):
    """Substitute variables in questions"""
    if not variables:
        return question
    
    # Replace common variable placeholders
    replacements = {
        '{Agreed Upon Body Parts}': ', '.join(variables.get('agreed_upon_body_parts', [])),
        '{Disagreed Upon Body Parts}': ', '.join(variables.get('disagreed_upon_body_parts', [])),
        '{Previous Injuries}': ', '.join(variables.get('previous_injuries', [])),
        '{Applicant Attorney Alleged Body Parts}': ', '.join(variables.get('applicant_attorney_alleged_body_parts', []))
    }
    
    for placeholder, replacement in replacements.items():
        question = question.replace(placeholder, replacement or 'None specified')
    
    return question

if __name__ == '__main__':
    print("Starting Medical Legal PDF Processor with GPT-5 Responses API on port 1776...")
    app.run(debug=True, host='0.0.0.0', port=1776)
