"""
RLS (Row-Level Security) Setup Script for Neon PostgreSQL

This script:
1. Creates an `app_user` role with limited privileges
2. Enables RLS on all tables
3. Creates RLS policies for per-user data isolation
4. Creates a SECURITY DEFINER function for hee_count updates

Safe to run on production DB because:
- neondb_owner (current connection) bypasses RLS
- app_user role is only used when the backend code is updated to use it
"""

import os
import secrets
import string
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def generate_password(length=32):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def setup_rls():
    engine = create_engine(DATABASE_URL)
    
    # Generate a secure password for app_user
    app_user_password = generate_password()
    
    with engine.connect() as conn:
        # ============================================================
        # Step 1: Create app_user role
        # ============================================================
        print("Step 1: Creating app_user role...")
        
        # Check if role already exists
        result = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'"))
        if result.fetchone():
            print("  app_user role already exists. Updating password...")
            conn.execute(text(f"ALTER ROLE app_user WITH PASSWORD :pw"), {"pw": app_user_password})
        else:
            conn.execute(text(f"CREATE ROLE app_user WITH LOGIN PASSWORD :pw"), {"pw": app_user_password})
            print("  app_user role created.")
        
        # Grant connect & usage
        conn.execute(text("GRANT CONNECT ON DATABASE neondb TO app_user"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_user"))
        
        # Grant table permissions
        # trivia: SELECT only (no INSERT/UPDATE/DELETE by app_user)
        conn.execute(text("GRANT SELECT ON trivia TO app_user"))
        
        # collections: full CRUD for user's own data
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON collections TO app_user"))
        
        # collection_items: full CRUD for user's own collections
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON collection_items TO app_user"))
        
        # daily_assignments: full CRUD for user's own data
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON daily_assignments TO app_user"))
        
        # trivia_candidates: no access for app_user (admin only)
        # (no GRANT = no access)
        
        # trivia_hees: full CRUD for user's own data
        conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON trivia_hees TO app_user"))
        
        # Grant sequence usage (needed for INSERT with auto-increment IDs)
        conn.execute(text("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user"))
        
        print("  Permissions granted.")
        
        # ============================================================
        # Step 2: Enable RLS on all tables
        # ============================================================
        print("\nStep 2: Enabling RLS on tables...")
        
        tables = ["trivia", "collections", "collection_items", "daily_assignments", "trivia_candidates", "trivia_hees"]
        for table in tables:
            conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            print(f"  RLS enabled on {table}")
        
        # ============================================================
        # Step 3: Create RLS Policies
        # ============================================================
        print("\nStep 3: Creating RLS policies...")
        
        # Helper: drop policy if exists (Postgres doesn't have CREATE OR REPLACE for policies)
        def create_policy(name, table, command, using=None, with_check=None):
            conn.execute(text(f"DROP POLICY IF EXISTS {name} ON {table}"))
            
            sql = f"CREATE POLICY {name} ON {table} FOR {command} TO app_user"
            if using:
                sql += f" USING ({using})"
            if with_check:
                sql += f" WITH CHECK ({with_check})"
            conn.execute(text(sql))
            print(f"  Created policy: {name} on {table}")
        
        # --- trivia: everyone can read ---
        create_policy("trivia_select_all", "trivia", "SELECT", using="true")
        
        # --- collections: user can only access own ---
        user_id_check = "user_id = current_setting('app.current_user_id', true)"
        
        create_policy("collections_select_own", "collections", "SELECT", using=user_id_check)
        create_policy("collections_insert_own", "collections", "INSERT", with_check=user_id_check)
        create_policy("collections_update_own", "collections", "UPDATE", using=user_id_check, with_check=user_id_check)
        create_policy("collections_delete_own", "collections", "DELETE", using=user_id_check)
        
        # --- collection_items: user can access items in their own collections ---
        collection_owner_check = "collection_id IN (SELECT id FROM collections WHERE user_id = current_setting('app.current_user_id', true))"
        
        create_policy("collection_items_select_own", "collection_items", "SELECT", using=collection_owner_check)
        create_policy("collection_items_insert_own", "collection_items", "INSERT", with_check=collection_owner_check)
        create_policy("collection_items_update_own", "collection_items", "UPDATE", using=collection_owner_check, with_check=collection_owner_check)
        create_policy("collection_items_delete_own", "collection_items", "DELETE", using=collection_owner_check)
        
        # --- daily_assignments: user can only access own ---
        create_policy("daily_assignments_select_own", "daily_assignments", "SELECT", using=user_id_check)
        create_policy("daily_assignments_insert_own", "daily_assignments", "INSERT", with_check=user_id_check)
        create_policy("daily_assignments_delete_own", "daily_assignments", "DELETE", using=user_id_check)
        
        # --- trivia_candidates: no policies for app_user (admin only, no GRANT given) ---
        # No policies needed since app_user has no GRANT on this table
        
        # --- trivia_hees: user can only access own ---
        create_policy("trivia_hees_select_own", "trivia_hees", "SELECT", using=user_id_check)
        create_policy("trivia_hees_insert_own", "trivia_hees", "INSERT", with_check=user_id_check)
        create_policy("trivia_hees_update_own", "trivia_hees", "UPDATE", using=user_id_check, with_check=user_id_check)
        create_policy("trivia_hees_delete_own", "trivia_hees", "DELETE", using=user_id_check)
        
        # ============================================================
        # Step 4: Create SECURITY DEFINER function for hee_count
        # ============================================================
        print("\nStep 4: Creating SECURITY DEFINER function for hee_count...")
        
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION increment_hee_count(target_trivia_id INT, amount INT)
            RETURNS INT AS $$
            DECLARE
                new_count INT;
            BEGIN
                UPDATE trivia 
                SET hee_count = COALESCE(hee_count, 0) + amount
                WHERE id = target_trivia_id
                RETURNING hee_count INTO new_count;
                
                RETURN COALESCE(new_count, 0);
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER
        """))
        
        # Grant execute permission to app_user
        conn.execute(text("GRANT EXECUTE ON FUNCTION increment_hee_count(INT, INT) TO app_user"))
        
        print("  increment_hee_count function created.")
        
        # Commit all changes
        conn.commit()
        
    print("\n" + "=" * 60)
    print("✅ RLS setup complete!")
    print("=" * 60)
    print(f"\napp_user password: {app_user_password}")
    print(f"\nAdd this to your .env file:")
    
    # Build the APP_DATABASE_URL from the existing DATABASE_URL
    # Replace neondb_owner:OLD_PASSWORD with app_user:NEW_PASSWORD
    import re
    app_db_url = re.sub(
        r'://[^:]+:[^@]+@',
        f'://app_user:{app_user_password}@',
        DATABASE_URL
    )
    print(f"APP_DATABASE_URL={app_db_url}")
    print("\n⚠️  Save this password! It won't be shown again.")

if __name__ == "__main__":
    setup_rls()
