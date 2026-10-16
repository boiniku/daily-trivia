"""Authenticated routes must run on real PostgreSQL with both DB drivers."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

import main
from models import Base, Trivia


@unittest.skipUnless(os.environ.get("TEST_POSTGRES_DATABASE_URL"), "PostgreSQL test URL not configured")
class PostgresAuthenticatedApiTests(unittest.TestCase):
    def test_collections_and_photo_gallery_with_both_drivers(self):
        url = make_url(os.environ["TEST_POSTGRES_DATABASE_URL"])
        if (url.host or "").endswith(".neon.tech"):
            url = url.set(host=url.host.replace("-pooler.", "."))
        for driver in ("psycopg", "psycopg2"):
            with self.subTest(driver=driver):
                schema = "test_photo_auth_" + uuid4().hex
                target_url = url.set(drivername="postgresql+" + driver)
                admin = create_engine(target_url)
                engine = create_engine(target_url, connect_args={"options": "-csearch_path=" + schema})
                created = False
                overrides = dict(main.app.dependency_overrides)
                client = TestClient(main.app)
                try:
                    with admin.begin() as db:
                        db.execute(text(f'CREATE SCHEMA "{schema}"'))
                    created = True
                    Base.metadata.create_all(engine)
                    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
                    urls = ["https://images.test/one.webp", "https://images.test/two.webp"]
                    sources = {urls[1]: "Photographer and license"}
                    with sessions() as db:
                        item = Trivia(title="Photos", content="Body", explanation="Details", source="", category="Test",
                                      image_url=urls[0], image_urls=urls, image_sources=sources)
                        db.add(item)
                        db.commit()
                        trivia_id = item.id
                    current_user = ["test-user'quoted"]
                    main.app.dependency_overrides[main.get_current_user_id] = lambda: current_user[0]
                    with patch.object(main, "AppSessionLocal", sessions):
                        for _ in range(2):
                            response = client.get("/collections")
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertEqual(len(response.json()), 2)
                            self.assertTrue(all(row["user_id"] == current_user[0] for row in response.json()))
                        response = client.post("/collections", json={"title": "Photo folder"})
                        self.assertEqual(response.status_code, 200, response.text)
                        collection_id = response.json()["id"]
                        path = f"/collections/{collection_id}/items"
                        response = client.post(path, json={"trivia_id": trivia_id})
                        self.assertEqual(response.status_code, 200, response.text)
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(response.json()[0]["image_urls"], urls)
                        self.assertEqual(response.json()[0]["image_sources"], sources)
                        response = client.get(f"/trivia/{trivia_id}/hee")
                        self.assertEqual(response.status_code, 200, response.text)
                        current_user[0] = "another-user"
                        response = client.get("/collections")
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(len(response.json()), 2)
                        self.assertTrue(all(row["user_id"] == current_user[0] for row in response.json()))
                finally:
                    client.close()
                    main.app.dependency_overrides.clear()
                    main.app.dependency_overrides.update(overrides)
                    engine.dispose()
                    if created:
                        with admin.begin() as db:
                            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                    admin.dispose()


if __name__ == "__main__":
    unittest.main()
