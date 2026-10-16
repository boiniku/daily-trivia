import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Trivia
from services.trivia_csv_import import (
    TriviaCsvValidationError,
    find_existing_duplicate_keys,
    import_trivia_rows,
    parse_trivia_csv,
)


class TriviaCsvImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_parses_utf8_bom_csv_and_ignores_blank_lines(self):
        parsed = parse_trivia_csv(
            ("﻿タイトル,本文,詳細,カテゴリ\r\n"
             "タコの心臓,タコには心臓が3つある,役割の異なる心臓を持つ,生物\r\n"
             ",,,\r\n").encode("utf-8")
        )

        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.rows[0].line_number, 2)
        self.assertEqual(parsed.rows[0].explanation, "役割の異なる心臓を持つ")

    def test_parses_cp932_csv(self):
        parsed = parse_trivia_csv(
            "タイトル,本文,詳細,カテゴリ\r\n富士山,日本で最も高い山,,地理\r\n".encode("cp932")
        )

        self.assertEqual(parsed.rows[0].category, "地理")

    def test_rejects_wrong_headers_and_invalid_rows(self):
        with self.assertRaises(TriviaCsvValidationError):
            parse_trivia_csv("題名,本文,詳細,カテゴリ\n題,本文,詳細,生物\n".encode("utf-8"))

        with self.assertRaises(TriviaCsvValidationError) as context:
            parse_trivia_csv("タイトル,本文,詳細,カテゴリ\n,本文,詳細,未知\n".encode("utf-8"))
        self.assertIn("2行目", str(context.exception))

    def test_duplicate_rows_are_skipped_in_file_and_database(self):
        parsed = parse_trivia_csv(
            ("タイトル,本文,詳細,カテゴリ\n"
             "タコ,心臓が3つある,詳細,生物\n"
             " タコ , 心臓が3つある ,別の詳細,生物\n").encode("utf-8")
        )
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(len(parsed.warnings), 1)

        self.db.add(Trivia(title="タコ", content="心臓が3つある", explanation="", category="生物"))
        self.db.commit()
        self.assertEqual(len(find_existing_duplicate_keys(self.db, parsed.rows)), 1)

        result = import_trivia_rows(self.db, parsed.rows)
        self.assertEqual(result.created_count, 0)
        self.assertEqual(result.skipped_duplicate_count, 1)
        self.assertEqual(self.db.query(Trivia).count(), 1)

    def test_imports_all_valid_rows_atomically(self):
        parsed = parse_trivia_csv(
            ("タイトル,本文,詳細,カテゴリ\n"
             "タコ,心臓が3つある,詳細,生物\n"
             "富士山,日本で最も高い山,,地理\n").encode("utf-8")
        )

        result = import_trivia_rows(self.db, parsed.rows)

        self.assertEqual(result.created_count, 2)
        self.assertEqual(self.db.query(Trivia).count(), 2)
        self.assertEqual(self.db.query(Trivia).filter_by(title="富士山").one().source, "")


if __name__ == "__main__":
    unittest.main()
