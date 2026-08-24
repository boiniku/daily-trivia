
from fastapi import FastAPI, Depends, HTTPException, status, Request, Query
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, case, func, or_
from database import get_db, AppSessionLocal
from models import Trivia, MapTrivia, Collection, CollectionItem, DailyAssignment, TriviaHee
import random
import datetime
import os
from auth import get_current_user_id, get_optional_user_id  # Added for token verification
from fastapi.responses import JSONResponse
import firebase_admin

# --- RLS-aware DB session dependencies ---
def get_rls_db(user_id: str):
    """
    Creates a DB session that sets app.current_user_id for RLS enforcement.
    """
    db = AppSessionLocal()
    try:
        if user_id:
            db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
        yield db
    finally:
        db.close()

def get_rls_db_for_auth_user(user_id: str = Depends(get_current_user_id)):
    """RLS DB session for authenticated endpoints."""
    db = AppSessionLocal()
    try:
        db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
        yield db
    finally:
        db.close()

app = FastAPI()
# Force redeploy 2


@app.on_event("startup")
def ensure_admin_schema():
    # Keep admin workflow columns in sync even when the hosting service uses
    # a manually configured start command instead of render.yaml.
    from scripts.migrations.migrate_trivia_candidates import migrate
    migrate()

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
from routers import line_admin
app.include_router(line_admin.router)
from routers import daily_collection
app.include_router(daily_collection.router)
from routers import social_automation
app.include_router(social_automation.router)

# Pydantic Schemas
from pydantic import BaseModel
try:
    from pydantic import field_validator
except ImportError:
    field_validator = None
try:
    from pydantic import validator
except ImportError:
    validator = None

TRIVIA_IMAGE_R2_BASE_URL = os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip().rstrip("/")
MINIMUM_SUPPORTED_APP_VERSION = os.getenv("MINIMUM_SUPPORTED_APP_VERSION", "1.0.5").strip()
LATEST_APP_VERSION = os.getenv("LATEST_APP_VERSION", "1.0.5").strip()
APP_STORE_URL = os.getenv("APP_STORE_URL", "https://apps.apple.com/app/id6758872525").strip()
APP_ENV = os.getenv("APP_ENV", "production").strip()
API_VERSION = "1"


def build_trivia_image_url(raw_value: Optional[str]) -> Optional[str]:
    value = (raw_value or "").strip()
    if not value:
        return None
    if value.startswith(("http://", "https://", "data:")):
        return value
    if not TRIVIA_IMAGE_R2_BASE_URL:
        return value
    return f"{TRIVIA_IMAGE_R2_BASE_URL}/{value.lstrip('/')}"

class TriviaSchema(BaseModel):
    id: int
    title: str
    content: str
    explanation: str
    source: str
    category: str
    image_url: Optional[str] = None
    hee_count: int = 0
    date: Optional[datetime.date] = None

    if field_validator:
        @field_validator("image_url", mode="before")
        @classmethod
        def normalize_image_url(cls, value):
            return build_trivia_image_url(value)
    elif validator:
        @validator("image_url", pre=True, always=True)
        def normalize_image_url(cls, value):
            return build_trivia_image_url(value)
    
    class Config:
        from_attributes = True

class CollectionItemSchema(TriviaSchema):
    user_hee_count: int = 0


class CollectionItemsSearchResponse(BaseModel):
    items: List[CollectionItemSchema]
    total: int
    has_more: bool
    categories: List[str]


class CollectionSchema(BaseModel):
    id: int
    user_id: Optional[str] = None
    title: str
    icon: str
    is_locked: bool
    count: int = 0
    
    class Config:
        from_attributes = True


class TriviaMapSpotSchema(BaseModel):
    id: str
    title: str
    description: str
    explanation: str
    latitude: float
    longitude: float
    unlockRadiusMeters: int
    isUnlocked: bool = False
    unlockedAt: Optional[datetime.datetime] = None
    prefecture: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    hint: Optional[str] = None

