# Large File Support (5000-10,000 Pages)

This document describes the improvements made to support uploading and processing very large PDF files (5000-10,000 pages) in the Medical Legal PDF Processor.

## Changes Made

### 1. Server Configuration

#### Gunicorn Configuration (`gunicorn_config.py`)
- **Worker timeout**: Increased to 600 seconds (10 minutes) to handle large file processing
- **Request size limits**: Removed limits to support files up to 2GB
- **Workers**: Configured based on CPU cores for optimal performance
- **Logging**: Enhanced logging for tracking large file uploads

#### Flask Configuration (`app.py`)
- **MAX_CONTENT_LENGTH**: Set to 2GB to accommodate large PDF files
- **Chunked file writing**: Uploads are now written in 8MB chunks to optimize memory usage
- **Enhanced logging**: Track file size and processing progress for large files

### 2. Processing Optimizations

#### Vector Store Processing
- **Timeout increased**: From 60s to 600s (10 minutes) for vector store file processing
- **Chunking strategy**: Using OpenAI's "auto" chunking strategy optimized for large documents
- **Progress logging**: Added detailed logging at each stage of processing

#### Query Processing
- **Query timeout**: Increased from 60s to 600s (10 minutes)
- **Check interval**: Optimized to 2 seconds to reduce API calls while monitoring progress
- **Retry logic**: Maintains 3 retry attempts with exponential backoff

### 3. Frontend Improvements

#### Upload Handling (`templates/index.html`)
- **Timeout**: Set to 600 seconds (10 minutes) for large file uploads
- **Progress tracking**: Animated progress bar for large files with status updates
- **File size warning**: Alerts users when uploading files > 100MB
- **AbortController**: Proper timeout handling with user-friendly error messages
- **Visual feedback**: Progress updates at different stages (uploading, processing, completing)

### 4. Error Handling

- **File size errors**: Specific error messages when files exceed 2GB limit
- **Timeout errors**: User-friendly messages explaining timeout issues
- **Connection errors**: Graceful handling of network interruptions
- **Logging**: Comprehensive error logging for debugging large file issues

## Running the Server

### Development Mode

```bash
# Standard Flask development server (not recommended for large files)
python app.py
```

### Production Mode with Gunicorn (Recommended)

```bash
# Using the gunicorn configuration file
gunicorn -c gunicorn_config.py app:app

# Or with explicit settings
gunicorn app:app \
  --workers 4 \
  --timeout 600 \
  --bind 0.0.0.0:8080 \
  --log-level info \
  --access-logfile - \
  --error-logfile -
```

### Environment Variables

Create a `.env` file with:

```env
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key_here
PORT=8080
```

## Performance Expectations

### File Size Guidelines

| File Size | Pages (Approx) | Upload Time | Processing Time |
|-----------|---------------|-------------|-----------------|
| 50-100 MB | 500-1000 | 1-2 min | 2-3 min |
| 100-500 MB | 1000-5000 | 2-5 min | 5-8 min |
| 500-1000 MB | 5000-8000 | 5-8 min | 8-10 min |
| 1-2 GB | 8000-10000 | 8-10 min | 10-15 min |

*Times are estimates and depend on network speed, server resources, and PDF complexity*

### System Requirements

For optimal performance with large files:

- **RAM**: Minimum 4GB, recommended 8GB+
- **CPU**: Multi-core processor recommended (4+ cores)
- **Network**: Stable high-speed internet connection
- **Disk**: Sufficient temporary storage (3x file size recommended)

## Best Practices

### For Users

1. **Check file size**: Ensure your PDF is under 2GB
2. **Stable connection**: Use a reliable internet connection
3. **Be patient**: Large files (5000+ pages) take 10-15 minutes to process
4. **Monitor progress**: Watch the progress bar and status messages
5. **Don't refresh**: Avoid refreshing the page during upload/processing

### For Administrators

1. **Monitor resources**: Watch server memory and CPU usage
2. **Log rotation**: Implement log rotation for production
3. **Backup strategy**: Regular backups of processed data
4. **Rate limiting**: Consider implementing rate limiting for very large files
5. **Cleanup**: Regularly clean up temporary files

## Troubleshooting

### Upload Fails with "File too large"
- Check that file is under 2GB
- Verify `MAX_CONTENT_LENGTH` in `app.py`
- Check web server (nginx/apache) upload limits if using reverse proxy

### Timeout During Processing
- Increase `timeout` in `gunicorn_config.py` if needed
- Check network connectivity to OpenAI API
- Verify OpenAI API quota and rate limits

### Out of Memory Errors
- Increase server RAM
- Reduce number of gunicorn workers
- Process files in smaller batches

### Slow Upload Speed
- Check network bandwidth
- Use wired connection instead of WiFi
- Consider server location (closer to users)
- Check for network throttling

## nginx Configuration (Optional)

If using nginx as a reverse proxy, add these settings:

```nginx
server {
    client_max_body_size 2G;
    client_body_timeout 600s;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Monitoring and Logging

### Check Logs

```bash
# View gunicorn logs
tail -f /path/to/access.log
tail -f /path/to/error.log

# View application logs
grep "Large file upload" /path/to/app.log
grep "Processing PDF" /path/to/app.log
```

### Key Metrics to Monitor

- Upload success rate
- Processing time per file size
- Memory usage during uploads
- API error rates
- Timeout occurrences

## Future Enhancements

Potential improvements for even better large file support:

1. **Streaming uploads**: Implement true streaming for files > 2GB
2. **Resume capability**: Allow resuming interrupted uploads
3. **Compression**: Optional PDF compression before upload
4. **Parallel processing**: Split large files for concurrent processing
5. **Progress webhooks**: Real-time progress updates via websockets
6. **Batch processing**: Queue system for multiple large files

## Support

For issues with large file uploads:

1. Check this documentation
2. Review server logs
3. Verify system requirements
4. Contact support with file size and error details
