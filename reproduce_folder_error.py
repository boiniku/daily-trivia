import requests
import json

# Config for production backend (as seen in user's Config.ts)
BACKEND_URL = 'https://daily-trivia-e7ge.onrender.com'

def test_create_collection():
    print(f"Testing connection to: {BACKEND_URL}")
    
    # Random temp user ID for testing
    user_id = "test-user-repro-script"
    
    payload = {
        "user_id": user_id,
        "title": "Test Folder From Script",
        "icon": "folder-outline"
    }
    
    print(f"Sending payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(
            f"{BACKEND_URL}/collections",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        
        if response.status_code == 200:
            print("✅ Success! Collection created.")
            data = response.json()
            print(f"Created Collection: {data}")
        else:
            print("❌ Failed to create collection.")
            
    except Exception as e:
        print(f"❌ Exception occurred: {e}")

if __name__ == "__main__":
    test_create_collection()
