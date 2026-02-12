from fastapi import FastAPI, Depends, HTTPException
from typing import List
from sqlalchemy.orm import Session
from database import get_db
from models import Trivia, Collection, CollectionItem

app = FastAPI()
# Force redeploy

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
    hee_count: int = 0
    
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
def get_todays_trivia(
    user_id: str, 
    limit: int = 3, 
    category: str | None = None,
    db: Session = Depends(get_db)
):
    from sqlalchemy.sql import func
    
    def log(message):
        try:
            with open("backend.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}: {message}\n")
        except:
            pass

    try:
        # Custom "Day" starts at 2:00 AM
        from datetime import timedelta
        current_time = datetime.now()
        effective_date = (current_time - timedelta(hours=2)).date()
        
        log(f"DEBUG: Requesting trivia for user_id={user_id}, category={category}, limit={limit}")
        
        # 1. Check if daily assignment exists for this user and date (ONLY if default limit=3 and no category)
        if limit == 3 and not category:
            assignments = db.query(DailyAssignment).filter(
                DailyAssignment.user_id == user_id,
                DailyAssignment.date == effective_date
            ).all()
            
            if assignments:
                log(f"DEBUG: Found {len(assignments)} assignments.")
                trivia_ids = [a.trivia_id for a in assignments]
                trivias = db.query(Trivia).filter(Trivia.id.in_(trivia_ids)).all()
                return trivias

        # 2. Build Subqueries for Exclusion
        # Use subqueries instead of fetching all IDs to memory
        
        # Subquery for history collection items
        history_subquery = db.query(CollectionItem.trivia_id).join(Collection).filter(
            Collection.user_id == user_id,
            Collection.title == "過去に見た雑学",
            CollectionItem.collection_id == Collection.id
        )
        
        # Subquery for daily assignments
        assignments_subquery = db.query(DailyAssignment.trivia_id).filter(
            DailyAssignment.user_id == user_id
        )

        # 3. Build Main Query
        query = db.query(Trivia)
        
        # Exclude seen items using NOT IN subquery
        query = query.filter(~Trivia.id.in_(history_subquery))
        query = query.filter(~Trivia.id.in_(assignments_subquery))
        
        if category:
            query = query.filter(Trivia.category == category)
            
        # 4. Fetch Random Samples using Database Random
        # order_by(func.random()) is standard for SQLite/PostgreSQL/MySQL
        # efficient enough for < 100k rows
        selected_trivias = query.order_by(func.random()).limit(limit).all()
        
        # 5. Fallback if not enough unseen
        if len(selected_trivias) < limit:
            needed = limit - len(selected_trivias)
            log(f"DEBUG: Not enough unseen trivia. Need {needed} more.")
            
            # Fallback query: Seen trivias
            fallback_query = db.query(Trivia)
            if category:
                fallback_query = fallback_query.filter(Trivia.category == category)
            
            # Exclude what we just picked
            if selected_trivias:
                picked_ids = [t.id for t in selected_trivias]
                fallback_query = fallback_query.filter(~Trivia.id.in_(picked_ids))
            
            # Randomly pick from fallback
            fillers = fallback_query.order_by(func.random()).limit(needed).all()
            selected_trivias.extend(fillers)

        # 6. Save assignments ONLY if it's the standard daily fetch
        if limit == 3 and not category:
             for t in selected_trivias:
                # Check if already assigned today (race condition check)
                exists = db.query(DailyAssignment).filter(
                    DailyAssignment.user_id == user_id,
                    DailyAssignment.date == effective_date,
                    DailyAssignment.trivia_id == t.id
                ).first()
                if not exists:
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
        raise HTTPException(status_code=500, detail=str(e))

class HistoryRequest(BaseModel):
    user_id: str
    trivia_id: int

