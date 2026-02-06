from database import SessionLocal
from models import Collection

def seed_collections():
    db = SessionLocal()
    
    try:
        # Check if "History" collection exists
        history_collection = db.query(Collection).filter(Collection.title == "過去に見た雑学").first()
        
        if not history_collection:
            print("Creating 'History' collection...")
            new_collection = Collection(
                title="過去に見た雑学",
                icon="time-outline",
                is_locked=False
            )
            db.add(new_collection)
            db.commit()
            print("Created 'History' collection.")
        else:
            print("'History' collection already exists.")

        # Check if "Favorites" collection exists
        fav_collection = db.query(Collection).filter(Collection.title == "お気に入り").first()
        
        if not fav_collection:
            print("Creating 'Favorites' collection...")
            new_collection = Collection(
                title="お気に入り",
                icon="heart-outline",
                is_locked=False # For now unlocked, logic handles locking
            )
            db.add(new_collection)
            db.commit()
            print("Created 'Favorites' collection.")
        else:
            print("'Favorites' collection already exists.")
            
    except Exception as e:
        print(f"Error seeding collections: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_collections()
