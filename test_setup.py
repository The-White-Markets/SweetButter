#!/usr/bin/env python3
"""
Test script to verify the Medical Legal PDF Processor setup
"""

import os
import sys
import importlib.util

def test_import(module_name):
    """Test if a module can be imported"""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return False
        return True
    except ImportError:
        return False

def main():
    print("🧪 Testing Medical Legal PDF Processor Setup")
    print("=" * 50)
    
    # Test Python version
    if sys.version_info >= (3, 8):
        print(f"✓ Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    else:
        print(f"❌ Python version: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} (3.8+ required)")
        return False
    
    # Test required modules
    required_modules = [
        'flask',
        'flask_cors', 
        'openai',
        'PyPDF2',
        'reportlab',
        'dotenv'
    ]
    
    print("\n📦 Testing required modules:")
    all_modules_ok = True
    
    for module in required_modules:
        if test_import(module):
            print(f"✓ {module}")
        else:
            print(f"❌ {module}")
            all_modules_ok = False
    
    # Test environment file
    print("\n🔑 Testing environment setup:")
    if os.path.exists('.env'):
        print("✓ .env file exists")
        
        # Check if API key is set
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key and api_key != 'your_openai_api_key_here':
            print("✓ OpenAI API key is configured")
        else:
            print("⚠️  OpenAI API key needs to be set in .env file")
    else:
        print("❌ .env file not found")
        all_modules_ok = False
    
    # Test file structure
    print("\n📁 Testing file structure:")
    required_files = [
        'app.py',
        'app_1789.py',
        'requirements.txt',
        'templates/index.html'
    ]
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✓ {file_path}")
        else:
            print(f"❌ {file_path}")
            all_modules_ok = False
    
    print("\n" + "=" * 50)
    
    if all_modules_ok:
        print("🎉 All tests passed! Setup is ready.")
        print("\nTo start the application:")
        print("  python app.py      (runs on port 1776)")
        print("  python app_1789.py (runs on port 1789)")
        return True
    else:
        print("❌ Some tests failed. Please check the setup.")
        print("\nTo fix issues:")
        print("  1. Run: pip install -r requirements.txt")
        print("  2. Create .env file with your OpenAI API key")
        print("  3. Ensure all required files are present")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
