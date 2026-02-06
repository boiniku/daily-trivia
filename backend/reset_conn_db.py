from database import engine
from models import Base, Collection
from sqlalchemy import text

def reset_collections():
    print("Dropping collections table...")
    # Drop table directly using SQL to ensure it's gone
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS collection_items"))
        conn.execute(text("DROP TABLE IF EXISTS collections"))
        conn.commit()
    
    print("Recreating tables...")
    Base.metadata.create_all(bind=engine)
    print("Done!")

if __name__ == "__main__":
    reset_collections()
