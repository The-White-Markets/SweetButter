#!/usr/bin/env python3
"""
Setup script for Medical Legal PDF Processor
"""

import os
import sys
import subprocess

def run_command(command):
    """Run a shell command and return success status"""
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✓ {command}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {command}")
        print(f"Error: {e.stderr}")
        return False

def main():
    print("🏥 Medical Legal PDF Processor Setup")
    print("=" * 50)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    
    # Install dependencies
    print("\n📦 Installing dependencies...")
    if not run_command("pip install -r requirements.txt"):
        print("❌ Failed to install dependencies")
        sys.exit(1)
    
    # Create .env file if it doesn't exist
    if not os.path.exists('.env'):
        print("\n🔑 Creating .env file...")
        with open('.env', 'w') as f:
            f.write("OPENAI_API_KEY=your_openai_api_key_here\n")
        print("✓ Created .env file")
        print("⚠️  Please edit .env and add your OpenAI API key")
    else:
        print("✓ .env file already exists")
    
    print("\n🎉 Setup complete!")
    print("\nNext steps:")
    print("1. Edit .env and add your OpenAI API key")
    print("2. Run: python app.py (for port 1776)")
    print("   Or: python app_1789.py (for port 1789)")
    print("3. Open http://localhost:1776 or http://localhost:1789")
    print("\n📚 See README.md for detailed instructions")

if __name__ == "__main__":
    main()
