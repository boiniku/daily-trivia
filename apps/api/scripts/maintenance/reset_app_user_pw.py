"""Reset app_user password and print the APP_DATABASE_URL."""
import os, re, secrets, string
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
url = os.getenv("DATABASE_URL")
pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

engine = create_engine(url)
with engine.connect() as conn:
    conn.execute(text(f"ALTER ROLE app_user WITH PASSWORD '{pw}'"))
    conn.commit()

app_url = re.sub(r'://[^:]+:[^@]+@', f'://app_user:{pw}@', url)
print(f"APP_DATABASE_URL={app_url}")
