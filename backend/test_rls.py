"""
Test RLS (Row-Level Security) policies on the Neon database.

Verifies:
1. app_user can SELECT from trivia (public read)
2. app_user CANNOT INSERT into trivia (admin only)
3. app_user can only see their own collections
4. app_user cannot see other users' collections
5. increment_hee_count SECURITY DEFINER function works
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

APP_DATABASE_URL = os.getenv("APP_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")

def test_rls():
    app_engine = create_engine(APP_DATABASE_URL)
    admin_engine = create_engine(DATABASE_URL)
    
    passed = 0
    failed = 0
    
    def check(name, condition):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name}")
            failed += 1
    
    # --- Test 1: app_user can SELECT trivia ---
    print("\n📋 Test 1: trivia SELECT (public read)")
    with app_engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM trivia"))
        count = result.scalar()
        check(f"Can read trivia table ({count} rows)", count > 0)
    
    # --- Test 2: app_user CANNOT INSERT into trivia ---
    print("\n📋 Test 2: trivia INSERT (should fail)")
    with app_engine.connect() as conn:
        try:
            conn.execute(text("""
                INSERT INTO trivia (title, content, explanation, source, category)
                VALUES ('TEST', 'TEST', 'TEST', 'TEST', 'TEST')
            """))
            conn.rollback()
            check("INSERT into trivia denied", False)  # Should not reach here
        except Exception as e:
            check(f"INSERT into trivia denied ({type(e).__name__})", True)
    
    # --- Test 3: Collections isolation ---
    print("\n📋 Test 3: collections isolation")
    
    # First, find two different user_ids from the admin connection
    with admin_engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT user_id FROM collections LIMIT 2"))
        user_ids = [row[0] for row in result]
    
    if len(user_ids) >= 2:
        user_a, user_b = user_ids[0], user_ids[1]
        
        # Get user A's collection count as admin (ground truth)
        with admin_engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM collections WHERE user_id = :uid"), {"uid": user_a})
            admin_count_a = result.scalar()
        
        # Get user A's collections via app_user with user_id set
        with app_engine.connect() as conn:
            conn.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_a})
            result = conn.execute(text("SELECT COUNT(*) FROM collections"))
            rls_count_a = result.scalar()
            check(f"User A sees only own collections (admin={admin_count_a}, RLS={rls_count_a})", rls_count_a == admin_count_a)
        
        # User A should NOT see user B's collections
        with app_engine.connect() as conn:
            conn.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_a})
            result = conn.execute(text("SELECT COUNT(*) FROM collections WHERE user_id = :uid"), {"uid": user_b})
            cross_count = result.scalar()
            check(f"User A cannot see User B's collections (count={cross_count})", cross_count == 0)
    else:
        print("  ⚠️  Not enough users to test isolation (need at least 2)")
    
    # --- Test 4: No user_id set = no collections visible ---
    print("\n📋 Test 4: No user_id = empty results")
    with app_engine.connect() as conn:
        # Don't set app.current_user_id
        result = conn.execute(text("SELECT COUNT(*) FROM collections"))
        no_user_count = result.scalar()
        check(f"No user_id set = 0 collections visible (count={no_user_count})", no_user_count == 0)
    
    # --- Test 5: increment_hee_count function ---
    print("\n📋 Test 5: increment_hee_count SECURITY DEFINER")
    with app_engine.connect() as conn:
        # Get current hee_count for trivia id=1
        result = conn.execute(text("SELECT hee_count FROM trivia WHERE id = 1"))
        row = result.fetchone()
        if row:
            original_count = row[0] or 0
            # Call the function
            result = conn.execute(text("SELECT increment_hee_count(1, 1)"))
            new_count = result.scalar()
            check(f"increment_hee_count works (was={original_count}, now={new_count})", new_count == original_count + 1)
            
            # Revert the change
            conn.execute(text("SELECT increment_hee_count(1, -1)"))
            conn.commit()
        else:
            print("  ⚠️  No trivia with id=1 found")
    
    # --- Summary ---
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("🎉 All RLS tests passed!")
    else:
        print("⚠️  Some tests failed. Review the output above.")
    
    return failed == 0

if __name__ == "__main__":
    test_rls()
