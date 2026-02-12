from database import engine, Base
from models import Trivia, TriviaHee
from sqlalchemy import text

def update_schema():
    print("Updating schema for Hee button...")
    
    # 1. Add hee_count column to trivia table if not exists
    with engine.connect() as conn:
        try:
            # Check if column exists
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='trivia' AND column_name='hee_count'"))
            if not result.fetchone():
                print("Adding hee_count column to trivia table...")
                conn.execute(text("ALTER TABLE trivia ADD COLUMN hee_count INTEGER DEFAULT 0"))
                conn.commit()
            else:
                print("hee_count column already exists.")
        except Exception as e:
            print(f"Error adding column: {e}")

    # 2. Create trivia_hees table
    print("Creating trivia_hees table...")
    TriviaHee.__table__.create(bind=engine, checkfirst=True)
    
    print("Schema update complete!")

if __name__ == "__main__":
    update_schema()