@app.get("/")
def read_root():
    return {"message": "Hello from Daily Trivia Backend with Neon DB!"}


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "environment": APP_ENV,
        "api_version": API_VERSION,
        # Render supplies this value at runtime. It lets the release workflow
        # prove that the exact reviewed commit is serving production traffic.
        "release_commit": os.getenv("RENDER_GIT_COMMIT", "").strip(),
    }


@app.get("/app/version")
def get_app_version():
    return {
        "minimum_supported_version": MINIMUM_SUPPORTED_APP_VERSION,
        "latest_version": LATEST_APP_VERSION,
        "app_store_url": APP_STORE_URL,
        "environment": APP_ENV,
        "api_version": API_VERSION,
    }


@app.get("/trivia/map", response_model=List[TriviaMapSpotSchema])
def get_map_trivia(db: Session = Depends(get_db)):
    items = (
        db.query(MapTrivia)
        .order_by(MapTrivia.id.desc())
        .all()
    )
    return [
        {
            "id": f"map_{item.id}",
            "title": item.title,
            "description": item.content,
            "explanation": item.explanation or "",
            "latitude": float(item.map_latitude),
            "longitude": float(item.map_longitude),
            "unlockRadiusMeters": int(item.map_radius or 500),
            "isUnlocked": False,
            "unlockedAt": None,
            "prefecture": item.map_prefecture,
            "address": item.map_address,
            "category": item.category,
            "hint": item.map_hint or "",
        }
        for item in items
    ]

