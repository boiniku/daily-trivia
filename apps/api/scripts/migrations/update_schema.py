from database import engine, Base
from sqlalchemy import text
from models import Trivia, TriviaCandidate

def update_schema():
    print("Creating new tables (TriviaCandidate)...")
    Base.metadata.create_all(bind=engine)
    
    print("Checking and altering existing tables...")
    with engine.connect() as conn:
        with conn.begin():
            # Check if embedding column exists in trivia table
            # Simple check by trying to select it or just running ALTER TABLE with IF NOT EXISTS logic handled manually 
            # (Postgres doesn't have ADD COLUMN IF NOT EXISTS in older versions, but 'try/except' is safer or just querying catalog)
             try:
                conn.execute(text("ALTER TABLE trivia ADD COLUMN embedding JSON;"))
                print("Added 'embedding' column to trivia table.")
             except Exception as e:
                print(f"Embedding column might already exist or error: {e}")

if __name__ == "__main__":
    update_schema()
