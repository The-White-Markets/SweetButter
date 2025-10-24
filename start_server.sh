#!/bin/bash

# Medical Legal PDF Processor - Server Startup Script
# Optimized for large file uploads (5000-10,000 pages)

set -e

echo "=========================================="
echo "Medical Legal PDF Processor"
echo "Large File Support Enabled"
echo "=========================================="
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  Warning: .env file not found!"
    echo "Create a .env file with:"
    echo "  OPENAI_API_KEY=your_key_here"
    echo "  SECRET_KEY=your_secret_key_here"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install/upgrade dependencies
echo "📚 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Check if gunicorn is installed
if ! command -v gunicorn &> /dev/null; then
    echo "❌ Gunicorn not found. Installing..."
    pip install gunicorn
fi

# Get port from environment or use default
PORT=${PORT:-8080}

echo ""
echo "=========================================="
echo "✅ Configuration:"
echo "   - Port: $PORT"
echo "   - Workers: Auto (CPU based)"
echo "   - Timeout: 600s (10 minutes)"
echo "   - Max file size: 2GB"
echo "   - Config: gunicorn_config.py"
echo "=========================================="
echo ""
echo "🚀 Starting server..."
echo "   Access at: http://127.0.0.1:$PORT"
echo ""
echo "📝 Logs will appear below..."
echo "   Press Ctrl+C to stop"
echo ""
echo "=========================================="
echo ""

# Start gunicorn with the configuration file
gunicorn -c gunicorn_config.py app:app
