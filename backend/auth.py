import os
import json
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import firebase_admin
from firebase_admin import credentials, auth
from firebase_admin.exceptions import FirebaseError
from dotenv import load_dotenv
import logging
import sys

# Configure logging to output immediately
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(stream_handler)

load_dotenv()

# Initialize Firebase Admin SKD (Requires GOOGLE_APPLICATION_CREDENTIALS in .env or initialized with cert)
try:
    # 1. Try to load from a raw JSON string in environment variable (Render setup)
    service_acc_json_str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if service_acc_json_str:
        logger.info("Initializing Firebase Admin securely via JSON string")
        try:
            service_acc_info = json.loads(service_acc_json_str)
            cred = credentials.Certificate(service_acc_info)
            firebase_admin.initialize_app(cred)
        except json.JSONDecodeError as je:
            logger.error(f"JSON Parsing Error for FIREBASE_SERVICE_ACCOUNT_JSON. Ensure it is valid JSON: {je}")
            raise
    else:
        # 2. Try file path
        service_acc_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if service_acc_path and os.path.exists(service_acc_path):
            logger.info(f"Initializing Firebase Admin via file: {service_acc_path}")
            cred = credentials.Certificate(service_acc_path)
            firebase_admin.initialize_app(cred)
        else:
            # 3. Default initialization (relies on GOOGLE_APPLICATION_CREDENTIALS)
            logger.info("Initializing Firebase Admin via default GOOGLE_APPLICATION_CREDENTIALS")
            firebase_admin.initialize_app()
except ValueError as ve:
    if "The default Firebase app already exists." in str(ve):
        logger.info("Firebase App already initialized.")
    else:
        logger.error(f"ValueError during Firebase init: {ve}")
except Exception as e:
    logger.error(f"Firebase Admin Initialization Error: {e}")

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verifies the Firebase ID token in the Authorization header.
    Returns the decoded token dictionary.
    Raises 401 Unauthorized if invalid.
    """
    token = credentials.credentials
    try:
        if not token:
            logger.warning("Empty token provided.")
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
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