@app.get("/trivia/today", response_model=List[TriviaSchema])
def get_todays_trivia(
    user_id: str = None, 
    category: str = None, 
    limit: int = 3,
    date: str = None,
    include_assignments: bool = True,
    token_user_id: str = Depends(get_optional_user_id),
):
    """
    1. Returns a tailored list of trivia based on user_id to avoid repeats.
    2. Allows 'date' to dynamically override server time.
    3. include_assignments=False prevents prepending DailyAssignments during infinite scrolling.
    """
    # Hybrid auth: prefer token-based uid, fallback to query param
    if token_user_id:
        user_id = token_user_id
    
    # Create RLS-aware DB session with the resolved user_id
    from sqlalchemy.sql import func
    db = AppSessionLocal()

    def log(message):
        try:
            with open("backend.log", "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now()}: {message}\n")
        except:
            pass

    try:
        if user_id:
            db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})

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
                trivia_ids = [a.trivia_id for a in assignments]
                assigned_trivias = db.query(Trivia).filter(Trivia.id.in_(trivia_ids)).all()
                
                if len(assigned_trivias) >= limit:
                    for t in assigned_trivias[:limit]:
                        t.date = effective_date
                    return assigned_trivias[:limit]

        # 2. Build Subqueries for Exclusion
        history_subquery = db.query(CollectionItem.trivia_id).join(Collection).filter(
            Collection.user_id == user_id,
            Collection.title == "過去に見た雑学",
            CollectionItem.collection_id == Collection.id
        ).subquery()
        
        assignments_subquery = db.query(DailyAssignment.trivia_id).filter(
            DailyAssignment.user_id == user_id
        ).subquery()

        # 3. Build Main Query
        query = db.query(Trivia)
        query = query.filter(~Trivia.id.in_(db.query(history_subquery)))
        query = query.filter(~Trivia.id.in_(db.query(assignments_subquery)))
        
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
                 # Keep the RLS context and all related writes in one transaction.
                 # SET LOCAL is cleared by commit, which made this collection
                 # invisible to app_user during the following refresh/query.
                 db.flush()

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
        db.rollback()
        error_msg = traceback.format_exc()
        log(f"ERROR: {error_msg}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

@app.get("/trivia/widget", response_model=List[TriviaSchema])
def get_widget_trivia(
    user_id: str = None,
    limit: int = 3,
    date: str = None,
):
    """
    Endpoint for iOS Widget.
    Uses user_id as query parameter instead of Firebase token.
    Accepts optional 'date' parameter to sync with widget's local time awareness.
    Same personalization logic as /trivia/today.
    """
    from sqlalchemy.sql import func
    
    # Create RLS-aware DB session
    db = AppSessionLocal()
    try:
        if user_id:
            db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})

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
            # Keep SET LOCAL app.current_user_id active until assignments and
            # history items have been written in the same transaction.
            db.flush()

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
        db.rollback()
        print(f"Widget endpoint error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()

class HistoryRequest(BaseModel):
    trivia_id: int

@app.get("/trivia/{trivia_id}", response_model=TriviaSchema)
def get_trivia_by_id(trivia_id: int):
    db = AppSessionLocal()
    try:
        trivia = db.query(Trivia).filter(Trivia.id == trivia_id).first()
        if not trivia:
            raise HTTPException(status_code=404, detail="Trivia not found")
        return trivia
    finally:
        db.close()


@app.post("/history")
def add_to_history(request: HistoryRequest, user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
    finally:
        db.close()

@app.get("/collections", response_model=List[CollectionSchema])
def get_collections(user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
    finally:
        db.close()

@app.delete("/collections/{collection_id}")
def delete_collection(collection_id: int, user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
    finally:
        db.close()

class CreateCollectionRequest(BaseModel):
    title: str
    icon: str = "folder-outline"

@app.post("/collections", response_model=CollectionSchema)
def create_collection(request: CreateCollectionRequest, user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
    finally:
        db.close()

def escape_like(value: str) -> str:
    """Treat %, _ and backslash as ordinary search characters."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get(
    "/collections/{collection_id}/items/search",
    response_model=CollectionItemsSearchResponse,
)
def search_collection_items(
    collection_id: int,
    q: str = Query(default="", max_length=100),
    category: Optional[str] = Query(default=None, max_length=100),
    sort: str = Query(default="default", pattern="^(default|total|user)$"),
    limit: int = Query(default=30, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    user_id: str = Depends(get_current_user_id),
):
    """Search one user's collection without loading its entire history."""
    db = AppSessionLocal()
    try:
        db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
        collection = db.query(Collection).filter(
            Collection.id == collection_id,
            Collection.user_id == user_id,
        ).first()
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")

        tokens = q.strip().split()[:5]

        def add_filters(query):
            query = query.filter(CollectionItem.collection_id == collection_id)
            if category:
                query = query.filter(Trivia.category == category)
            for token in tokens:
                pattern = f"%{escape_like(token)}%"
                query = query.filter(or_(
                    Trivia.title.ilike(pattern, escape="\\"),
                    Trivia.content.ilike(pattern, escape="\\"),
                    Trivia.explanation.ilike(pattern, escape="\\"),
                    Trivia.category.ilike(pattern, escape="\\"),
                ))
            return query

        user_hee = db.query(
            TriviaHee.trivia_id.label("trivia_id"),
            func.max(TriviaHee.count).label("count"),
        ).filter(
            TriviaHee.user_id == user_id,
        ).group_by(
            TriviaHee.trivia_id,
        ).subquery()

        result_query = db.query(
            Trivia,
            func.coalesce(user_hee.c.count, 0).label("user_hee_count"),
        ).join(
            CollectionItem, Trivia.id == CollectionItem.trivia_id,
        ).outerjoin(
            user_hee, Trivia.id == user_hee.c.trivia_id,
        )
        result_query = add_filters(result_query)

        total_query = db.query(func.count(CollectionItem.id)).join(
            Trivia, Trivia.id == CollectionItem.trivia_id,
        )
        total = int(add_filters(total_query).scalar() or 0)

        if tokens:
            normalized_query = " ".join(tokens)
            escaped_query = escape_like(normalized_query)
            relevance = case(
                (func.lower(Trivia.title) == normalized_query.lower(), 0),
                (Trivia.title.ilike(f"{escaped_query}%", escape="\\"), 1),
                (Trivia.title.ilike(f"%{escaped_query}%", escape="\\"), 2),
                else_=3,
            )
            result_query = result_query.order_by(relevance.asc())

        if sort == "total":
            result_query = result_query.order_by(Trivia.hee_count.desc(), CollectionItem.id.desc())
        elif sort == "user":
            result_query = result_query.order_by(
                func.coalesce(user_hee.c.count, 0).desc(),
                CollectionItem.id.desc(),
            )
        else:
            result_query = result_query.order_by(CollectionItem.id.desc())

        results = result_query.offset(offset).limit(limit).all()
        items = []
        for trivia, user_hee_count in results:
            item = {column.name: getattr(trivia, column.name) for column in trivia.__table__.columns}
            item["user_hee_count"] = int(user_hee_count or 0)
            items.append(item)

        categories = [row[0] for row in db.query(Trivia.category).join(
            CollectionItem, Trivia.id == CollectionItem.trivia_id,
        ).filter(
            CollectionItem.collection_id == collection_id,
            Trivia.category.isnot(None),
            Trivia.category != "",
        ).distinct().order_by(Trivia.category.asc()).all()]

        return {
            "items": items,
            "total": total,
            "has_more": offset + len(items) < total,
            "categories": categories,
        }
    finally:
        db.close()


@app.get("/collections/{collection_id}/items", response_model=List[CollectionItemSchema])
def get_collection_items(collection_id: int, user_id: str = Depends(get_current_user_id)):
    from sqlalchemy import func, and_
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
    # Join Trivia and CollectionItem to get trivias in the collection
    # Also verify collection belongs to user
    col = db.query(Collection).filter(Collection.id == collection_id, Collection.user_id == user_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Collection not found")
        
    results = db.query(
        Trivia,
        func.coalesce(TriviaHee.count, 0).label('user_hee_count')
    ).join(
        CollectionItem, Trivia.id == CollectionItem.trivia_id
    ).outerjoin(
        TriviaHee, and_(Trivia.id == TriviaHee.trivia_id, TriviaHee.user_id == user_id)
    ).filter(
        CollectionItem.collection_id == collection_id
    ).order_by(CollectionItem.id.desc()).all()
    
    trivias_with_hee = []
    for trivia, user_hee_count in results:
        t_dict = {c.name: getattr(trivia, c.name) for c in trivia.__table__.columns}
        t_dict['user_hee_count'] = user_hee_count
        trivias_with_hee.append(t_dict)

    db.close()
    return trivias_with_hee

class AddCollectionItemRequest(BaseModel):
    trivia_id: int

@app.post("/collections/{collection_id}/items")
def add_collection_item(collection_id: int, request: AddCollectionItemRequest, user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
    finally:
        db.close()

# --- Hee Button Endpoints ---

class HeeRequest(BaseModel):
    count: int = 1 # Number of times pressed in this batch

@app.post("/trivia/{trivia_id}/hee")
def add_hee(trivia_id: int, request: HeeRequest, user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
        
        # 3. Update total count via SECURITY DEFINER function (app_user can't UPDATE trivia directly)
        result = db.execute(
            text("SELECT increment_hee_count(:tid, :amt)"),
            {"tid": trivia_id, "amt": to_add}
        )
        total_count = result.scalar() or 0

        db.commit()

        return {
            "message": "Hee added", 
            "user_count": current_user_count + to_add, 
            "total_count": total_count
        }

    except Exception as e:
        print(f"Error adding Hee: {e}")
        raise HTTPException(status_code=500, detail="Failed to add Hee")
    finally:
        db.close()

@app.get("/trivia/{trivia_id}/hee")
def get_hee_status(trivia_id: int, user_id: str = Depends(get_current_user_id)):
    db = AppSessionLocal()
    db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})
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
    finally:
        db.close()

# --- Cleanup Endpoint ---
@app.delete("/admin/cleanup-assignments")
def cleanup_old_assignments(
    days: int = 30,
):
    """
    Delete DailyAssignments older than N days to prevent table bloat.
    Call periodically (e.g. weekly via external cron).
    """
    # Admin endpoint uses owner connection (bypasses RLS)
    from database import SessionLocal
    db = SessionLocal()
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
    finally:
        db.close()
