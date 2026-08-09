import requests
import json

BACKEND_URL = 'https://daily-trivia-e7ge.onrender.com'

def diagnose_remote():
    print(f"🔍 Diagnosing: {BACKEND_URL}")
    user_id = "test-user-diag"
    
    # 1. Test GET (Read Collections) - Should work if server is up
    print("\n--- Testing GET /collections ---")
    try:
        response = requests.get(f"{BACKEND_URL}/collections?user_id={user_id}")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}...") # Print first 200 chars
    except Exception as e:
        print(f"GET Failed: {e}")

    # 2. Test POST (Create Collection) - The failing endpoint
    print("\n--- Testing POST /collections ---")
    payload = {
        "user_id": user_id,
        "title": "Diagnosis Folder",
        "icon": "folder-outline"
    }
    try:
        response = requests.post(
            f"{BACKEND_URL}/collections",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        print(f"Headers: {response.headers}")
    except Exception as e:
        print(f"POST Failed: {e}")

    # 3. Test POST with trailing slash (Just in case)
    print("\n--- Testing POST /collections/ (with slash) ---")
    try:
        response = requests.post(
            f"{BACKEND_URL}/collections/",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}...")
    except Exception as e:
        print(f"POST/ Failed: {e}")

if __name__ == "__main__":
    diagnose_remote()
