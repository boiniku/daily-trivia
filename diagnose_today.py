import requests
import json
import datetime

BACKEND_URL = 'https://daily-trivia-e7ge.onrender.com'
# BACKEND_URL = 'http://localhost:8000' # For local testing if needed

def diagnose_today():
    print(f"🔍 Diagnosing: {BACKEND_URL}/trivia/today")
    user_id = "test-user-diag-today"
    
    print("\n--- Testing GET /trivia/today ---")
    try:
        response = requests.get(f"{BACKEND_URL}/trivia/today?user_id={user_id}&limit=3")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Response count: {len(data)}")
            if len(data) > 0:
                print(f"First item: {json.dumps(data[0], indent=2, ensure_ascii=False)}")
            else:
                print("Response is empty list []")
        else:
            print(f"Error Response: {response.text}")
    except Exception as e:
        print(f"GET Failed: {e}")

if __name__ == "__main__":
    diagnose_today()
