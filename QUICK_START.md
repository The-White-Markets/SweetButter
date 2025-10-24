# Quick Start Guide - Large File Support

## 🚀 Get Started in 3 Steps

### Step 1: Configure Environment

Create `.env` file in the project root:

```bash
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key_here
PORT=8080
```

### Step 2: Start the Server

**macOS/Linux:**
```bash
chmod +x start_server.sh
./start_server.sh
```

**Windows:**
```bash
start_server.bat
```

**Manual Start:**
```bash
# Activate virtual environment
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate.bat  # Windows

# Start server
gunicorn -c gunicorn_config.py app:app
```

### Step 3: Upload Your File

1. Open browser: `http://localhost:8080`
2. Drag & drop your PDF (up to 2GB)
3. Wait for processing (10-15 min for large files)
4. Start querying your document!

---

## 📋 What's New

✅ **2GB file size support** (up from previous limits)
✅ **10-minute timeouts** (handles 10,000 page documents)
✅ **Progress tracking** with visual feedback
✅ **Optimized memory usage** with chunked processing
✅ **Better error messages** and user guidance

---

## 📊 Expected Upload Times

| File Size | Pages | Time |
|-----------|-------|------|
| 10 MB | ~100 | 30s |
| 100 MB | ~1,000 | 3 min |
| 500 MB | ~5,000 | 10 min |
| 1 GB | ~8,000 | 15 min |
| 2 GB | ~10,000 | 20 min |

---

## ⚠️ Important Notes

- **Be Patient**: Large files take time. Don't refresh the page!
- **Stable Connection**: Ensure reliable internet during upload
- **System Resources**: 4GB+ RAM recommended for large files
- **File Limit**: Maximum 2GB per file

---

## 🔍 Troubleshooting

### Upload Timeout?
- Check internet connection
- Verify file size < 2GB
- Try again (OpenAI API may be slow)

### "File too large" Error?
- Current limit is 2GB
- Split large PDFs into smaller files

### Out of Memory?
- Close other applications
- Increase system RAM
- Reduce gunicorn workers in `gunicorn_config.py`

---

## 📚 More Information

- **Technical Details**: [LARGE_FILE_SUPPORT.md](LARGE_FILE_SUPPORT.md)
- **Deployment Guide**: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- **Testing Procedures**: [TESTING_GUIDE.md](TESTING_GUIDE.md)
- **Full Changelog**: [UPGRADE_SUMMARY.md](UPGRADE_SUMMARY.md)

---

## 💡 Tips for Best Performance

1. **Use wired connection** instead of WiFi for large uploads
2. **Close unnecessary applications** to free up RAM
3. **Upload during off-peak hours** for faster OpenAI processing
4. **Monitor progress** via the progress bar and status messages
5. **Check logs** if something goes wrong: `tail -f error.log`

---

## 🎯 Quick Commands

```bash
# Start server
./start_server.sh

# View logs
tail -f error.log

# Check disk space
df -h

# Monitor memory
free -h  # Linux
vm_stat  # macOS

# Stop server
Ctrl+C (or kill gunicorn process)
```

---

## ✅ Ready to Go!

Your system is now configured to handle very large PDF files (5,000-10,000 pages). Simply start the server and upload your documents!

**Need Help?** Check the troubleshooting guides or review the logs for detailed error information.
