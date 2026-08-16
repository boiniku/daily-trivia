import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import search_collection_items
from models import Base, Collection, CollectionItem, Trivia, TriviaHee


class CollectionSearchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "before_cursor_execute", retval=True)
        def replace_postgres_rls_statement(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("SET LOCAL app.current_user_id"):
                return "SELECT 1", ()
            return statement, parameters

        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        db = self.session_factory()
        self.collection = Collection(user_id="user-1", title="過去に見た雑学", icon="time-outline")
        other_collection = Collection(user_id="user-2", title="過去に見た雑学", icon="time-outline")
        db.add_all([self.collection, other_collection])
        db.flush()

        trivia = [
            Trivia(title="タコの心臓", content="タコには心臓が3つある", explanation="海の生き物です", source="", category="生物", hee_count=10),
            Trivia(title="富士山の雪", content="山頂には長く雪が残る", explanation="日本で最も高い山です", source="", category="地理", hee_count=30),
            Trivia(title="宇宙で鳴らない音", content="真空では音が伝わらない", explanation="空気の振動が必要です", source="", category="科学", hee_count=20),
            Trivia(title="100%ジュース", content="表示には基準がある", explanation="食品表示の雑学です", source="", category="食べ物", hee_count=5),
        ]
        db.add_all(trivia)
        db.flush()
        db.add_all([CollectionItem(collection_id=self.collection.id, trivia_id=item.id) for item in trivia])
        db.add(TriviaHee(user_id="user-1", trivia_id=trivia[0].id, count=7))
        db.commit()
        self.collection_id = self.collection.id
        self.other_collection_id = other_collection.id
        db.close()

    def tearDown(self):
        self.engine.dispose()

    def search(self, **overrides):
        params = {
            "collection_id": self.collection_id,
            "q": "",
            "category": None,
            "sort": "default",
            "limit": 30,
            "offset": 0,
            "user_id": "user-1",
        }
        params.update(overrides)
        with patch("main.AppSessionLocal", self.session_factory):
            return search_collection_items(**params)

    def test_searches_japanese_across_fields_and_requires_all_terms(self):
        result = self.search(q="日本 高い")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["title"], "富士山の雪")

    def test_search_treats_like_wildcards_as_literal_text(self):
        result = self.search(q="100%")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["title"], "100%ジュース")

    def test_filters_sorts_and_paginates(self):
        first_page = self.search(sort="total", limit=2)
        second_page = self.search(sort="total", limit=2, offset=2)
        self.assertEqual(first_page["total"], 4)
        self.assertTrue(first_page["has_more"])
        self.assertEqual([item["hee_count"] for item in first_page["items"]], [30, 20])
        self.assertFalse(second_page["has_more"])
        self.assertIn("生物", first_page["categories"])

        category_result = self.search(category="科学")
        self.assertEqual(category_result["total"], 1)
        self.assertEqual(category_result["items"][0]["category"], "科学")

    def test_cannot_search_another_users_collection(self):
        with self.assertRaises(HTTPException) as raised:
            self.search(collection_id=self.other_collection_id)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
