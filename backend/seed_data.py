import json
from database import SessionLocal
from models import Trivia

def seed_data():
    db = SessionLocal()
    
    try:
        # Load JSON data
        with open("data_50.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            
        print(f"Found {len(data)} items in JSON file.")
        
        count = 0
        for item in data:
            # Check if title already exists to prevent duplicates
            exists = db.query(Trivia).filter(Trivia.title == item["title"]).first()
            if not exists:
                new_trivia = Trivia(
                    title=item["title"],
                    content=item["content"],
                    explanation=item["explanation"],
                    source=item["source"],
                    category=item["category"]
                )
                db.add(new_trivia)
                count += 1
        
        db.commit()
        print(f"Successfully added {count} new trivia items!")
        
    except Exception as e:
        print(f"Error seeding data: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
