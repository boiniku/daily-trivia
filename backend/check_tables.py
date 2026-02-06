from sqlalchemy import inspect
from database import engine
from models import DailyAssignment

def check_tables():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print("Existing tables:", tables)
    
    if "daily_assignments" in tables:
        print("daily_assignments table verification: OK")
    else:
        print("daily_assignments table verification: FAILED")

if __name__ == "__main__":
    check_tables()
