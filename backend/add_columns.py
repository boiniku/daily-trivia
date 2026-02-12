from database import engine
from sqlalchemy import text, inspect

def add_missing_columns():
    inspector = inspect(engine)
    
    try:
        # Check collection_items
        if inspector.has_table("collection_items"):
            ci_columns = [c['name'] for c in inspector.get_columns("collection_items")]
            if "saved_at" not in ci_columns:
                print("Adding saved_at to collection_items...")
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(text("ALTER TABLE collection_items ADD COLUMN saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
            else:
                print("saved_at already exists in collection_items")

        # Check collections
        if inspector.has_table("collections"):
            c_columns = [c['name'] for c in inspector.get_columns("collections")]
            if "user_id" not in c_columns:
                print("Adding user_id to collections...")
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(text("ALTER TABLE collections ADD COLUMN user_id VARCHAR"))
                        conn.execute(text("CREATE INDEX ix_collections_user_id ON collections (user_id)"))
            else:
                print("user_id already exists in collections")
                
    except Exception as e:
        print(f"Error updating schema: {e}")

if __name__ == "__main__":
    add_missing_columns()
