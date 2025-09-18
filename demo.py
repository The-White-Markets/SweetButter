#!/usr/bin/env python3
"""
Demo script to show how the Medical Legal PDF Processor works
"""

import os
import sys
from app import PDFProcessor

def create_sample_medical_text():
    """Create a sample medical text for demonstration"""
    return """
MEDICAL LEGAL REPORT

Defense Attorney: John Smith, Smith & Associates, 123 Legal St, City, State 12345
Applicant Attorney: Jane Doe, Doe Law Firm, 456 Attorney Ave, City, State 12345
Insurance Company: ABC Insurance, 789 Insurance Blvd, City, State 12345

Claimant Name: Johnson, Robert
Claimant Date of Birth: 03/15/1980
Claimant Employer: Construction Corp
Claimant Occupation: Construction Worker
Claimant Date of Injury: 06/20/2023
Claim number: CLM-2023-5678
WCAB Number: WC-2023-9012

HISTORY OF INJURY (Patient's Perspective):
The patient reports that on June 20, 2023, while working construction, he was lifting heavy materials when he felt sudden severe pain in his lower back and right shoulder. The pain radiated down his right leg. He immediately stopped work and sought medical attention.

HISTORY OF INJURY (Physician's Perspective):
Medical records indicate acute lumbar strain with possible disc involvement at L4-L5 level. Patient also sustained rotator cuff injury to right shoulder during the same incident.

AGREED UPON BODY PARTS (Both attorneys agree):
- Lower back (lumbar spine)
- Right shoulder

DISAGREED UPON BODY PARTS (Attorneys disagree):
- Right leg (applicant claims, defense disputes)

CHIEF COMPLAINTS:
Lower back: Constant aching pain, worse with bending and lifting
Right shoulder: Sharp pain with overhead motion, weakness
Right leg: Numbness and tingling (disputed by defense)

JOB DESCRIPTION:
Construction worker responsible for heavy lifting, operating machinery, and general construction tasks requiring significant physical demands.

PREVIOUS INJURIES:
Patient reports no previous significant injuries to back or shoulder.

MEDICAL HISTORY:
No significant past medical history. Patient is generally healthy.

CURRENT MEDICATIONS:
- Ibuprofen 800mg TID
- Cyclobenzaprine 10mg QHS

DIAGNOSTIC REPORTS:
MRI Lumbar Spine (07/15/2023): Shows disc bulge at L4-L5 with mild neural foraminal narrowing
MRI Right Shoulder (07/20/2023): Reveals partial thickness rotator cuff tear

DIAGNOSTIC IMPRESSIONS:
Lower back: Lumbar disc bulge L4-L5 with radiculopathy
Right shoulder: Partial thickness rotator cuff tear
"""

def demo_variable_extraction():
    """Demonstrate variable extraction"""
    print("🔍 Variable Extraction Demo")
    print("=" * 40)
    
    processor = PDFProcessor()
    processor.pdf_text = create_sample_medical_text()
    
    # Mock the OpenAI responses for demo
    processor.variables = {
        "Agreed Upon Body Parts": ["Lower back", "Right shoulder"],
        "Disagreed Upon Body Parts": ["Right leg"],
        "Previous Injuries": [],
        "Applicant Attorney Alleged Body Parts": ["Lower back", "Right shoulder", "Right leg"]
    }
    
    print("Extracted Variables:")
    for var_name, values in processor.variables.items():
        print(f"  {var_name}: {values}")
    
    return processor

def demo_question_processing(processor):
    """Demonstrate question processing"""
    print("\n📝 Question Processing Demo")
    print("=" * 40)
    
    # Sample questions that would be processed
    sample_questions = {
        "Demographics": "Extract claimant information",
        "Chief Complaints (Lower back)": "Describe chief complaints for lower back",
        "Chief Complaints (Right shoulder)": "Describe chief complaints for right shoulder", 
        "Chief Complaints (Right leg)": "Describe chief complaints for right leg"
    }
    
    print("Sample questions that would be processed:")
    for question, description in sample_questions.items():
        print(f"  • {question}: {description}")
    
    print(f"\nTotal body parts to process: {len(processor.variables['Applicant Attorney Alleged Body Parts'])}")
    print("Variable substitution would create separate API calls for each body part.")

def main():
    print("🏥 Medical Legal PDF Processor Demo")
    print("=" * 50)
    print("This demo shows how the application processes medical legal documents.\n")
    
    # Demo variable extraction
    processor = demo_variable_extraction()
    
    # Demo question processing
    demo_question_processing(processor)
    
    print("\n🎯 Key Features Demonstrated:")
    print("  ✓ PDF text extraction")
    print("  ✓ Variable identification (body parts, injuries)")
    print("  ✓ Dynamic question generation")
    print("  ✓ Variable substitution for repeated queries")
    print("  ✓ Structured report generation")
    
    print("\n🚀 To use the full application:")
    print("  1. Add your OpenAI API key to .env file")
    print("  2. Run: python3 app.py")
    print("  3. Open: http://localhost:1776")
    print("  4. Upload a PDF and click 'Process & Preview'")
    print("  5. Generate the final PDF report")

if __name__ == "__main__":
    main()
