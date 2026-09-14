
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import sys
import os
import datetime
from typing import List
from firebase_admin import auth as firebase_auth

# Add parent directory to path to import models and database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import AppSessionLocal
from sqlalchemy import text
from models import AccountLifecycle, TriviaHee, MapTriviaUnlock, Collection, CollectionItem, DailyAssignment
from auth import get_current_user_id, get_deletion_user_id, verify_token
from services.account_lifecycle import lock_accounts, require_active_account

router = APIRouter()

class MergeRequest(BaseModel):
    guest_id_token: str

class LegacyMergeRequest(BaseModel):
    guest_user_id: str


class PrepareMergeRequest(BaseModel):
    apple_subject: str = Field(min_length=1, max_length=255)


def apple_subject_for(user_id):
    try:
        account = firebase_auth.get_user(user_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Unable to verify Apple account")
    for provider in account.provider_data:
        if provider.provider_id == "apple.com":
            return provider.uid
    raise HTTPException(status_code=403, detail="An Apple-linked destination is required")


@router.post("/auth/merge/prepare")
def prepare_guest_merge(request: PrepareMergeRequest, claims: dict = Depends(verify_token)):
    """Persist source consent before auth switches; no saved bearer credentials."""
    guest_id = claims.get("uid")
    if not guest_id or (claims.get("firebase") or {}).get("sign_in_provider") != "anonymous":
        raise HTTPException(status_code=403, detail="Anonymous source authentication required")
    from database import SessionLocal
    with SessionLocal() as db:
        state = require_active_account(db, guest_id)
        if state is None:
            state = AccountLifecycle(user_id=guest_id, status="active")
            db.add(state)
        state.merge_apple_subject = request.apple_subject
        db.commit()
    return {"prepared": True}


@router.post("/auth/merge/pending")
def finish_pending_merges(auth_user_id: str = Depends(get_current_user_id)):
    subject = apple_subject_for(auth_user_id)
    from database import SessionLocal
    with SessionLocal() as db:
        source_ids = [row.user_id for row in db.query(AccountLifecycle).filter(
            AccountLifecycle.merge_apple_subject == subject,
            AccountLifecycle.status.in_(["active", "merged"]),
        ).all() if row.user_id != auth_user_id and row.merged_into in (None, auth_user_id)]
    for guest_id in source_ids:
        _merge_guest_data(guest_id, auth_user_id, expected_apple_subject=subject)
    return {"merged_guest_ids": source_ids}


@router.post("/auth/merge/verified")
def merge_verified_guest_data(request: MergeRequest, auth_user_id: str = Depends(get_current_user_id)):
    """
    Merge guest data into authenticated user account.
    """
    try:
        guest_claims = firebase_auth.verify_id_token(request.guest_id_token, check_revoked=True)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid guest authentication token")

    guest_id = guest_claims.get("uid")
    sign_in_provider = (guest_claims.get("firebase") or {}).get("sign_in_provider")
    if not guest_id or sign_in_provider != "anonymous":
        raise HTTPException(
            status_code=400,
            detail="The merge token must belong to an anonymous Firebase user",
        )
    apple_subject_for(auth_user_id)
    return _merge_guest_data(guest_id, auth_user_id)


@router.post("/auth/merge")
def merge_legacy_guest_data(
    request: LegacyMergeRequest,
    auth_user_id: str = Depends(get_current_user_id),
    app_version: str | None = Header(default=None, alias="X-Daily-Trivia-App-Version"),
):
    """Temporary, constrained bridge for the already-distributed 1.1.0 app.

    That client cannot present its former anonymous token after Apple sign-in.
    Keep compatibility only for the exact old release and only until the
    configured deadline. New clients use the proof-bearing prepare flow.
    """
    if app_version != "1.1.0":
        raise HTTPException(status_code=410, detail="Verified migration required; update the app")
    if os.getenv("LEGACY_GUEST_MERGE_ENABLED", "true").lower() != "true":
        raise HTTPException(status_code=410, detail="Legacy migration is disabled; update the app")

    deadline_text = os.getenv(
        "LEGACY_GUEST_MERGE_DEADLINE",
        "2026-10-31T00:00:00+00:00",
    )
    try:
        deadline = datetime.datetime.fromisoformat(deadline_text)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise HTTPException(status_code=500, detail="Invalid legacy merge deadline")
    if datetime.datetime.now(datetime.timezone.utc) >= deadline:
        raise HTTPException(status_code=410, detail="Legacy migration has expired; update the app")

    # The destination token is already authenticated; additionally require it
    # to be linked to Apple and require the source still to be a pure anonymous
    # Firebase identity. This cannot add proof absent from 1.1.0, but prevents
    # moving registered accounts and keeps the compatibility window bounded.
    apple_subject_for(auth_user_id)
    try:
        source = firebase_auth.get_user(request.guest_user_id)
    except Exception:
        raise HTTPException(status_code=403, detail="Anonymous source account could not be verified")
    if (
        getattr(source, "disabled", False)
        or list(getattr(source, "provider_data", []) or [])
        or getattr(source, "email", None)
        or getattr(source, "phone_number", None)
    ):
        raise HTTPException(status_code=403, detail="Legacy source must be an anonymous account")
    return _merge_guest_data(request.guest_user_id, auth_user_id)


def _merge_guest_data(guest_id: str, auth_id: str, expected_apple_subject=None):
    
    if not guest_id or not auth_id:
        raise HTTPException(status_code=400, detail="Both guest and authenticated user IDs are required")
        
    if guest_id == auth_id:
        return {"message": "Same user ID, nothing to merge"}

    # Use admin connection for merge (needs access to both guest and auth user data)
    from database import SessionLocal
    db = SessionLocal()
    try:
        lock_accounts(db, guest_id, auth_id)
        require_active_account(db, auth_id)
        state = db.get(AccountLifecycle, guest_id)
        if expected_apple_subject and (not state or state.merge_apple_subject != expected_apple_subject):
            raise HTTPException(status_code=403, detail="Migration destination does not match")
        if state and state.status != "active":
            if state.status == "merged" and state.merged_into == auth_id:
                return {"message": "Merge successful"}
            raise HTTPException(status_code=409, detail="Source account is no longer transferable")
        if state is None:
            state = AccountLifecycle(user_id=guest_id, status="active")
            db.add(state)
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

        # 2. Merge map unlocks. Preserve the earliest collection timestamp and
        # never let account linking discard an unlock already owned by either ID.
        guest_unlocks = db.query(MapTriviaUnlock).filter(
            MapTriviaUnlock.user_id == guest_id
        ).all()
        for guest_unlock in guest_unlocks:
            auth_unlock = db.query(MapTriviaUnlock).filter(
                MapTriviaUnlock.user_id == auth_id,
                MapTriviaUnlock.map_trivia_id == guest_unlock.map_trivia_id,
            ).first()
            if auth_unlock:
                auth_unlock.unlocked_at = min(
                    auth_unlock.unlocked_at,
                    guest_unlock.unlocked_at,
                )
                db.delete(guest_unlock)
            else:
                guest_unlock.user_id = auth_id
        
        # 3. Merge Collections ("History", "Favorites", Custom)
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
                
                # Flush moves before relationship cleanup (production autoflush=False).
                db.flush()
                # Delete guest collection after merging items
                db.delete(g_col)
            else:
                # No conflict, just transfer ownership
                # Also normalize title if needed (e.g. rename "History" to "過去に見た雑学")
                if g_col.title != target_title:
                    g_col.title = target_title
                g_col.user_id = auth_id

        # 4. Merge Daily Assignments
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

        # 5. Deduplicate Collections (Fix for Race Condition)
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
                    
                    db.flush()
                    # Delete duplicate collection
                    db.delete(dup)

        db.flush()
        state.status = "merged"
        state.merged_into = auth_id
        db.commit()
        return {"message": "Merge successful"}

    except Exception as e:
        db.rollback()
        if isinstance(e, HTTPException):
            raise
        print(f"Merge error: {e}")
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}")
    finally:
        db.close()

@router.delete("/auth/user")
def delete_user(user_id: str = Depends(get_deletion_user_id)):
    """
    Delete all data associated with a user.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    # Use admin connection for delete (needs to clean up all user data)
    from database import SessionLocal
    db = SessionLocal()
    try:
        lock_accounts(db, user_id)
        state = db.get(AccountLifecycle, user_id)
        if state is None:
            state = AccountLifecycle(user_id=user_id, status="deleted")
            db.add(state)
        state.status = "deleted"
        state.merge_apple_subject = None
        db.flush()
        db.query(MapTriviaUnlock).filter(
            MapTriviaUnlock.user_id == user_id
        ).delete(synchronize_session=False)

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
        # Tombstone blocks late writes even if Firebase is temporarily unavailable.
        try:
            firebase_auth.delete_user(user_id)
        except firebase_auth.UserNotFoundError:
            pass
        return {"message": "User data deleted successfully"}

    except Exception as e:
        db.rollback()
        print(f"Delete user error: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
    finally:
        db.close()
