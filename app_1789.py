import os
import sys

# Add the current directory to Python path to import from app.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app

if __name__ == '__main__':
    print("Starting Medical Legal PDF Processor on port 1789...")
    app.run(debug=True, host='0.0.0.0', port=1789)
