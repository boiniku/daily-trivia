from sqlalchemy import inspect
from database import engine

def check_columns():
    inspector = inspect(engine)
    
    for table_name in inspector.get_table_names():
        print(f"Table: {table_name}")
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        print(f"  Columns: {columns}")
        
if __name__ == "__main__":
    check_columns()
