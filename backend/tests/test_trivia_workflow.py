import base64
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, Trivia, TriviaCandidate, MapTrivia
from routers import line_admin
from routers.line_admin import _approve_candidate_from_line, _parse_collect_command, _parse_generate_command
from services.trivia_generation import build_generation_prompt
from services.trivia_collection import (
    CollectedTrivia,
    DEFAULT_COLLECTION_ATTEMPTS,
    DEFAULT_DISCOVERY_DOMAINS,
    DEFAULT_MAX_SEARCH_CALLS,
    TriviaCollectionResult,
    build_collection_prompt,
    collect_trivia,
    collect_trivia_candidates,
    get_incomplete_reason,
    get_collection_attempts,
    get_discovery_domains,
    get_max_search_calls,
    get_search_context_size,
    has_complete_map_fields,
    parse_collection_output,
    remove_existing_duplicates,
    select_diverse_items,
    validate_collected_items,
)
from services.line_bot import make_editor_token, read_editor_token, verify_signature
from services.trivia_map import build_trivia_spot, format_trivia_spot_block, parse_trivia_spot_block
from services.trivia_candidates import (
    CandidateError,
    DuplicateCandidateError,
    approve_candidate,
    create_candidate,
    create_candidates,
    reject_candidate,
    update_candidate,
)


class TriviaWorkflowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def test_candidate_schema_contains_workflow_columns(self):
        columns = {
            column["name"]
            for column in inspect(self.db.get_bind()).get_columns("trivia_candidates")
        }
        self.assertTrue({
            "image_url",
            "updated_at",
            "reviewed_at",
            "reviewed_by",
            "published_trivia_id",
            "line_sent_at",
        }.issubset(columns))

    def test_candidate_can_be_edited_and_approved_once(self):
        candidate = create_candidates(self.db, [{
            "title": "元タイトル",
            "content": "元本文",
            "explanation": "元解説",
            "source": "https://example.com",
            "category": "科学",
        }])[0]

        update_candidate(
            self.db,
            candidate.id,
            title="編集後タイトル",
            content="編集後本文",
            explanation="編集後解説",
            source="https://example.com/source",
            category="宇宙・天体",
        )
        first = approve_candidate(self.db, candidate.id, "test")
        second = approve_candidate(self.db, candidate.id, "test-again")

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(Trivia).count(), 1)
        self.assertEqual(first.title, "編集後タイトル")

    def test_rejected_candidate_cannot_be_approved(self):
        candidate = create_candidates(self.db, [{
            "title": "却下候補",
            "content": "本文",
            "category": "その他",
        }])[0]
        reject_candidate(self.db, candidate.id, "test")

        with self.assertRaises(CandidateError):
            approve_candidate(self.db, candidate.id, "test")
        self.assertEqual(self.db.query(Trivia).count(), 0)
        refreshed = self.db.query(TriviaCandidate).filter_by(id=candidate.id).one()
        self.assertEqual(refreshed.status, "rejected")
        self.assertIsNone(refreshed.published_trivia_id)

    def test_manual_candidate_rejects_similar_published_trivia(self):
        self.db.add(Trivia(
            title="タコには心臓が3つある",
            content="タコは全身用とエラ用を合わせて3つの心臓を持っています。",
            explanation="",
            source="",
            category="生物",
        ))
        self.db.commit()

        with self.assertRaises(DuplicateCandidateError):
            create_candidate(self.db, {
                "title": "タコの心臓は3つある",
                "content": "タコには役割の違う心臓が合計3つあります。",
                "category": "生物",
            })

    def test_generated_candidates_filter_duplicates(self):
        existing = create_candidate(self.db, {
            "title": "ハチミツは腐りにくい",
            "content": "糖度が高いハチミツは非常に腐りにくい食品です。",
            "category": "食べ物",
        })
        created = create_candidates(self.db, [
            {
                "title": "ハチミツは腐りにくい",
                "content": "糖度が高いハチミツは非常に腐りにくい食品です。",
                "category": "食べ物",
            },
            {
                "title": "金星の1日は1年より長い",
                "content": "金星は自転が遅く、1日の長さが公転周期よりも長くなります。",
                "category": "宇宙・天体",
            },
        ])

        self.assertEqual(len(created), 1)
        self.assertNotEqual(created[0].id, existing.id)

    def test_local_admin_content_similarity_threshold_is_preserved(self):
        create_candidate(self.db, {
            "title": "海の生き物の体の仕組み",
            "content": "タコは全身用とえら用を合わせて三つの心臓を持っています。",
            "category": "生物",
        })

        with self.assertRaises(DuplicateCandidateError):
            create_candidate(self.db, {
                "title": "軟体動物が持つ循環器官",
                "content": "タコは全身用とえら用を合わせて三個の心臓を備えています。",
                "category": "生物",
            })

    def test_reworded_fact_is_detected_as_duplicate(self):
        create_candidate(self.db, {
            "title": "タコには心臓が3つある",
            "content": "タコは全身用とえら用の心臓を合わせて三つ持っています。",
            "category": "生物",
        })

        with self.assertRaises(DuplicateCandidateError):
            create_candidate(self.db, {
                "title": "心臓を3個持つタコ",
                "content": "タコの体には全身へ血液を送る心臓が一つ、えらへ送る心臓が二つあります。",
                "category": "生物",
            })

    def test_different_facts_from_same_source_are_allowed(self):
        create_candidate(self.db, {
            "title": "タコは心臓を3つ持つ",
            "content": "タコには全身用が一つと、えら用が二つの心臓があります。",
            "source": "https://example.com/facts-list",
            "category": "生物",
        })

        candidate = create_candidate(self.db, {
            "title": "金星の1日は1年より長い",
            "content": "金星は自転が遅いため、一日の長さが公転周期を上回ります。",
            "source": "https://example.com/facts-list",
            "category": "宇宙・天体",
        })

        self.assertEqual(candidate.title, "金星の1日は1年より長い")

    def test_different_fact_about_same_subject_is_not_duplicate(self):
        create_candidate(self.db, {
            "title": "タコには心臓が3つある",
            "content": "タコは全身用とえら用の心臓を合わせて三つ持っています。",
            "category": "生物",
        })
        candidate = create_candidate(self.db, {
            "title": "タコの血液は青い",
            "content": "タコの血液は銅を含むヘモシアニンによって青く見えます。",
            "category": "生物",
        })

        self.assertEqual(candidate.title, "タコの血液は青い")

    def test_map_spot_keeps_explanation(self):
        spot = build_trivia_spot(
            title="東京タワーの色",
            description="東京タワーは赤白に見えますが、正式にはインターナショナルオレンジと白です。",
            explanation="航空機から目立つようにするため、航空法に基づく昼間障害標識として塗り分けられています。",
            prefecture="東京都",
            address="東京タワー / 東京都港区芝公園4-2-8",
            latitude=35.658581,
            longitude=139.745433,
            category="観光",
            spot_id="test_tokyo_tower_color",
        )
        block = format_trivia_spot_block(spot)
        parsed = parse_trivia_spot_block(block)

        self.assertIn("explanation", block)
        self.assertEqual(parsed["explanation"], spot["explanation"])

    def test_line_approve_map_candidate_publishes_to_map_trivia(self):
        candidate = create_candidate(self.db, {
            "title": "東京タワーの色",
            "content": "東京タワーは赤白に見えますが、正式にはインターナショナルオレンジと白です。",
            "explanation": "航空機から目立つようにするため、航空法に基づく昼間障害標識として塗り分けられています。",
            "category": "観光",
            "map_prefecture": "東京都",
            "map_address": "東京タワー / 東京都港区芝公園4-2-8",
            "map_latitude": 35.658581,
            "map_longitude": 139.745433,
            "map_radius": 300,
        })

        message = _approve_candidate_from_line(self.db, candidate.id, "line-user")
        refreshed = self.db.query(TriviaCandidate).filter_by(id=candidate.id).one()
        published = self.db.query(MapTrivia).one()
        self.assertEqual(refreshed.status, "rejected")
        self.assertIn("MAPに公開しました", message)
        self.assertEqual(self.db.query(Trivia).count(), 0)
        self.assertEqual(self.db.query(MapTrivia).count(), 1)
        self.assertEqual(published.map_prefecture, "東京都")
        self.assertEqual(published.map_address, "東京タワー / 東京都港区芝公園4-2-8")
        self.assertAlmostEqual(published.map_latitude, 35.658581)
        self.assertAlmostEqual(published.map_longitude, 139.745433)
        self.assertEqual(published.map_radius, 300)

    def test_delete_published_trivia_requires_unlinking_candidate(self):
        candidate = create_candidate(self.db, {
            "title": "削除対象の公開済み雑学",
            "content": "削除前に候補からの参照を外す必要がある本文です。",
            "explanation": "削除テスト用の解説です。",
            "category": "その他",
        })
        trivia = approve_candidate(self.db, candidate.id, "test")

        self.db.query(TriviaCandidate).filter(
            TriviaCandidate.published_trivia_id == trivia.id
        ).update(
            {TriviaCandidate.published_trivia_id: None},
            synchronize_session=False,
        )
        self.db.delete(trivia)
        self.db.commit()

        refreshed = self.db.query(TriviaCandidate).filter_by(id=candidate.id).one()
        self.assertIsNone(refreshed.published_trivia_id)
        self.assertIsNone(self.db.query(Trivia).filter_by(id=trivia.id).first())


class LineSecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "LINE_CHANNEL_SECRET": os.environ.get("LINE_CHANNEL_SECRET"),
            "CANDIDATE_EDITOR_SECRET": os.environ.get("CANDIDATE_EDITOR_SECRET"),
        }
        os.environ["LINE_CHANNEL_SECRET"] = "line-secret"
        os.environ["CANDIDATE_EDITOR_SECRET"] = "editor-secret"

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_line_signature_verification(self):
        body = b'{"events":[]}'
        digest = hmac.new(b"line-secret", body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")

        self.assertTrue(verify_signature(body, signature))
        self.assertFalse(verify_signature(body + b"x", signature))

    def test_editor_token_rejects_tampering(self):
        token = make_editor_token(42)
        self.assertEqual(read_editor_token(token), 42)

        with self.assertRaises(ValueError):
            read_editor_token(token[:-1] + ("A" if token[-1] != "A" else "B"))

    def test_editor_token_expires(self):
        token = make_editor_token(42, expires_in=-1)
        time.sleep(0.01)
        with self.assertRaises(ValueError):
            read_editor_token(token)

    def test_random_generation_commands_do_not_use_random_as_topic(self):
        self.assertEqual(_parse_generate_command("生成"), ("", 3))
        self.assertEqual(_parse_generate_command("生成 5"), ("", 5))
        self.assertEqual(_parse_generate_command("生成 ランダム 5"), ("", 5))
        self.assertEqual(_parse_generate_command("生成 おまかせ"), ("", 3))
        self.assertEqual(_parse_generate_command("生成 宇宙 4"), ("宇宙", 4))

    def test_theme_free_prompt_uses_distinct_categories_without_random_word(self):
        prompt = build_generation_prompt(
            "",
            3,
            "",
            selected_categories=["歴史", "生物", "食べ物"],
        )
        self.assertNotIn("ランダム", prompt)
        self.assertIn("それぞれ1件ずつ", prompt)
        self.assertIn("歴史、生物、食べ物", prompt)

    def test_collection_commands(self):
        self.assertEqual(_parse_collect_command("収集"), ("", 3, False))
        self.assertEqual(_parse_collect_command("収集 5"), ("", 5, False))
        self.assertEqual(_parse_collect_command("収集 食べ物 5"), ("食べ物", 5, False))
        self.assertEqual(_parse_collect_command("地図収集"), ("", 3, True))
        self.assertEqual(_parse_collect_command("地図収集 5"), ("", 5, True))
        self.assertEqual(_parse_collect_command("地図収集 京都 5"), ("京都", 5, True))
        self.assertEqual(_parse_collect_command("MAP収集 東京タワー 2"), ("東京タワー", 2, True))
        self.assertEqual(_parse_collect_command("収集(地図用)"), ("", 3, True))
        self.assertEqual(_parse_collect_command("収集(地図用) 5"), ("", 5, True))
        self.assertEqual(_parse_collect_command("収集(地図用) 京都 5"), ("京都", 5, True))
        self.assertEqual(_parse_collect_command("収集 地図用 京都 5"), ("京都", 5, True))
        self.assertIsNone(_parse_collect_command("生成 5"))

    def test_collection_prompt_forbids_copying(self):
        prompt = build_collection_prompt("", 5, ["既存タイトル"])
        self.assertIn("元記事のタイトルや文章をコピーしない", prompt)
        self.assertIn("事実・題材・キーワードだけ", prompt)
        self.assertIn("独自の日本語表現", prompt)
        self.assertIn("雑学サイト、まとめサイト、記事、メディアそのものを題材にしない", prompt)
        self.assertIn("深掘り内容を直接説明している個別ページのhttpまたはhttps URL", prompt)
        self.assertIn("話題まとめサイトの使い方", prompt)
        self.assertIn("タイトルだけで「何についての、どんな意外な事実か」", prompt)
        self.assertIn("疑問形、過度な煽り", prompt)
        self.assertIn("contentの繰り返しではなく", prompt)
        self.assertIn("同じ対象について同じ事実を述べる言い換え", prompt)
        self.assertIn("特定ジャンルに偏らず", prompt)
        self.assertIn("具体的な対象1つと、検証可能な事実1つ", prompt)
        self.assertIn("一覧記事の要約ではなく", prompt)
        self.assertIn("同一対象から選ぶのは1件まで", prompt)
        self.assertIn("最低3カテゴリ", prompt)
        self.assertIn("モデルの内部知識だけで題材、理由、例外、因果関係を作らない", prompt)
        self.assertIn("『魔女の宅急便』でなぜ使えるのか", prompt)
        self.assertIn("2段目の理由・例外・意外な繋がり", prompt)
        self.assertIn("公式ページ、官公庁、大学・研究機関", prompt)
        self.assertIn("日常会話で誰かに話したくなる", prompt)
        self.assertIn("常識逆転型", prompt)
        self.assertIn("疑問深掘り型", prompt)
        self.assertIn("身近な由来型", prompt)
        self.assertIn("想像超越型", prompt)
        self.assertIn("合計18点未満の候補は出力しない", prompt)
        self.assertIn("身近な比較で規模を実感できる場合は積極的に採用", prompt)
        self.assertIn("記録だけでは採用しない", prompt)
        self.assertIn("30秒で説明できないもの", prompt)
        self.assertIn("専門知識のない中学生", prompt)
        self.assertIn("候補のおよそ7割", prompt)
        self.assertIn("全体の3割以内", prompt)
        self.assertIn("専門語は1候補につき最大1つ", prompt)
        self.assertIn("専門用語を三つ以上使わないと説明できない題材", prompt)
        self.assertIn("45〜75文字程度", prompt)
        self.assertIn("80〜140文字程度、最大2文", prompt)
        self.assertIn("一度で言い換えられるか", prompt)
        self.assertIn(f"最大{DEFAULT_MAX_SEARCH_CALLS}回まで", prompt)
        self.assertIn("検索語や切り口を変えて複数回", prompt)
        self.assertIn("回数を使い切る必要はありません", prompt)

    def test_map_collection_prompt_requires_place_fields(self):
        prompt = build_collection_prompt("京都", 3, [], map_mode=True)
        self.assertIn("雑学MAPへ登録する候補だけ", prompt)
        self.assertIn("現地に証拠が残る", prompt)
        self.assertIn("一段目より二段目・三段目が面白い", prompt)
        self.assertIn("対象物そのものを観察できる候補", prompt)
        self.assertIn("私有地への立入り", prompt)
        self.assertIn("2件以上の独立した資料", prompt)
        self.assertIn("座標を推測しない", prompt)
        self.assertIn("map_address、map_prefecture、map_latitude、map_longitude、map_radius、map_hintを全件必ず", prompt)
        self.assertIn("合計26点以上", prompt)

    def test_map_collection_requires_complete_map_fields(self):
        complete = CollectedTrivia(
            subject_key="東京タワー",
            title="東京タワーは戦車由来の鉄も使った",
            content="東京タワーには、朝鮮戦争後の米軍戦車のスクラップ鉄も使われました。",
            explanation="建設当時は大量の鉄が必要で、入手しやすいスクラップ鉄も資材として活用されました。",
            category="歴史",
            source="https://example.com/tokyo-tower",
            map_address="東京タワー / 東京都港区芝公園4-2-8",
            map_prefecture="東京都",
            map_latitude=35.658581,
            map_longitude=139.745433,
            map_radius=300,
            map_hint="正面から塔の部材を見比べられます。",
        )
        incomplete = complete.model_copy(update={"map_address": ""})
        missing_hint = complete.model_copy(update={"map_hint": ""})
        invalid_radius = complete.model_copy(update={"map_radius": 5000})

        self.assertTrue(has_complete_map_fields(complete))
        self.assertFalse(has_complete_map_fields(incomplete))
        self.assertFalse(has_complete_map_fields(missing_hint))
        self.assertFalse(has_complete_map_fields(invalid_radius))

    def test_collection_search_is_unrestricted_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRIVIA_DISCOVERY_DOMAINS", None)
            self.assertEqual(
                get_discovery_domains(),
                list(DEFAULT_DISCOVERY_DOMAINS),
            )

    def test_collection_search_limit_is_configurable_and_bounded(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRIVIA_MAX_SEARCH_CALLS", None)
            self.assertEqual(get_max_search_calls(), DEFAULT_MAX_SEARCH_CALLS)
        with patch.dict(os.environ, {"TRIVIA_MAX_SEARCH_CALLS": "8"}, clear=False):
            self.assertEqual(get_max_search_calls(), 8)
        with patch.dict(os.environ, {"TRIVIA_MAX_SEARCH_CALLS": "99"}, clear=False):
            self.assertEqual(get_max_search_calls(), 10)
        with patch.dict(os.environ, {"TRIVIA_MAX_SEARCH_CALLS": "invalid"}, clear=False):
            self.assertEqual(get_max_search_calls(), DEFAULT_MAX_SEARCH_CALLS)

    def test_collection_search_context_defaults_to_medium_and_is_validated(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRIVIA_SEARCH_CONTEXT_SIZE", None)
            self.assertEqual(get_search_context_size(), "medium")
        with patch.dict(os.environ, {"TRIVIA_SEARCH_CONTEXT_SIZE": "high"}, clear=False):
            self.assertEqual(get_search_context_size(), "high")
        with patch.dict(os.environ, {"TRIVIA_SEARCH_CONTEXT_SIZE": "invalid"}, clear=False):
            self.assertEqual(get_search_context_size(), "medium")

    def test_collection_attempts_are_configurable_and_bounded(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRIVIA_COLLECTION_ATTEMPTS", None)
            self.assertEqual(get_collection_attempts(), DEFAULT_COLLECTION_ATTEMPTS)
        with patch.dict(os.environ, {"TRIVIA_COLLECTION_ATTEMPTS": "2"}, clear=False):
            self.assertEqual(get_collection_attempts(), 2)
        with patch.dict(os.environ, {"TRIVIA_COLLECTION_ATTEMPTS": "99"}, clear=False):
            self.assertEqual(get_collection_attempts(), 3)

    def test_collection_prompt_includes_all_existing_titles(self):
        titles = [f"既存タイトル{i}" for i in range(305)]
        prompt = build_collection_prompt(
            "",
            5,
            titles,
            existing_facts=["宅急便は商標: 宅急便はヤマト運輸の登録商標です。"],
        )

        self.assertIn("既存タイトル0", prompt)
        self.assertIn("既存タイトル304", prompt)
        self.assertIn("宅急便は商標: 宅急便はヤマト運輸の登録商標", prompt)
        self.assertIn("中心事実が同じ候補は出力しない", prompt)

    def test_collection_output_parser(self):
        items = parse_collection_output("""```json
        {"trivia": [
          {
            "title": "独自タイトル",
            "content": "独自本文",
            "explanation": "独自解説",
            "category": "生活",
            "source": "https://example.com/article"
          }
        ]}
        ```""")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "独自タイトル")

    def test_collection_allows_multiple_web_tool_calls_in_one_response(self):
        parsed_result = TriviaCollectionResult(trivia=[CollectedTrivia(
            subject_key="Web検索",
            title="Web収集テスト",
            content="Web検索から題材を集めて独自に作った本文です。",
            explanation="独自解説",
            category="生活",
            source="https://example.com/article",
        )])
        response = type("Response", (), {
            "output_text": json.dumps({
                "trivia": [{
                    "subject_key": "Web検索",
                    "title": "Web収集テスト",
                    "content": "Web検索から題材を集めて独自に作った本文です。",
                    "explanation": "独自解説",
                    "category": "生活",
                    "source": "https://example.com/article",
                }]
            }, ensure_ascii=False),
            "output_parsed": parsed_result,
            "status": "completed",
        })()
        parse = MagicMock(return_value=response)
        client = type("Client", (), {
            "responses": type("Responses", (), {"parse": parse})()
        })()

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "TRIVIA_DISCOVERY_DOMAINS": "example.com,https://media.example.jp/path",
        }, clear=False), patch(
            "services.trivia_collection.OpenAI",
            return_value=client,
        ):
            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            db = sessionmaker(bind=engine)()
            try:
                db.add(Trivia(
                    title="既存の雑学",
                    content="既存本文の中心事実です。",
                    explanation="",
                    source="https://example.com/existing",
                    category="生活",
                ))
                db.commit()
                items = collect_trivia(db, "", 5)
            finally:
                db.close()
                engine.dispose()

        self.assertEqual(len(items), 1)
        kwargs = parse.call_args.kwargs
        self.assertEqual(kwargs["max_tool_calls"], DEFAULT_MAX_SEARCH_CALLS)
        self.assertEqual(kwargs["max_output_tokens"], 16000)
        self.assertEqual(kwargs["reasoning"], {"effort": "low"})
        self.assertEqual(kwargs["tool_choice"], "required")
        self.assertEqual(kwargs["tools"][0]["search_context_size"], "medium")
        self.assertIn("既存本文の中心事実", kwargs["input"])
        self.assertIs(kwargs["text_format"], TriviaCollectionResult)
        self.assertEqual(
            kwargs["tools"][0]["filters"]["allowed_domains"],
            ["example.com", "media.example.jp"],
        )

    def test_shared_collection_workflow_persists_review_candidates(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        item = {
            "title": "深掘りした共通候補",
            "content": "Web検索で確認した共通収集処理のテスト本文です。",
            "explanation": "理由や例外まで追加検索して確認した解説です。",
            "source": "https://example.com/deep-fact",
            "category": "生活",
        }
        try:
            with patch("services.trivia_collection.collect_trivia", return_value=[item]):
                candidates = collect_trivia_candidates(db, "商標", 1)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(db.query(TriviaCandidate).count(), 1)
        finally:
            db.close()
            engine.dispose()

    def test_collection_retries_after_generated_items_are_duplicates(self):
        duplicate_result = TriviaCollectionResult(trivia=[CollectedTrivia(
            subject_key="タコ",
            title="心臓を3個持つタコ",
            content="タコの体には全身用が一つ、えら用が二つの心臓があります。",
            explanation="既存候補の言い換えです。",
            category="生物",
            source="https://example.com/octopus",
        )])
        novel_result = TriviaCollectionResult(trivia=[CollectedTrivia(
            subject_key="金星",
            title="金星では太陽が西から昇る",
            content="金星は多くの惑星とは逆向きに自転するため、太陽が西から昇ります。",
            explanation="地球とは反対方向にゆっくり自転していることが理由です。",
            category="宇宙・天体",
            source="https://example.com/venus",
        )])

        def response_for(parsed):
            return type("Response", (), {
                "output_text": "{}",
                "output_parsed": parsed,
                "status": "completed",
            })()

        parse = MagicMock(side_effect=[
            response_for(duplicate_result),
            response_for(novel_result),
        ])
        client = type("Client", (), {
            "responses": type("Responses", (), {"parse": parse})()
        })()
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            db.add(Trivia(
                title="タコには心臓が3つある",
                content="タコは全身用とえら用の心臓を合わせて三つ持っています。",
                explanation="",
                source="https://example.com/existing-octopus",
                category="生物",
            ))
            db.commit()
            with patch.dict(os.environ, {
                "OPENAI_API_KEY": "test-key",
                "TRIVIA_COLLECTION_ATTEMPTS": "3",
            }, clear=False), patch(
                "services.trivia_collection.OpenAI",
                return_value=client,
            ):
                items = collect_trivia(db, "科学", 1)
        finally:
            db.close()
            engine.dispose()

        self.assertEqual([item["title"] for item in items], ["金星では太陽が西から昇る"])
        self.assertEqual(parse.call_count, 2)
        self.assertIn("心臓を3個持つタコ", parse.call_args_list[1].kwargs["input"])

    def test_collection_schema_requires_all_fields(self):
        schema = TriviaCollectionResult.model_json_schema()
        item_schema = schema["$defs"]["CollectedTrivia"]
        self.assertFalse(item_schema["additionalProperties"])
        self.assertEqual(
            set(item_schema["required"]),
            {"subject_key", "title", "content", "explanation", "category", "source"},
        )

    def test_parsed_collection_filters_invalid_source_and_normalizes_category(self):
        items = validate_collected_items([
            CollectedTrivia(
                subject_key="有効",
                title="有効",
                content="本文",
                explanation="解説",
                category="暮らし",
                source="https://example.com",
            ),
            CollectedTrivia(
                subject_key="無効",
                title="無効",
                content="本文",
                explanation="解説",
                category="生活",
                source="example.com",
            ),
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"], "その他")

    def test_parsed_collection_filters_site_meta_topics(self):
        items = validate_collected_items([
            CollectedTrivia(
                subject_key="雑学サイト",
                title="雑学系サイトの分類と活用法",
                content="雑学サイトにはさまざまな分類があります。",
                explanation="サイトの使い方を説明します。",
                category="その他",
                source="https://example.com/article",
            ),
            CollectedTrivia(
                subject_key="タコ",
                title="タコには心臓が3つある",
                content="タコは全身用の心臓と、えらへ血液を送る心臓を持ちます。",
                explanation="えら心臓が二つ、体心臓が一つあり、それぞれ異なる役割を担っています。",
                category="生物",
                source="https://example.com/octopus",
            ),
        ])
        self.assertEqual([item["title"] for item in items], ["タコには心臓が3つある"])

    def test_parsed_collection_filters_broad_article_summaries(self):
        items = validate_collected_items([
            CollectedTrivia(
                subject_key="日本語",
                title="日本語には意外な由来を持つ語が多い",
                content="日常語には歴史的事情から生まれた言葉が多数あります。",
                explanation="記事では複数の言葉の由来が紹介されています。",
                category="言語・言葉",
                source="https://example.com/word-list",
            ),
            CollectedTrivia(
                subject_key="イクラ",
                title="イクラの語源はロシア語",
                content="日本語のイクラは、魚卵を意味するロシア語に由来します。",
                explanation="ロシア語の魚卵を表す言葉が日本へ伝わり、サケ科の卵を指す語として定着しました。",
                category="言語・言葉",
                source="https://example.com/ikura",
            ),
        ])
        self.assertEqual([item["title"] for item in items], ["イクラの語源はロシア語"])

    def test_concrete_fact_is_kept_even_if_explanation_mentions_article(self):
        items = validate_collected_items([
            CollectedTrivia(
                subject_key="ウナギ",
                title="ウナギの血液には毒性がある",
                content="ウナギの血清には毒性がありますが、加熱すると毒性は失われます。",
                explanation="記事では、生食を避け加熱調理する理由として血清毒が説明されています。",
                category="生物",
                source="https://example.com/eel",
            ),
        ])
        self.assertEqual([item["title"] for item in items], ["ウナギの血液には毒性がある"])

    def test_random_collection_selects_unique_subjects_and_limits_categories(self):
        items = [
            CollectedTrivia(
                subject_key=subject,
                title=title,
                content="本文",
                explanation="解説",
                category=category,
                source=f"https://example.com/{index}",
            )
            for index, (subject, title, category) in enumerate([
                ("目", "目の雑学1", "人体・医学"),
                ("目", "目の雑学2", "科学"),
                ("網膜", "網膜の雑学", "人体・医学"),
                ("タコ", "タコの雑学", "生物"),
                ("金星", "金星の雑学", "宇宙・天体"),
                ("ハチミツ", "ハチミツの雑学", "食べ物"),
                ("ウサギ", "ウサギの雑学", "生物"),
            ])
        ]

        selected = select_diverse_items(items, 5)

        self.assertEqual(len(selected), 5)
        self.assertEqual(
            sum(item.subject_key in {"目", "網膜"} for item in selected),
            1,
        )
        category_counts = {}
        for item in selected:
            category_counts[item.category] = category_counts.get(item.category, 0) + 1
        self.assertLessEqual(max(category_counts.values()), 2)
        self.assertGreaterEqual(len(category_counts), 4)

    def test_diversity_selection_falls_back_to_valid_items(self):
        items = [
            CollectedTrivia(
                subject_key="",
                title=f"有効な候補{index}",
                content=f"重複していない有効な本文{index}です。",
                explanation="Web検索で確認した解説です。",
                category="生活",
                source=f"https://example.com/fallback-{index}",
            )
            for index in range(5)
        ]

        selected = select_diverse_items(items, 5)

        self.assertEqual(len(selected), 5)
        self.assertEqual([item.title for item in selected], [
            "有効な候補0",
            "有効な候補1",
            "有効な候補2",
            "有効な候補3",
            "有効な候補4",
        ])

    def test_incomplete_collection_response_has_clear_message(self):
        response = type("Response", (), {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        })()
        self.assertIn("件数を減らして", get_incomplete_reason(response))


class MobileEditorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        self.previous_secret = os.environ.get("CANDIDATE_EDITOR_SECRET")
        os.environ["CANDIDATE_EDITOR_SECRET"] = "editor-integration-secret"

        app = FastAPI()
        app.include_router(line_admin.router)
        self.client = TestClient(app)
        self.session_patch = patch.object(
            line_admin,
            "SessionLocal",
            self.session_factory,
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.db.close()
        self.engine.dispose()
        if self.previous_secret is None:
            os.environ.pop("CANDIDATE_EDITOR_SECRET", None)
        else:
            os.environ["CANDIDATE_EDITOR_SECRET"] = self.previous_secret

    def _create_candidate(self, suffix: str) -> TriviaCandidate:
        return create_candidate(self.db, {
            "title": f"編集テスト{suffix}",
            "content": f"編集画面の統合テスト本文{suffix}",
            "category": "その他",
        })

    def test_existing_candidate_publishs_immediately_from_mobile_editor(self):
        candidate = self._create_candidate("A")
        token = make_editor_token(candidate.id)
        path = f"/admin/candidates/{candidate.id}/edit"

        page = self.client.get(path, params={"token": token})
        self.assertEqual(page.status_code, 200)

        saved = self.client.put(path, json={
            "token": token,
            "title": "編集後タイトルA",
            "content": "編集後の本文として保存しますA",
            "explanation": "編集後解説",
            "category": "科学",
            "source": "",
            "image_url": "",
            "publish": False,
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["status"], "approved")

        verify_db = self.session_factory()
        try:
            refreshed = verify_db.query(TriviaCandidate).filter_by(id=candidate.id).one()
            self.assertEqual(refreshed.status, "approved")
            self.assertIsNotNone(refreshed.published_trivia_id)
            self.assertEqual(verify_db.query(Trivia).count(), 1)
        finally:
            verify_db.close()

    def test_new_candidate_publishes_immediately_from_mobile_editor(self):
        token = make_editor_token(0)
        page = self.client.get("/admin/candidates/new", params={"token": token})
        self.assertEqual(page.status_code, 200)

        response = self.client.post("/admin/candidates/new", json={
            "token": token,
            "title": "スマホ手入力テスト",
            "content": "スマホから新しく入力した雑学の本文です。",
            "explanation": "",
            "category": "その他",
            "source": "",
            "image_url": "",
            "publish": False,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")
        verify_db = self.session_factory()
        try:
            self.assertEqual(verify_db.query(Trivia).count(), 1)
            self.assertEqual(verify_db.query(TriviaCandidate).count(), 0)
        finally:
            verify_db.close()

    def test_new_map_candidate_page_opens_with_map_fields(self):
        token = make_editor_token(0)
        page = self.client.get("/admin/candidates/new", params={"token": token, "map": "1"})

        self.assertEqual(page.status_code, 200)
        self.assertIn("新しい地図用雑学を登録", page.text)
        self.assertIn('id="add_to_map" type="checkbox" checked', page.text)
        self.assertIn('id="add_to_normal" type="checkbox">', page.text)

    def test_new_map_candidate_requires_address(self):
        token = make_editor_token(0)
        response = self.client.post("/admin/candidates/new", json={
            "token": token,
            "title": "地図用手入力テスト",
            "content": "地図用として新しく入力した雑学の本文です。",
            "explanation": "",
            "category": "歴史",
            "source": "",
            "image_url": "",
            "publish": False,
            "add_to_normal": False,
            "add_to_map": True,
            "map_prefecture": "東京都",
            "map_address": "",
        })

        self.assertEqual(response.status_code, 400)

    def test_mobile_editor_page_does_not_offer_draft_save(self):
        token = make_editor_token(0)
        page = self.client.get("/admin/candidates/new", params={"token": token})

        self.assertEqual(page.status_code, 200)
        self.assertNotIn("下書き保存", page.text)
        self.assertIn("登録する", page.text)
        self.assertIn('id="map_hint"', page.text)

    def test_new_map_candidate_publishes_to_map_trivia_directly(self):
        token = make_editor_token(0)
        response = self.client.post("/admin/candidates/new", json={
            "token": token,
            "title": "地図用直接公開テスト",
            "content": "東京タワーに関する地図雑学です。",
            "explanation": "公開先を map_trivia に分離したテストです。",
            "category": "歴史",
            "source": "",
            "image_url": "",
            "publish": True,
            "add_to_normal": False,
            "add_to_map": True,
            "map_prefecture": "東京都",
            "map_address": "東京タワー / 東京都港区芝公園4-2-8",
            "map_latitude": 35.658581,
            "map_longitude": 139.745433,
            "map_radius": 300,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")
        verify_db = self.session_factory()
        try:
            self.assertEqual(verify_db.query(MapTrivia).count(), 1)
            self.assertEqual(verify_db.query(TriviaCandidate).count(), 0)
            self.assertEqual(verify_db.query(Trivia).count(), 0)
        finally:
            verify_db.close()

    def test_existing_map_candidate_shows_collected_location_info(self):
        candidate = create_candidate(self.db, {
            "title": "地図候補編集テスト",
            "content": "地図候補として収集した雑学の本文です。",
            "explanation": "地図候補として収集した雑学の解説です。",
            "category": "歴史",
            "map_prefecture": "東京都",
            "map_address": "東京タワー / 東京都港区芝公園4-2-8",
            "map_latitude": 35.658581,
            "map_longitude": 139.745433,
            "map_radius": 300,
        })
        token = make_editor_token(candidate.id)

        page = self.client.get(f"/admin/candidates/{candidate.id}/edit", params={"token": token})

        self.assertEqual(page.status_code, 200)
        self.assertIn("収集済みMAP情報", page.text)
        self.assertIn("東京タワー / 東京都港区芝公園4-2-8", page.text)
        self.assertIn('id="add_to_map" type="checkbox" checked', page.text)
        self.assertIn('id="add_to_normal" type="checkbox">', page.text)

    def test_image_upload_returns_uploaded_url(self):
        token = make_editor_token(0)
        with patch.object(
            line_admin,
            "upload_trivia_image",
            return_value="https://images.example/trivia/test.webp",
        ):
            response = self.client.post(
                "/admin/candidates/image",
                data={"token": token},
                files={"image": ("test.jpg", b"image-bytes", "image/jpeg")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["image_url"],
            "https://images.example/trivia/test.webp",
        )


if __name__ == "__main__":
    unittest.main()
