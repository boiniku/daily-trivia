import requests
import json

# Testing against LOCAL backend
BACKEND_URL = 'http://localhost:8000'

def test_create_collection():
    print(f"Testing connection to: {BACKEND_URL}")
    
    user_id = "test-user-local"
    
    payload = {
        "user_id": user_id,
        "title": "Test Folder Local",
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
