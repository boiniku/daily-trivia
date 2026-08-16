import sys
import os

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API_DIR = os.path.join(REPOSITORY_ROOT, "apps", "api")
sys.path.insert(0, API_DIR)

from main import get_widget_trivia
from database import SessionLocal

db = SessionLocal()
print("--- TEST DAY 1 (TODAY) ---")
try:
    res1 = get_widget_trivia(user_id="test_widget_user_999", limit=3, date="2026-03-03", db=db)
    for r in res1:
        print(f"[{r.date}] ID: {r.id} - {r.title}")
except Exception as e:
    print(e)
    
print("\n--- TEST DAY 2 (TOMORROW) ---")
try:
    res2 = get_widget_trivia(user_id="test_widget_user_999", limit=3, date="2026-03-04", db=db)
    for r in res2:
        print(f"[{r.date}] ID: {r.id} - {r.title}")
except Exception as e:
    print(e)
db.close()
