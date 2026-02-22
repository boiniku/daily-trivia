import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import credentials, auth
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase Admin SKD (Requires GOOGLE_APPLICATION_CREDENTIALS in .env or initialized with cert)
# For now, we will assume the environment variable or service account json is provided.
try:
    # If a service account path is in .env, use it. Otherwise, init app will look for GOOGLE_APPLICATION_CREDENTIALS
    service_acc_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    if service_acc_path and os.path.exists(service_acc_path):
        cred = credentials.Certificate(service_acc_path)
        firebase_admin.initialize_app(cred)
    else:
        # Default initialization (relies on GOOGLE_APPLICATION_CREDENTIALS var being set)
        firebase_admin.initialize_app()
except ValueError:
    # App already initialized
    pass
except Exception as e:
    print(f"Firebase Admin Initialization Error: {e}")

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verifies the Firebase ID token in the Authorization header.
    Returns the decoded token dictionary.
    Raises 401 Unauthorized if invalid.
    """
    token = credentials.credentials
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        print(f"Token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user_id(decoded_token: dict = Depends(verify_token)) -> str:
    """
    Dependency to get the verified user_id (uid) from the token.
    """
    uid = decoded_token.get("uid")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user ID",
        )
    return uid
