#!/usr/bin/env python3
"""
Test script to verify user isolation in the Flask application.
This script simulates multiple users accessing the application simultaneously.
"""

import requests
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# Configuration
BASE_URL = "http://localhost:8080"
TEST_PDF_PATH = "test.pdf"  # Make sure this file exists

def simulate_user(user_id, session_cookies=None):
    """Simulate a single user session"""
    print(f"User {user_id}: Starting session...")
    
    # Create a session to maintain cookies
    session = requests.Session()
    
    # Get initial status
    try:
        response = session.get(f"{BASE_URL}/api/status")
        status = response.json()
        print(f"User {user_id}: Initial status - {status}")
    except Exception as e:
        print(f"User {user_id}: Error getting status - {e}")
        return
    
    # Upload a test PDF (if available)
    try:
        with open(TEST_PDF_PATH, 'rb') as f:
            files = {'pdf': f}
            data = {'verbosity': 'detailed'}
            response = session.post(f"{BASE_URL}/upload", files=files, data=data)
            upload_result = response.json()
            print(f"User {user_id}: Upload result - {upload_result}")
    except FileNotFoundError:
        print(f"User {user_id}: Test PDF not found, skipping upload")
    except Exception as e:
        print(f"User {user_id}: Upload error - {e}")
    
    # Get session info
    try:
        response = session.get(f"{BASE_URL}/api/session-info")
        session_info = response.json()
        print(f"User {user_id}: Session info - {session_info}")
    except Exception as e:
        print(f"User {user_id}: Session info error - {e}")
    
    # Wait a bit
    time.sleep(2)
    
    # Get final status
    try:
        response = session.get(f"{BASE_URL}/api/status")
        final_status = response.json()
        print(f"User {user_id}: Final status - {final_status}")
    except Exception as e:
        print(f"User {user_id}: Final status error - {e}")
    
    print(f"User {user_id}: Session completed")

def test_concurrent_users():
    """Test multiple users accessing the application simultaneously"""
    print("Testing user isolation with 4 concurrent users...")
    print("=" * 60)
    
    # Start the Flask app first (you'll need to run this manually)
    print("Make sure the Flask app is running on localhost:8080")
    print("Run: python app.py")
    print("=" * 60)
    
    # Simulate 4 users
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for i in range(4):
            future = executor.submit(simulate_user, f"User-{i+1}")
            futures.append(future)
        
        # Wait for all users to complete
        for future in futures:
            future.result()
    
    print("=" * 60)
    print("Test completed! Check the output above to verify user isolation.")
    print("Each user should have their own session ID and processor instance.")

if __name__ == "__main__":
    test_concurrent_users()