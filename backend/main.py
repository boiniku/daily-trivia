from fastapi import FastAPI, Depends, HTTPException
from typing import List
from sqlalchemy.orm import Session
from database import get_db
from models import Trivia, Collection, CollectionItem

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Pydantic Schemas
from pydantic import BaseModel

class TriviaSchema(BaseModel):
    id: int
    title: str
    content: str
    explanation: str
    source: str
    category: str
    
    class Config:
        from_attributes = True

class CollectionSchema(BaseModel):
    id: int
    user_id: str | None = None
    title: str
    icon: str
    is_locked: bool
    count: int = 0
    
    class Config:
        from_attributes = True

@app.get("/")
def read_root():
    return {"message": "Hello from Daily Trivia Backend with Neon DB!"}

import random
from datetime import date, datetime
from models import Trivia, Collection, CollectionItem, DailyAssignment

@app.get("/trivia/today", response_model=List[TriviaSchema])
def get_todays_trivia(user_id: str, db: Session = Depends(get_db)):
    def log(message):
        try:
            with open("backend.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}: {message}\n")
        except:
            pass

    try:
        # Custom "Day" starts at 2:00 AM
        # If current time is before 2:00 AM, it counts as the previous day.
        from datetime import timedelta
        current_time = datetime.now()
        effective_date = (current_time - timedelta(hours=2)).date()
        
        log(f"DEBUG: Requesting trivia for user_id={user_id}, effective_date={effective_date} (raw: {current_time})")
        
        # 1. Check if daily assignment exists for this user and date
        assignments = db.query(DailyAssignment).filter(
            DailyAssignment.user_id == user_id,
            DailyAssignment.date == effective_date
        ).all()
        
        if assignments:
            log(f"DEBUG: Found {len(assignments)} assignments.")
            # Return assigned logic
            trivia_ids = [a.trivia_id for a in assignments]
            trivias = db.query(Trivia).filter(Trivia.id.in_(trivia_ids)).all()
            return trivias

        # 2. Get IDs of trivia already in "History" collection for THIS USER
        # Find user's history collection
        history_collection = db.query(Collection).filter(
            Collection.user_id == user_id, 
            Collection.title == "過去に見た雑学"
        ).first()
        
        seen_ids = []
        if history_collection:
            seen_items = db.query(CollectionItem.trivia_id).filter(
                CollectionItem.collection_id == history_collection.id
            ).all()
            seen_ids = [item.trivia_id for item in seen_items]
        
        # Also check past daily assignments to avoid repetition
        past_assignments = db.query(DailyAssignment.trivia_id).filter(
            DailyAssignment.user_id == user_id
        ).all()
        seen_ids.extend([p.trivia_id for p in past_assignments])
        seen_ids = list(set(seen_ids)) # Unique
        
        log(f"DEBUG: Seen IDs: {seen_ids}")
        
        # Query trivias NOT in seen_ids
        if seen_ids:
            query = db.query(Trivia).filter(~Trivia.id.in_(seen_ids))
        else:
            query = db.query(Trivia)
            
        total_count = query.count()
        log(f"DEBUG: Available trivias: {total_count}")
        
        # Fallback if all seen
        if total_count < 3:
            all_trivias = db.query(Trivia).all()
            if not all_trivias:
                return []
            selected_trivias = random.sample(all_trivias, min(len(all_trivias), 3))
        else:
            # Select 3 random IDs from unseen
            candidate_ids = [t.id for t in query.with_entities(Trivia.id).all()]
            selected_ids = random.sample(candidate_ids, 3)
            selected_trivias = db.query(Trivia).filter(Trivia.id.in_(selected_ids)).all()
        
        # 3. Save assignments
        for t in selected_trivias:
            new_assignment = DailyAssignment(
                user_id=user_id,
                date=effective_date,
                trivia_id=t.id
            )
            db.add(new_assignment)
        db.commit()
        
        return selected_trivias
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        log(f"ERROR: {error_msg}")
        print(error_msg)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/collections", response_model=List[CollectionSchema])
def get_collections(user_id: str, db: Session = Depends(get_db)):
    # Fetch collections for this user
    collections = db.query(Collection).filter(Collection.user_id == user_id).all()
    
    # If no collections found for this user, create defaults
    if not collections:
        default_collections = [
            Collection(user_id=user_id, title="過去に見た雑学", icon="time-outline", is_locked=False),
            Collection(user_id=user_id, title="お気に入り", icon="heart-outline", is_locked=True) 
            # Note: Favorites logic might change, kept locked per prev implementation, 
            # now maybe unlocked or locked depending on plan. Keeping as is.
        ]
        db.add_all(default_collections)
        db.commit()
        # Refresh to get IDs
        collections = db.query(Collection).filter(Collection.user_id == user_id).all()

    # Manually map to schema to include count
    result = []
    for c in collections:
        item_count = db.query(CollectionItem).filter(CollectionItem.collection_id == c.id).count()
        result.append(CollectionSchema(
            id=c.id,
            user_id=c.user_id,
            title=c.title,
            icon=c.icon,
            is_locked=c.is_locked,
            count=item_count
        ))
    return result

class AddHistoryRequest(BaseModel):
    user_id: str
    trivia_id: int

@app.post("/history")
def add_to_history(request: AddHistoryRequest, db: Session = Depends(get_db)):
    # Find list "History" for this user
    # Ensure collections exist (in case user swipes before visiting collections tab)
    history_collection = db.query(Collection).filter(
        Collection.user_id == request.user_id, 
        Collection.title == "過去に見た雑学"
    ).first()
    
    if not history_collection:
        # Create defaults if not exist
        history_collection = Collection(user_id=request.user_id, title="過去に見た雑学", icon="time-outline", is_locked=False)
        fav_collection = Collection(user_id=request.user_id, title="お気に入り", icon="heart-outline", is_locked=True)
        db.add(history_collection)
        db.add(fav_collection)
        db.commit()
        db.refresh(history_collection)
    
    # Check if already exists
    exists = db.query(CollectionItem).filter(
        CollectionItem.collection_id == history_collection.id,
        CollectionItem.trivia_id == request.trivia_id
    ).first()
    
    if exists:
        return {"message": "Already in history"}
    
    new_item = CollectionItem(
        collection_id=history_collection.id,
        trivia_id=request.trivia_id
    )
    db.add(new_item)
    db.commit()
    return {"message": "Added to history"}

@app.get("/collections/{collection_id}/items", response_model=List[TriviaSchema])
def get_collection_items(collection_id: int, db: Session = Depends(get_db)):
    # Join Trivia and CollectionItem to get trivias in the collection
    trivias = db.query(Trivia).join(CollectionItem).filter(CollectionItem.collection_id == collection_id).all()
    return trivias

