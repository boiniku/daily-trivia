"""Transaction-scoped identity barrier shared by deletion, merge and uploads."""
import hashlib

from fastapi import HTTPException
from sqlalchemy import text
from models import AccountLifecycle


def lock_accounts(db, *user_ids):
    for uid in sorted(set(user_ids)):
        if db.bind.dialect.name == "postgresql":
            # Same stable key as the SQL write trigger; never Python's random hash().
            key = int.from_bytes(hashlib.md5(uid.encode()).digest()[:8], "big", signed=True)
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def require_active_account(db, user_id):
    lock_accounts(db, user_id)
    state = db.get(AccountLifecycle, user_id)
    if state and state.status != "active":
        raise HTTPException(status_code=409, detail="Account data is deleted or transferred")
    return state
