# Testing Guide for Large File Support

This guide provides testing procedures to verify that the large file upload functionality works correctly.

## Pre-Testing Checklist

- [ ] Server is running with gunicorn configuration
- [ ] OpenAI API key is configured in `.env`
- [ ] At least 4GB RAM available
- [ ] Sufficient disk space (5GB+ free)
- [ ] Stable internet connection

## Test Cases

### Test 1: Small File Upload (Baseline)

**Objective**: Verify basic functionality works

**Steps**:
1. Upload a PDF file < 10MB (< 100 pages)
2. Verify upload completes in < 30 seconds
3. Check that vector store is created
4. Test a simple query on the document

**Expected Results**:
- ✅ Upload succeeds
- ✅ Progress bar shows 100%
- ✅ Success message appears
- ✅ Query returns relevant information

### Test 2: Medium File Upload

**Objective**: Test with moderately large files

**Steps**:
1. Upload a PDF file 50-100MB (500-1000 pages)
2. Monitor upload progress
3. Note the time taken
4. Verify processing completes successfully

**Expected Results**:
- ✅ Upload completes in 2-5 minutes
- ✅ Progress updates show status
- ✅ Vector store processes successfully
- ✅ File is searchable

**Metrics to Record**:
- File size: ________ MB
- Upload time: ________ seconds
- Processing time: ________ seconds
- Total time: ________ seconds

### Test 3: Large File Upload (5000 pages)

**Objective**: Test with very large files

**Steps**:
1. Upload a PDF file 500-750MB (~5000 pages)
2. Watch for "Large file upload" warning
3. Monitor server logs in real-time
4. Wait for complete processing
5. Test queries on the document

**Expected Results**:
- ✅ Warning message for large file appears
- ✅ Upload completes within 10 minutes
- ✅ Progress bar animates smoothly
- ✅ No timeout errors
- ✅ Vector store creates successfully
- ✅ Document is searchable

**Metrics to Record**:
- File size: ________ MB
- Number of pages: ________
- Upload time: ________ minutes
- Processing time: ________ minutes
- Total time: ________ minutes

### Test 4: Extra Large File Upload (10000 pages)

**Objective**: Test maximum capacity

**Steps**:
1. Upload a PDF file 1-2GB (~10000 pages)
2. Verify warning appears
3. Monitor system resources (RAM/CPU)
4. Watch server logs for errors
5. Wait for completion (may take 15+ minutes)

**Expected Results**:
- ✅ Upload accepted (no file size error)
- ✅ System remains responsive
- ✅ Memory usage stays reasonable
- ✅ Processing completes without timeout
- ✅ Document is fully searchable

**Metrics to Record**:
- File size: ________ MB
- Number of pages: ________
- Peak RAM usage: ________ GB
- Upload time: ________ minutes
- Processing time: ________ minutes
- Total time: ________ minutes

### Test 5: Timeout Handling

**Objective**: Verify timeout error handling

**Steps**:
1. Temporarily set shorter timeout (60s) in code
2. Upload large file
3. Wait for timeout to occur
4. Check error message

**Expected Results**:
- ✅ Timeout error is caught gracefully
- ✅ User-friendly error message displays
- ✅ System remains stable
- ✅ Can retry upload

### Test 6: Network Interruption

**Objective**: Test resilience to connection issues

**Steps**:
1. Start uploading a large file
2. Briefly disconnect network during upload
3. Reconnect network
4. Observe behavior

**Expected Results**:
- ✅ Upload fails with appropriate error
- ✅ User can retry
- ✅ No data corruption
- ✅ System recovers properly

### Test 7: Concurrent Uploads

**Objective**: Test multiple simultaneous uploads

**Steps**:
1. Open application in 2 different browsers
2. Upload different files simultaneously
3. Monitor server resources
4. Verify both complete successfully

**Expected Results**:
- ✅ Both uploads succeed
- ✅ No interference between sessions
- ✅ Server handles load appropriately
- ✅ Each user's data is isolated

### Test 8: File Size Limit

**Objective**: Verify 2GB limit enforcement

**Steps**:
1. Try to upload a file > 2GB
2. Check for appropriate error message

**Expected Results**:
- ✅ Upload is rejected
- ✅ Error message indicates size limit
- ✅ No server crash or hang

### Test 9: Query Performance on Large Files

**Objective**: Verify search works well on large documents

**Steps**:
1. Upload a large file (5000+ pages)
2. Run various queries:
   - Simple keyword search
   - Complex medical terminology
   - Date-based queries
   - Multi-part questions
3. Measure response times

**Expected Results**:
- ✅ All queries return results
- ✅ Response time < 10 seconds
- ✅ Results are accurate
- ✅ Citations include page numbers

**Metrics to Record**:
- Simple query time: ________ seconds
- Complex query time: ________ seconds
- Average response time: ________ seconds

### Test 10: Memory Leak Test

**Objective**: Ensure no memory leaks with repeated uploads

**Steps**:
1. Note initial memory usage
2. Upload and process 5 medium-large files sequentially
3. Run cleanup between uploads
4. Check final memory usage

**Expected Results**:
- ✅ Memory returns to baseline after cleanup
- ✅ No progressive memory increase
- ✅ All resources are freed properly

