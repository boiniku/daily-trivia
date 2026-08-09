from database import engine, Base
from sqlalchemy import inspect

def verify():
    insp = inspect(engine)
    print("Verifying schema...")
    
    # Check trivia columns
    columns = [c['name'] for c in insp.get_columns('trivia')]
    if 'hee_count' in columns:
        print("SUCCESS: 'hee_count' column exists in 'trivia'.")
    else:
        print("FAILURE: 'hee_count' column MISSING in 'trivia'.")
        
    # Check trivia_hees table
    if insp.has_table('trivia_hees'):
        print("SUCCESS: 'trivia_hees' table exists.")
    else:
        print("FAILURE: 'trivia_hees' table MISSING.")

if __name__ == "__main__":
    verify()