@app.post("/history")
def add_to_history(request: HistoryRequest, db: Session = Depends(get_db)):
    try:
        # Find "History" collection for this user
        history_collection = db.query(Collection).filter(
            Collection.user_id == request.user_id,
            Collection.title == "過去に見た雑学"
        ).first()

        if not history_collection:
            # Should exist from get_collections, but just in case
            history_collection = Collection(
                user_id=request.user_id, 
                title="過去に見た雑学", 
                icon="time-outline", 
                is_locked=False
            )
            db.add(history_collection)
            db.commit()
            db.refresh(history_collection)

        # Check if already exists in history
        exists = db.query(CollectionItem).filter(
            CollectionItem.collection_id == history_collection.id,
            CollectionItem.trivia_id == request.trivia_id
        ).first()

        if not exists:
            new_item = CollectionItem(
                collection_id=history_collection.id,
                trivia_id=request.trivia_id
            )
            db.add(new_item)
            db.commit()
            try:
                msg = f"{datetime.now()}: ADDED: User {request.user_id}, Trivia {request.trivia_id}"
                print(msg)
                with open("history_debug.log", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except:
                pass
            return {"message": "Added to history"}
        else:
            try:
                msg = f"{datetime.now()}: DUPLICATE: User {request.user_id}, Trivia {request.trivia_id}"
                print(msg)
                with open("history_debug.log", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except:
                pass
            return {"message": "Already in history"}

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        try:
            with open("history_debug.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}: ERROR: {error_msg}\n")
        except:
            pass
        print(f"Error adding to history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add to history: {str(e)}")

@app.get("/collections", response_model=List[CollectionSchema])
def get_collections(user_id: str, db: Session = Depends(get_db)):
    try:
        # Fetch collections for this user
        collections = db.query(Collection).filter(Collection.user_id == user_id).all()
        
        # If no collections found for this user, create defaults
        if not collections:
            default_collections = [
                Collection(user_id=user_id, title="過去に見た雑学", icon="time-outline", is_locked=False),
                Collection(user_id=user_id, title="お気に入り", icon="heart-outline", is_locked=True) 
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
    except Exception as e:
        print(f"Error in get_collections: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch collections")

class CreateCollectionRequest(BaseModel):
    user_id: str
    title: str
    icon: str = "folder-outline"

@app.post("/collections", response_model=CollectionSchema)
def create_collection(request: CreateCollectionRequest, db: Session = Depends(get_db)):
    try:
        new_collection = Collection(
            user_id=request.user_id,
            title=request.title,
            icon=request.icon,
            is_locked=False # Custom collections are unlocked
        )
        db.add(new_collection)
        db.commit()
        db.refresh(new_collection)
        return CollectionSchema(
            id=new_collection.id,
            user_id=new_collection.user_id,
            title=new_collection.title,
            icon=new_collection.icon,
            is_locked=new_collection.is_locked,
            count=0
        )
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"Error creating collection: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Failed to create collection: {str(e)}")

@app.get("/collections/{collection_id}/items", response_model=List[TriviaSchema])
def get_collection_items(collection_id: int, db: Session = Depends(get_db)):
    # Join Trivia and CollectionItem to get trivias in the collection
    trivias = db.query(Trivia).join(CollectionItem).filter(CollectionItem.collection_id == collection_id).all()
    return trivias

class AddCollectionItemRequest(BaseModel):
    trivia_id: int

@app.post("/collections/{collection_id}/items")
def add_collection_item(collection_id: int, request: AddCollectionItemRequest, db: Session = Depends(get_db)):
    try:
        # Check if collection exists
        collection = db.query(Collection).filter(Collection.id == collection_id).first()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        # Check if already exists
        exists = db.query(CollectionItem).filter(
            CollectionItem.collection_id == collection_id,
            CollectionItem.trivia_id == request.trivia_id
        ).first()

        if exists:
             raise HTTPException(status_code=400, detail="Already in collection")
        
        new_item = CollectionItem(
            collection_id=collection_id,
            trivia_id=request.trivia_id
        )
        db.add(new_item)
        db.commit()
        return {"message": "Added to collection"}

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error adding item to collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to add item")

# --- Hee Button Endpoints ---

class HeeRequest(BaseModel):
    user_id: str
    count: int = 1 # Number of times pressed in this batch

@app.post("/trivia/{trivia_id}/hee")
def add_hee(trivia_id: int, request: HeeRequest, db: Session = Depends(get_db)):
    try:
        # 1. Check if user has already hit limit for this trivia
        existing_hee = db.query(TriviaHee).filter(
            TriviaHee.user_id == request.user_id,
            TriviaHee.trivia_id == trivia_id
        ).first()

        current_user_count = existing_hee.count if existing_hee else 0
        
        # Max 10 per user per trivia
        if current_user_count >= 10:
             return {"message": "Max limit reached", "user_count": 10, "total_count": -1} # -1 means don't update total in UI yet

        # Calculate how many we can add
        to_add = min(request.count, 10 - current_user_count)
        
        if to_add <= 0:
             return {"message": "Max limit reached", "user_count": current_user_count, "total_count": -1}

        # 2. Update user count
        if existing_hee:
            existing_hee.count += to_add
        else:
            new_hee = TriviaHee(
                user_id=request.user_id,
                trivia_id=trivia_id,
                count=to_add
            )
            db.add(new_hee)
        
        # 3. Update total count on Trivia
        trivia = db.query(Trivia).filter(Trivia.id == trivia_id).first()
        if trivia:
            trivia.hee_count = (trivia.hee_count or 0) + to_add
            total_count = trivia.hee_count
        else:
            total_count = 0

        db.commit()

        return {
            "message": "Hee added", 
            "user_count": current_user_count + to_add, 
            "total_count": total_count
        }

    except Exception as e:
        print(f"Error adding Hee: {e}")
        raise HTTPException(status_code=500, detail="Failed to add Hee")

@app.get("/trivia/{trivia_id}/hee")
def get_hee_status(trivia_id: int, user_id: str, db: Session = Depends(get_db)):
    try:
        # Get total count
        trivia = db.query(Trivia).filter(Trivia.id == trivia_id).first()
        total_count = trivia.hee_count if trivia else 0
        
        # Get user count
        user_hee = db.query(TriviaHee).filter(
            TriviaHee.user_id == user_id,
            TriviaHee.trivia_id == trivia_id
        ).first()
        user_count = user_hee.count if user_hee else 0
        
        return {
            "total_count": total_count,
            "user_count": user_count
        }
    except Exception as e:
        print(f"Error getting Hee status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get Hee status")

