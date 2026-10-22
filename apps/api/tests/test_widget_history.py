"""Widget installation and swipes, rather than prefetches, create history.

These run the HTTP routes against SQLite with PostgreSQL's set_config registered
as a local function; SQLite does not exercise the production advisory lock.
"""

import datetime
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:", "APP_DATABASE_URL": "sqlite:///:memory:"}):
    import main
    from models import Base, Collection, CollectionItem, DailyAssignment, Trivia
    from services.trivia_history import record_history_items


DAY = "2026-10-22"
USER = "widget-user"


class WidgetHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def configure(connection, _record):
            connection.create_function("set_config", 3, lambda _key, value, _local: value)
            # Stable ordering lets selection tests distinguish unseen candidates
            # from the last-resort fallback to already-seen trivia.
            connection.create_function("random", 0, lambda: 0)
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.read_sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.read_sessions() as db:
            db.add_all([
                Trivia(id=i, title=f"Trivia {i}", content="Body", explanation="Details", source="", category="Science")
                for i in range(1, 9)
            ])
            db.commit()

        commits = self.commits = []

        class ScopedSession(Session):
            def execute(self, statement, params=None, *args, **kwargs):
                if str(statement).startswith("SELECT set_config('app.current_user_id'"):
                    self.info["rls_user"] = params["uid"]
                return super().execute(statement, params, *args, **kwargs)

            def flush(self, *args, **kwargs):
                if any(isinstance(row, (Collection, CollectionItem, DailyAssignment)) for row in self.new):
                    if not self.info.get("rls_user"):
                        raise AssertionError("a premature commit cleared the user context before history was saved")
                return super().flush(*args, **kwargs)

            def commit(self):
                super().commit()
                commits.append(self.info.pop("rls_user", None))

        self.sessions = sessionmaker(
            bind=self.engine, class_=ScopedSession, autoflush=False, expire_on_commit=False,
        )
        self.overrides = dict(main.app.dependency_overrides)
        main.app.dependency_overrides[main.get_optional_user_id] = lambda: None
        main.app.dependency_overrides[main.get_current_user_id] = lambda: USER
        self.database_patch = patch.object(main, "AppSessionLocal", self.sessions)
        self.database_patch.start()
        # Keep route diagnostics out of the working tree.
        self.log_patch = patch("builtins.open", side_effect=OSError("test logging disabled"))
        self.log_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.log_patch.stop()
        self.database_patch.stop()
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(self.overrides)
        self.engine.dispose()

    def get(self, path, **params):
        response = self.client.get(path, params={"user_id": USER, "date": DAY, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return [row["id"] for row in response.json()]

    def history_ids(self, user=USER):
        with self.read_sessions() as db:
            return sorted(row[0] for row in db.query(CollectionItem.trivia_id).join(Collection).filter(
                Collection.user_id == user, Collection.title == "過去に見た雑学",
            ).all())

    def assignment_ids(self, day=DAY):
        with self.read_sessions() as db:
            return [row.trivia_id for row in db.query(DailyAssignment).filter(
                DailyAssignment.user_id == USER,
                DailyAssignment.date == datetime.date.fromisoformat(day),
            ).order_by(DailyAssignment.id).all()]

    def seed_assignments(self, ids, day=DAY):
        with self.read_sessions() as db:
            db.add_all([DailyAssignment(user_id=USER, date=datetime.date.fromisoformat(day), trivia_id=i) for i in ids])
            db.commit()

    def seed_history(self, ids, user=USER):
        with self.read_sessions() as db:
            folder = Collection(user_id=user, title="過去に見た雑学")
            db.add(folder)
            db.flush()
            db.add_all([CollectionItem(collection_id=folder.id, trivia_id=i) for i in ids])
            db.commit()

    def swipe(self, trivia_id):
        response = self.client.post("/history", json={"trivia_id": trivia_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_today_prefetch_saves_only_three_assignments_and_no_history(self):
        ids = self.get("/trivia/today", limit=8)
        self.assertEqual(len(ids), 8)
        self.assertEqual(self.assignment_ids(), ids[:3])
        self.assertEqual(self.history_ids(), [])
        self.assertEqual(self.get("/trivia/today"), ids[:3])
        self.assertEqual(self.history_ids(), [])

    def test_more_and_category_fetches_do_not_save_history_or_assignments(self):
        self.get("/trivia/today", include_assignments="false")
        self.get("/trivia/today", category="Science")
        self.assertEqual(self.assignment_ids(), [])
        self.assertEqual(self.history_ids(), [])

    def test_detail_fetch_does_not_record_history(self):
        response = self.client.get("/trivia/1")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.history_ids(), [])

    def test_uninstalled_widget_can_fetch_but_does_not_record_history(self):
        ids = self.get("/trivia/widget", widget_installed="false")
        self.assertEqual(len(ids), 3)
        self.assertEqual(self.assignment_ids(), ids)
        self.assertEqual(self.history_ids(), [])
        self.assertEqual(self.get("/trivia/widget", widget_installed="false"), ids)
        self.assertEqual(self.history_ids(), [])

    def test_installing_after_today_prefetch_records_the_same_three_once(self):
        ids = self.get("/trivia/today")
        self.assertEqual(self.get("/trivia/widget", widget_installed="true"), ids)
        self.assertEqual(self.history_ids(), sorted(ids))
        self.get("/trivia/widget", widget_installed="true")
        self.assertEqual(self.history_ids(), sorted(ids))
        self.assertEqual(self.assignment_ids(), ids)

    def test_installing_after_an_uninstalled_widget_fetch_records_existing_assignments(self):
        ids = self.get("/trivia/widget", widget_installed="false")
        self.assertEqual(self.get("/trivia/widget", widget_installed="true"), ids)
        self.assertEqual(self.history_ids(), sorted(ids))

    def test_legacy_widget_defaults_to_installed_and_caps_to_three(self):
        ids = self.get("/trivia/widget", limit=8)
        self.assertEqual(len(ids), 3)
        self.assertEqual(self.assignment_ids(), ids)
        self.assertEqual(self.history_ids(), sorted(ids))
        self.get("/trivia/widget", limit=8)
        self.assertEqual(self.history_ids(), sorted(ids))

    def test_today_and_widget_keep_assignment_order_even_when_ids_are_not_sorted(self):
        self.seed_assignments([7, 2, 5, 1])
        self.assertEqual(self.get("/trivia/today"), [7, 2, 5])
        self.assertEqual(self.get("/trivia/widget", widget_installed="true"), [7, 2, 5])
        self.assertEqual(self.history_ids(), [2, 5, 7])

    def test_swipes_and_widget_registration_are_idempotent_and_user_scoped(self):
        ids = self.get("/trivia/today")
        self.seed_history([8], user="other-user")
        self.swipe(ids[0])
        self.assertEqual(self.history_ids(), [ids[0]])
        self.get("/trivia/widget", widget_installed="true")
        for trivia_id in ids:
            self.swipe(trivia_id)
            self.swipe(trivia_id)
        self.assertEqual(self.history_ids(), sorted(ids))
        self.assertEqual(self.history_ids("other-user"), [8])
        response = self.client.get("/collections")
        self.assertEqual(response.status_code, 200, response.text)
        history = next(row for row in response.json() if row["title"] == "過去に見た雑学")
        self.assertEqual(history["count"], 3)

    def test_uninstalling_preserves_existing_history(self):
        ids = self.get("/trivia/widget", widget_installed="true")
        with self.read_sessions() as db:
            before = [(row.id, row.trivia_id, row.saved_at) for row in db.query(CollectionItem).all()]
        self.get("/trivia/widget", widget_installed="false")
        self.get("/trivia/today")
        with self.read_sessions() as db:
            after = [(row.id, row.trivia_id, row.saved_at) for row in db.query(CollectionItem).all()]
        self.assertEqual(after, before)
        self.assertEqual(self.history_ids(), sorted(ids))

    def test_anonymous_widget_fetch_does_not_save_history(self):
        response = self.client.get("/trivia/widget", params={"date": DAY, "widget_installed": "true"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.history_ids(), [])
        self.assertEqual(self.assignment_ids(), [])

    def test_past_unread_assignments_are_eligible_but_today_assignments_remain_excluded(self):
        self.seed_history([1, 4, 5, 6, 7, 8])
        self.seed_assignments([2], day="2026-10-21")
        self.seed_assignments([3])
        self.assertEqual(self.get("/trivia/today", limit=1, include_assignments="false"), [2])
        self.assertEqual(self.history_ids(), [1, 4, 5, 6, 7, 8])

    def test_widget_can_reassign_a_past_unread_trivia(self):
        self.seed_history([1, 3, 4, 5, 6, 7, 8])
        self.seed_assignments([2], day="2026-10-21")
        self.assertEqual(self.get("/trivia/widget", limit=1, widget_installed="false"), [2])
        self.assertEqual(self.history_ids(), [1, 3, 4, 5, 6, 7, 8])

    def test_swipe_folder_and_item_are_committed_together_with_user_context(self):
        self.swipe(1)
        self.assertEqual(self.commits, [USER])
        self.assertEqual(self.history_ids(), [1])

    def test_history_endpoint_still_requires_authentication(self):
        del main.app.dependency_overrides[main.get_current_user_id]
        response = self.client.post("/history", json={"trivia_id": 1})
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.history_ids(), [])

    def test_shared_history_helper_sees_repeated_writes_with_autoflush_disabled(self):
        with self.sessions() as db:
            db.execute(main.text("SELECT set_config('app.current_user_id', :uid, true)"), {"uid": USER})
            self.assertEqual(record_history_items(db, USER, [1, 1, 2]), 2)
            self.assertEqual(record_history_items(db, USER, [2, 3]), 1)
            self.assertEqual(record_history_items(db, USER, [1, 2, 3]), 0)
            db.commit()
        self.assertEqual(self.history_ids(), [1, 2, 3])

    def test_existing_duplicate_folders_do_not_cause_a_second_copy_of_old_history(self):
        self.seed_history([1])
        self.seed_history([2])
        self.swipe(2)
        self.assertEqual(self.history_ids(), [1, 2])

    def test_failed_widget_history_write_rolls_back_assignments_and_new_folder(self):
        original = main.record_history_items

        def fail_after_history(db, user_id, ids):
            original(db, user_id, ids)
            raise RuntimeError("history transaction failed")

        with patch.object(main, "record_history_items", side_effect=fail_after_history):
            response = self.client.get("/trivia/widget", params={"user_id": USER, "date": DAY, "widget_installed": "true"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.history_ids(), [])
        self.assertEqual(self.assignment_ids(), [])
        with self.read_sessions() as db:
            self.assertEqual(db.query(Collection).count(), 0)


if __name__ == "__main__":
    unittest.main()
