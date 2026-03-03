
from fastapi import FastAPI, Depends, HTTPException, status
from typing import List, Optional
from sqlalchemy.orm import Session
from database import get_db
from models import Trivia, Collection, CollectionItem, DailyAssignment, TriviaHee
import random
import datetime
from auth import get_current_user_id, get_optional_user_id  # Added for token verification
from fastapi.responses import JSONResponse
import firebase_admin

app = FastAPI()
# Force redeploy 2

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Include Routers
from routers import user
app.include_router(user.router)

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
    date: Optional[datetime.date] = None
    
    class Config:
        from_attributes = True

class CollectionSchema(BaseModel):
    id: int
    user_id: Optional[str] = None
    title: str
    icon: str
    is_locked: bool
    count: int = 0
    
    class Config:
        from_attributes = True

@app.get("/")
def read_root():
    return {"message": "Hello from Daily Trivia Backend with Neon DB!"}

@app.get("/trivia/today", response_model=List[TriviaSchema])
def get_todays_trivia(
    user_id: str = None, 
    category: str = None, 
    limit: int = 3,
    date: str = None,
    include_assignments: bool = True,
    token_user_id: str = Depends(get_optional_user_id),
    db: Session = Depends(get_db)
):
    """
    1. Returns a tailored list of trivia based on user_id to avoid repeats.
    2. Allows 'date' to dynamically override server time.
    3. include_assignments=False prevents prepending DailyAssignments during infinite scrolling.
    """
    # Hybrid auth: prefer token-based uid, fallback to query param
    if token_user_id:
        user_id = token_user_id
    from sqlalchemy.sql import func
    
    def log(message):
        try:
            with open("backend.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now()}: {message}\n")
        except:
            pass

    try:
        # Default to Server's Effective Date if no date provided
        JST = datetime.timezone(datetime.timedelta(hours=9))
        current_time = datetime.datetime.now(JST)
        default_effective_date = (current_time - datetime.timedelta(hours=2)).date()
        
        # Parse client-provided date if available
        if date:
            try:
                effective_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                effective_date = default_effective_date
        else:
            effective_date = default_effective_date
        
        log(f"DEBUG: Requesting trivia for user_id={user_id}, category={category}, limit={limit}, include_assignments={include_assignments}")
        
        # If no user_id provided, return random trivia
        if not user_id:
            selected_trivias = db.query(Trivia).order_by(func.random()).limit(limit).all()
            for t in selected_trivias:
                t.date = effective_date
            return selected_trivias

        # 1. Check if daily assignment exists for this user and date
        assigned_trivias = []
        if not category and include_assignments:
            assignments = db.query(DailyAssignment).filter(
                DailyAssignment.user_id == user_id,
                DailyAssignment.date == effective_date
            ).all()
            
            if assignments:
                log(f"DEBUG: Found {len(assignments)} assignments.")
                # We want to maintain assignment creation order or ID order, but IN_ often loses order.
                # Since assignments is a list of objects, we can sort them, though random is fine.
                trivia_ids = [a.trivia_id for a in assignments]
                assigned_trivias = db.query(Trivia).filter(Trivia.id.in_(trivia_ids)).all()
                
                if len(assigned_trivias) >= limit:
                    for t in assigned_trivias[:limit]:
                        t.date = effective_date
                    return assigned_trivias[:limit]

        # 2. Build Subqueries for Exclusion (using NOT EXISTS for performance)
        from sqlalchemy import exists
        
        history_exists = db.query(CollectionItem.id).join(Collection).filter(
            Collection.user_id == user_id,
            Collection.title == "過去に見た雑学",
            CollectionItem.collection_id == Collection.id,
            CollectionItem.trivia_id == Trivia.id
        ).correlate(Trivia)
        
        assignments_exists = db.query(DailyAssignment.id).filter(
            DailyAssignment.user_id == user_id,
            DailyAssignment.trivia_id == Trivia.id
        ).correlate(Trivia)

        # 3. Build Main Query
        query = db.query(Trivia)
        query = query.filter(~exists(history_exists))
        query = query.filter(~exists(assignments_exists))
        
        if category:
            query = query.filter(Trivia.category == category)
            
        # 4. Fetch Random Samples
        needed_random = limit - len(assigned_trivias)
        selected_trivias = []
        if needed_random > 0:
            selected_trivias = query.order_by(func.random()).limit(needed_random).all()
        
        # Combine assigned and newly selected
        final_trivias = assigned_trivias + selected_trivias
        
        # 5. Fallback if not enough unseen
        if len(final_trivias) < limit:
            needed = limit - len(final_trivias)
            log(f"DEBUG: Not enough unseen trivia. Need {needed} more.")
            
            fallback_query = db.query(Trivia)
            if category:
                fallback_query = fallback_query.filter(Trivia.category == category)
            
            if final_trivias:
                picked_ids = [t.id for t in final_trivias]
                fallback_query = fallback_query.filter(~Trivia.id.in_(picked_ids))
            
            fillers = fallback_query.order_by(func.random()).limit(needed).all()
            final_trivias.extend(fillers)

        # 6. Save first 3 generic items as Daily Assignments for widget sync
        if not category and include_assignments:
             history_collection = db.query(Collection).filter(
                 Collection.user_id == user_id,
                 Collection.title == "過去に見た雑学"
             ).first()
             if not history_collection:
                 history_collection = Collection(
                     user_id=user_id,
                     title="過去に見た雑学",
                     icon="time-outline",
                     is_locked=False
                 )
                 db.add(history_collection)
                 db.commit()
                 db.refresh(history_collection)

             # We only create DailyAssignments for up to the first 3 items
             assignable_trivias = final_trivias[:3]
             for t in assignable_trivias:
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

                    # Also add to history since it's displayed on widget/today screen
                    history_exists = db.query(CollectionItem).filter(
                        CollectionItem.collection_id == history_collection.id,
                        CollectionItem.trivia_id == t.id
                    ).first()
                    if not history_exists:
                         db.add(CollectionItem(
                             collection_id=history_collection.id,
                             trivia_id=t.id
                         ))
             db.commit()
        
        # Inject date into response
        for t in final_trivias:
            t.date = effective_date

        return final_trivias

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        log(f"ERROR: {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/trivia/widget", response_model=List[TriviaSchema])
def get_widget_trivia(
    user_id: str = None,
    limit: int = 3,
    date: str = None,
    db: Session = Depends(get_db)
):
    """
    Endpoint for iOS Widget.
    Uses user_id as query parameter instead of Firebase token.
    Accepts optional 'date' parameter to sync with widget's local time awareness.
    Same personalization logic as /trivia/today.
    """
    from sqlalchemy.sql import func
    
    try:
        # Default to Server's Effective Date if no date provided
        JST = datetime.timezone(datetime.timedelta(hours=9))
        current_time = datetime.datetime.now(JST)
        default_effective_date = (current_time - datetime.timedelta(hours=2)).date()
        
        # Parse client-provided date if available
        if date:
            try:
                effective_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                effective_date = default_effective_date
        else:
            effective_date = default_effective_date
        
        # If no user_id provided, return random trivia
        if not user_id:
            selected_trivias = db.query(Trivia).order_by(func.random()).limit(limit).all()
            for t in selected_trivias:
                t.date = effective_date
            return selected_trivias
        
        # 1. Check if daily assignment exists for this user and date
        assignments = db.query(DailyAssignment).filter(
            DailyAssignment.user_id == user_id,
            DailyAssignment.date == effective_date
        ).all()
        
        if assignments:
            trivia_ids = [a.trivia_id for a in assignments]
            trivias = db.query(Trivia).filter(Trivia.id.in_(trivia_ids)).all()
            for t in trivias:
                t.date = effective_date
            return trivias

        # 2. Build exclusion subqueries (same as /trivia/today)
        history_subquery = db.query(CollectionItem.trivia_id).join(Collection).filter(
            Collection.user_id == user_id,
            Collection.title == "過去に見た雑学",
            CollectionItem.collection_id == Collection.id
        )
        
        assignments_subquery = db.query(DailyAssignment.trivia_id).filter(
            DailyAssignment.user_id == user_id
        )

        # 3. Query excluding seen trivia
        query = db.query(Trivia)
        query = query.filter(~Trivia.id.in_(history_subquery))
        query = query.filter(~Trivia.id.in_(assignments_subquery))
        
        selected_trivias = query.order_by(func.random()).limit(limit).all()
        
        # 4. Fallback if not enough unseen
        if len(selected_trivias) < limit:
            needed = limit - len(selected_trivias)
            fallback_query = db.query(Trivia)
            if selected_trivias:
                picked_ids = [t.id for t in selected_trivias]
                fallback_query = fallback_query.filter(~Trivia.id.in_(picked_ids))
            fillers = fallback_query.order_by(func.random()).limit(needed).all()
            selected_trivias.extend(fillers)

        # 5. Create daily assignments (same as /trivia/today)
        history_collection = db.query(Collection).filter(
            Collection.user_id == user_id,
            Collection.title == "過去に見た雑学"
        ).first()
        if not history_collection:
            history_collection = Collection(
                user_id=user_id,
                title="過去に見た雑学",
                icon="time-outline",
                is_locked=False
            )
            db.add(history_collection)
            db.commit()
            db.refresh(history_collection)

        for t in selected_trivias:
            exists = db.query(DailyAssignment).filter(
                DailyAssignment.user_id == user_id,
                DailyAssignment.date == effective_date,
                DailyAssignment.trivia_id == t.id
            ).first()
            if not exists:
                db.add(DailyAssignment(
                    user_id=user_id,
                    date=effective_date,
                    trivia_id=t.id
                ))
                history_exists = db.query(CollectionItem).filter(
                    CollectionItem.collection_id == history_collection.id,
                    CollectionItem.trivia_id == t.id
                ).first()
                if not history_exists:
                    db.add(CollectionItem(
                        collection_id=history_collection.id,
                        trivia_id=t.id
                    ))
        db.commit()
        
        for t in selected_trivias:
            t.date = effective_date

        return selected_trivias

    except Exception as e:
        import traceback
        print(f"Widget endpoint error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

class HistoryRequest(BaseModel):
    trivia_id: int

@app.get("/trivia/{trivia_id}", response_model=TriviaSchema)
def get_trivia_by_id(trivia_id: int, db: Session = Depends(get_db)):
    trivia = db.query(Trivia).filter(Trivia.id == trivia_id).first()
    if not trivia:
        raise HTTPException(status_code=404, detail="Trivia not found")
    return trivia


@app.post("/history")
def add_to_history(request: HistoryRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        # Find "History" collection for this user
        history_collection = db.query(Collection).filter(
            Collection.user_id == user_id,
            Collection.title == "過去に見た雑学"
        ).first()

        if not history_collection:
            # Should exist from get_collections, but just in case
            history_collection = Collection(
                user_id=user_id, 
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
                msg = f"{datetime.datetime.now()}: ADDED: User {user_id}, Trivia {request.trivia_id}"
                print(msg)
                with open("history_debug.log", "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except:
                pass
            return {"message": "Added to history"}
        else:
            try:
                msg = f"{datetime.datetime.now()}: DUPLICATE: User {user_id}, Trivia {request.trivia_id}"
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
                f.write(f"{datetime.datetime.now()}: ERROR: {error_msg}\n")
        except:
            pass
        print(f"Error adding to history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add to history: {str(e)}")

@app.get("/collections", response_model=List[CollectionSchema])
def get_collections(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        # Fetch collections for this user
        collections = db.query(Collection).filter(Collection.user_id == user_id).all()
        
        # Ensure default folders exist (check each individually)
        existing_titles = {c.title for c in collections}
        defaults_to_create = []
        if "過去に見た雑学" not in existing_titles:
            defaults_to_create.append(Collection(user_id=user_id, title="過去に見た雑学", icon="time-outline", is_locked=False))
        if "お気に入り" not in existing_titles:
            defaults_to_create.append(Collection(user_id=user_id, title="お気に入り", icon="heart-outline", is_locked=True))
        
        if defaults_to_create:
            db.add_all(defaults_to_create)
            db.commit()
            # Refresh to get IDs
            collections = db.query(Collection).filter(Collection.user_id == user_id).all()
        
        # Self-healing: Ensure "お気に入り" always has is_locked=True
        for col in collections:
            if col.title == "お気に入り" and not col.is_locked:
                col.is_locked = True
                db.commit()
        
        # Self-healing: Check for duplicates (same title) and merge them
        # This fixes issues where race conditions caused double default folders
        title_map = {}
        for col in collections:
            if col.title not in title_map:
                title_map[col.title] = []
            title_map[col.title].append(col)
            
        has_duplicates = False
        for title, cols in title_map.items():
            if len(cols) > 1:
                has_duplicates = True
                # Sort by ID (keep oldest)
                cols.sort(key=lambda x: x.id)
                master = cols[0]
                duplicates = cols[1:]
                
                print(f"Self-healing: Deduplicating '{title}' for user {user_id}")
                
                for dup in duplicates:
                    # Move items to master
                    dup_items = db.query(CollectionItem).filter(CollectionItem.collection_id == dup.id).all()
                    for item in dup_items:
                        exists = db.query(CollectionItem).filter(
                             CollectionItem.collection_id == master.id,
                             CollectionItem.trivia_id == item.trivia_id
                        ).first()
                        if not exists:
                            item.collection_id = master.id
                        else:
                            db.delete(item)
                    db.delete(dup)
        
        if has_duplicates:
            db.commit()
            # Fetch again after cleanup
            collections = db.query(Collection).filter(Collection.user_id == user_id).all()

        # Fast aggregate count (Fix for slow N+1 query loading)
        from sqlalchemy import func
        collection_ids = [c.id for c in collections]
        count_map = {}
        if collection_ids:
            counts = db.query(
                CollectionItem.collection_id, 
                func.count(CollectionItem.id)
            ).filter(
                CollectionItem.collection_id.in_(collection_ids)
            ).group_by(CollectionItem.collection_id).all()
            for row in counts:
                count_map[row[0]] = row[1]

        # Manually map to schema to include count
        result = []
        for c in collections:
            item_count = count_map.get(c.id, 0)
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

@app.delete("/collections/{collection_id}")
def delete_collection(collection_id: int, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    # Verify ownership
    col = db.query(Collection).filter(Collection.id == collection_id, Collection.user_id == user_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    # Prevent deleting default folders
    if col.title in ["過去に見た雑学", "お気に入り"]:
         raise HTTPException(status_code=400, detail="Default collections cannot be deleted")

    try:
        # Delete items first
        db.query(CollectionItem).filter(CollectionItem.collection_id == collection_id).delete()
        # Delete collection
        db.delete(col)
        db.commit()
        return {"message": "Collection deleted"}
    except Exception as e:
        db.rollback()
        print(f"Error deleting collection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {str(e)}")

class CreateCollectionRequest(BaseModel):
    title: str
    icon: str = "folder-outline"

@app.post("/collections", response_model=CollectionSchema)
def create_collection(request: CreateCollectionRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        new_collection = Collection(
            user_id=user_id,
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
def get_collection_items(collection_id: int, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    # Join Trivia and CollectionItem to get trivias in the collection
    # Also verify collection belongs to user
    col = db.query(Collection).filter(Collection.id == collection_id, Collection.user_id == user_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
        
    trivias = db.query(Trivia).join(CollectionItem).filter(CollectionItem.collection_id == collection_id).all()
    return trivias

class AddCollectionItemRequest(BaseModel):
    trivia_id: int

@app.post("/collections/{collection_id}/items")
def add_collection_item(collection_id: int, request: AddCollectionItemRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        # Check if collection exists and belongs to user
        collection = db.query(Collection).filter(Collection.id == collection_id, Collection.user_id == user_id).first()
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
    count: int = 1 # Number of times pressed in this batch

@app.post("/trivia/{trivia_id}/hee")
def add_hee(trivia_id: int, request: HeeRequest, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    try:
        # 1. Check if user has already hit limit for this trivia
        existing_hee = db.query(TriviaHee).filter(
            TriviaHee.user_id == user_id,
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
                user_id=user_id,
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
def get_hee_status(trivia_id: int, user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
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

# --- Cleanup Endpoint ---
@app.delete("/admin/cleanup-assignments")
def cleanup_old_assignments(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Delete DailyAssignments older than N days to prevent table bloat.
    Call periodically (e.g. weekly via external cron).
    """
    try:
        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        deleted = db.query(DailyAssignment).filter(
            DailyAssignment.date < cutoff
        ).delete()
        db.commit()
        return {"message": f"Deleted {deleted} old assignments (before {cutoff})"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