**Metrics to Record**:
- Initial RAM: ________ MB
- After upload 1: ________ MB
- After upload 2: ________ MB
- After upload 3: ________ MB
- After upload 4: ________ MB
- After upload 5: ________ MB
- After cleanup: ________ MB

## Automated Testing Script

Create `test_large_files.py`:

```python
import requests
import time
import os

API_BASE = "http://localhost:8080"

def test_upload(file_path):
    """Test PDF upload"""
    print(f"Testing upload: {file_path}")

    file_size = os.path.getsize(file_path) / (1024 * 1024)
    print(f"File size: {file_size:.2f} MB")

    start_time = time.time()

    with open(file_path, 'rb') as f:
        files = {'pdf': f}
        data = {'verbosity': 'detailed'}

        response = requests.post(
            f"{API_BASE}/upload",
            files=files,
            data=data,
            timeout=600
        )

    upload_time = time.time() - start_time

    print(f"Status: {response.status_code}")
    print(f"Upload time: {upload_time:.2f}s")

    if response.ok:
        result = response.json()
        print(f"Vector Store ID: {result.get('vector_store_id')}")
        print("✅ Upload successful")
        return True
    else:
        print(f"❌ Upload failed: {response.text}")
        return False

def test_query(query_text):
    """Test query after upload"""
    print(f"\nTesting query: {query_text}")

    start_time = time.time()

    response = requests.post(
        f"{API_BASE}/api/run-one",
        json={
            'type': 'simple',
            'prompt': query_text
        },
        timeout=600
    )

    query_time = time.time() - start_time

    print(f"Query time: {query_time:.2f}s")

    if response.ok:
        result = response.json()
        print(f"Result: {result.get('result', {}).get('text', '')[:100]}...")
        print("✅ Query successful")
        return True
    else:
        print(f"❌ Query failed: {response.text}")
        return False

if __name__ == "__main__":
    # Test with your file
    test_file = "path/to/your/large/file.pdf"

    if test_upload(test_file):
        time.sleep(5)  # Wait for processing
        test_query("What is the patient's name?")
```

## Performance Benchmarks

Expected performance based on testing:

| File Size | Pages | Upload | Process | Total | Status |
|-----------|-------|--------|---------|-------|--------|
| 10 MB | 100 | 10s | 30s | 40s | ✅ |
| 50 MB | 500 | 30s | 90s | 2m | ✅ |
| 100 MB | 1000 | 1m | 2m | 3m | ✅ |
| 500 MB | 5000 | 5m | 5m | 10m | ✅ |
| 1 GB | 8000 | 8m | 7m | 15m | ✅ |
| 2 GB | 10000 | 10m | 10m | 20m | ⚠️ |

## Monitoring During Tests

### Server Logs

Watch logs in real-time:
```bash
tail -f /path/to/gunicorn/error.log | grep -E "Processing PDF|Upload|Large file"
```

### System Resources

```bash
# Watch memory
watch -n 1 'free -h'

# Watch disk I/O
iostat -x 2

# Watch network
iftop

# Complete system view
htop
```

### Application Metrics

Check these during testing:
- CPU usage should stay < 80%
- Memory usage should not exceed available RAM
- Disk I/O should be active during upload
- Network traffic should correlate with upload size

## Test Results Template

```
===========================================
LARGE FILE UPLOAD TEST RESULTS
===========================================

Test Date: _______________
Server: _______________
Configuration:
  - Workers: ___
  - RAM: ___ GB
  - Timeout: ___ seconds

Test 1 - Small File (< 10MB):
  ☐ Pass  ☐ Fail
  Time: _____
  Notes: _______________

Test 2 - Medium File (50-100MB):
  ☐ Pass  ☐ Fail
  Time: _____
  Notes: _______________

Test 3 - Large File (~5000 pages):
  ☐ Pass  ☐ Fail
  Time: _____
  Notes: _______________

Test 4 - Extra Large File (~10000 pages):
  ☐ Pass  ☐ Fail
  Time: _____
  Notes: _______________

Test 5 - Timeout Handling:
  ☐ Pass  ☐ Fail
  Notes: _______________

Test 6 - Network Interruption:
  ☐ Pass  ☐ Fail
  Notes: _______________

Test 7 - Concurrent Uploads:
  ☐ Pass  ☐ Fail
  Notes: _______________

Test 8 - File Size Limit:
  ☐ Pass  ☐ Fail
  Notes: _______________

Test 9 - Query Performance:
  ☐ Pass  ☐ Fail
  Avg Time: _____
  Notes: _______________

Test 10 - Memory Leak:
  ☐ Pass  ☐ Fail
  Notes: _______________

Overall Result: ☐ Pass  ☐ Fail

Issues Found:
1. _______________
2. _______________
3. _______________

Recommendations:
1. _______________
2. _______________
3. _______________

Tested By: _______________
Signature: _______________
===========================================
```

## Next Steps After Testing

1. **Document Results**: Record all metrics
2. **Fix Issues**: Address any failures
3. **Optimize**: Improve based on performance data
4. **Re-test**: Verify fixes work
5. **Deploy**: Move to production if all tests pass
