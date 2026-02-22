
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
import sys
import os
from typing import List

# Add parent directory to path to import models and database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db
from models import TriviaHee, Collection, CollectionItem, DailyAssignment
from auth import get_current_user_id

router = APIRouter()

class MergeRequest(BaseModel):
    guest_user_id: str

@router.post("/auth/merge")
def merge_guest_data(request: MergeRequest, auth_user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """
    Merge guest data into authenticated user account.
    """
    guest_id = request.guest_user_id
    auth_id = auth_user_id
    
    if not guest_id or not auth_id:
        raise HTTPException(status_code=400, detail="Both guest_user_id and auth_user_id are required")
        
    if guest_id == auth_id:
        return {"message": "Same user ID, nothing to merge"}

    try:
        # 1. Merge TriviaHee (Hees)
        # Get all guest hees
        guest_hees = db.query(TriviaHee).filter(TriviaHee.user_id == guest_id).all()
        for g_hee in guest_hees:
            # Check if auth user already has hee for this trivia
            auth_hee = db.query(TriviaHee).filter(
                TriviaHee.user_id == auth_id, 
                TriviaHee.trivia_id == g_hee.trivia_id
            ).first()
            
            if auth_hee:
                # Merge counts (max 10)
                new_total = min(auth_hee.count + g_hee.count, 10)
                auth_hee.count = new_total
                # Delete guest record
                db.delete(g_hee)
            else:
                # specific update
                g_hee.user_id = auth_id
        
        # 2. Merge Collections ("History", "Favorites", Custom)
        # Title normalization map (English -> Japanese)
        TITLE_MAP = {
            "History": "過去に見た雑学",
            "Favorites": "お気に入り"
        }

        # Get all guest collections
        guest_collections = db.query(Collection).filter(Collection.user_id == guest_id).all()
        
        for g_col in guest_collections:
            # Determine target title
            target_title = TITLE_MAP.get(g_col.title, g_col.title)
            
            # Check if auth user has collection with same target title
            auth_col = db.query(Collection).filter(
                Collection.user_id == auth_id,
                Collection.title == target_title
            ).first()
            
            if auth_col:
                # Merge items from guest collection to auth collection
                # Get guest items
                g_items = db.query(CollectionItem).filter(CollectionItem.collection_id == g_col.id).all()
                for g_item in g_items:
                    # Check if item already exists in auth collection
                    exists = db.query(CollectionItem).filter(
                        CollectionItem.collection_id == auth_col.id,
                        CollectionItem.trivia_id == g_item.trivia_id
                    ).first()
                    
                    if not exists:
                        # Move item to auth collection
                        g_item.collection_id = auth_col.id
                    else:
                        # Duplicate, delete guest item
                        db.delete(g_item)
                
                # Delete guest collection after merging items
                db.delete(g_col)
            else:
                # No conflict, just transfer ownership
                # Also normalize title if needed (e.g. rename "History" to "過去に見た雑学")
                if g_col.title != target_title:
                    g_col.title = target_title
                g_col.user_id = auth_id

        # 3. Merge Daily Assignments
        # Just update user_id. If duplicate, we effectively ignore (allow double assignment logic-wise or unique constraint fails)
        # Since standard flow has no unique constraint on DB level for (user, date, trivia), we simple update.
        # But to be clean, let's delete guest assignment if auth already has same assignment.
        guest_assignments = db.query(DailyAssignment).filter(DailyAssignment.user_id == guest_id).all()
        for g_assign in guest_assignments:
            auth_assign = db.query(DailyAssignment).filter(
                DailyAssignment.user_id == auth_id,
                DailyAssignment.date == g_assign.date,
                DailyAssignment.trivia_id == g_assign.trivia_id
            ).first()
            
            if auth_assign:
                db.delete(g_assign)
            else:
                g_assign.user_id = auth_id

        # 4. Deduplicate Collections (Fix for Race Condition)
        # If get_collections created defaults while we were merging, we might have duplicates now.
        # Strategy: Group by Title. Keep one, merge items from others, delete others.
        
        # Refresh to see all collections for auth_user (including just moved ones)
        db.flush() 
        all_cols = db.query(Collection).filter(Collection.user_id == auth_id).all()
        
        title_map = {}
        for col in all_cols:
            if col.title not in title_map:
                title_map[col.title] = []
            title_map[col.title].append(col)
            
        for title, cols in title_map.items():
            if len(cols) > 1:
                # prefer the one that was already "auth" or just the first one
                # sort by ID (keep oldest)
                cols.sort(key=lambda x: x.id)
                master = cols[0]
                duplicates = cols[1:]
                
                print(f"Deduplicating '{title}': Keeping {master.id}, merging {len(duplicates)} dups")

                for dup in duplicates:
                    dup_items = db.query(CollectionItem).filter(CollectionItem.collection_id == dup.id).all()
                    for item in dup_items:
                        # Check existence in master
                        exists = db.query(CollectionItem).filter(
                            CollectionItem.collection_id == master.id,
                            CollectionItem.trivia_id == item.trivia_id
                        ).first()
                        
                        if not exists:
                            item.collection_id = master.id
                        else:
                            db.delete(item)
                    
                    # Delete duplicate collection
                    db.delete(dup)

        db.commit()
        return {"message": "Merge successful"}

    except Exception as e:
        db.rollback()
        print(f"Merge error: {e}")
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}")

@router.delete("/auth/user")
def delete_user(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """
    Delete all data associated with a user.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        # 1. Delete DailyAssignments
        db.query(DailyAssignment).filter(DailyAssignment.user_id == user_id).delete()

        # 2. Delete TriviaHee
        db.query(TriviaHee).filter(TriviaHee.user_id == user_id).delete()

        # 3. Delete Collections and Items
        collections = db.query(Collection).filter(Collection.user_id == user_id).all()
        for col in collections:
            db.query(CollectionItem).filter(CollectionItem.collection_id == col.id).delete()
            db.delete(col)

        db.commit()
        return {"message": "User data deleted successfully"}

    except Exception as e:
        db.rollback()
        print(f"Delete user error: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
