import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Admin connection (neondb_owner) - bypasses RLS
# Used by admin_dashboard.py
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to backend/.env or the process environment.")

# App connection (app_user) - subject to RLS policies
# Used by main.py API endpoints
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL", DATABASE_URL)

# Admin engine (existing behavior, used by admin_dashboard)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600
)

# App engine (RLS-enforced, used by API server)
app_engine = create_engine(
    APP_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600
)

# Admin session (for admin_dashboard.py - bypasses RLS)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# App session (for main.py - RLS enforced)
AppSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=app_engine)

Base = declarative_base()

# Legacy dependency (admin dashboard uses this)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_app_db(user_id: str = None):
    """
    Get a DB session with RLS context.
    Sets app.current_user_id so RLS policies can filter by user.
    """
    db = AppSessionLocal()
    try:
        if user_id:
            db.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
        yield db
    finally:
        db.close()
