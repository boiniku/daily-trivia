import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, SocialPublishJob, SocialVideoJob, Trivia
from routers.social_automation import _authorize as authorize_social_automation
from services.line_bot import make_line_video_preview, social_review_messages
from services.kling import KlingClient, KlingTask
from services.seedance import SeedanceClient, SeedanceTask
from services.social_content import (
    build_social_prompt,
    build_shared_text_prompt,
    generate_social_content,
    normalize_social_content,
    script_quality_issues,
    shared_text_quality_issues,
    trim_for_x,
    x_weighted_length,
)
from services.static_video import compose_static_video, _fit_scene_durations_to_audio
from services.aivis_tts import AivisTTSClient, build_narration_ssml, generate_aivis_narration
from services.story_patterns import select_story_pattern
from services.social_publishers import ThreadsTextPublisher, XTextPublisher
from services.social_pipeline import (
    approve_content_job,
    create_daily_text_job,
    create_content_job,
    poll_seedance_job,
    poll_kling_job,
    publish_due_text_jobs,
    process_due_video_jobs,
    regenerate_content_job,
    render_static_video_job,
    submit_seedance_job,
    submit_kling_job,
)


def sample_content():
    return {
        "x": {"text": "タコの心臓は3つあります。 #雑学"},
        "threads": {"text": "タコの心臓は3つあります。知っていましたか？", "topic_tag": "雑学"},
        "instagram": {"caption": "タコの雑学", "hashtags": ["雑学"]},
        "tiktok": {"caption": "タコの雑学", "hashtags": ["雑学"]},
        "video": {
            "narration": ["タコの心臓は3つあります。"],
            "subtitles": ["心臓は3つ"],
            "image_prompt": "Vertical editorial illustration of an octopus. No text.",
            "visual_prompts": [
                {"duration": 8, "prompt": "Vertical documentary footage of an octopus. No text."},
                {"duration": 9, "prompt": "Underwater close-up of an octopus."},
            ],
        },
    }


def sample_scene_content():
    content = sample_content()
    content["video"]["hook_candidates"] = ["タコの心臓、いくつだと思う？"]
    content["video"]["scenes"] = [
        {
            "duration": 2.5,
            "role": "hook",
            "narration": "タコの心臓、いくつだと思いますか？",
            "subtitle": "心臓はいくつ？",
            "image_prompt": "Vertical close-up of an octopus. No text.",
            "motion": "zoom_in",
        },
        {
            "duration": 3.5,
            "role": "question",
            "narration": "人間と同じひとつではありません。",
            "subtitle": "1つではない",
            "image_prompt": "Vertical mysterious octopus silhouette. No text.",
            "motion": "pan_left",
        },
        {
            "duration": 7,
            "role": "reveal",
            "narration": "答えは三つです。",
            "subtitle": "答えは3つ",
            "image_prompt": "Vertical scientific octopus illustration. No text.",
            "motion": "zoom_out",
        },
        {
            "duration": 6,
            "role": "payoff",
            "narration": "二つはえらへ血液を送ります。",
            "subtitle": "2つはえらへ送る",
            "image_prompt": "Vertical underwater octopus portrait. No text.",
            "motion": "pan_right",
        },
    ]
    return content


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data

    @property
    def content(self):
        return b"fake-audio"


class SocialAutomationAuthorizationTests(unittest.TestCase):
    def test_manual_routes_only_accept_social_secret(self):
        with patch.dict(
            "os.environ",
            {
                "SOCIAL_AUTOMATION_SECRET": "manual-secret",
                "DAILY_COLLECTION_SECRET": "scheduler-secret",
            },
            clear=False,
        ):
            authorize_social_automation("Bearer manual-secret")
            with self.assertRaises(HTTPException):
                authorize_social_automation("Bearer scheduler-secret")

    def test_scheduler_routes_can_accept_daily_collection_secret(self):
        with patch.dict(
            "os.environ",
            {
                "SOCIAL_AUTOMATION_SECRET": "manual-secret",
                "DAILY_COLLECTION_SECRET": "scheduler-secret",
            },
            clear=False,
        ):
            authorize_social_automation(
                "Bearer scheduler-secret",
                allow_scheduler_secret=True,
            )


class FakeAivisErrorResponse:
    status_code = 401
    content = b'{"detail":"Unauthorized"}'

    def raise_for_status(self):
        import requests
        raise requests.HTTPError("401 Client Error")

    def json(self):
        return {"detail": "Unauthorized"}


class FakeAivisErrorSession:
    def post(self, url, **kwargs):
        return FakeAivisErrorResponse()


class FakeHttpSession:
    def __init__(self):
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return FakeResponse({"id": "task-1", "status": "queued"})

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakeResponse({
            "id": "task-1",
            "status": "succeeded",
            "content": {"video_url": "https://example.com/video.mp4"},
        })


class FakeSeedance:
    def __init__(self):
        self.created = []

    def create_video(self, prompt, **kwargs):
        task_id = f"task-{len(self.created) + 1}"
        self.created.append((prompt, kwargs))
        return SeedanceTask(task_id, "queued")

    def get_task(self, task_id):
        return SeedanceTask(task_id, "succeeded", f"https://example.com/{task_id}.mp4")


class FakeKlingHttpSession:
    def __init__(self):
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return FakeResponse({
            "code": 0,
            "data": {"id": "kling-task-1", "status": "submitted"},
        })

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakeResponse({
            "code": 0,
            "data": [{
                "id": "kling-task-1",
                "status": "succeeded",
                "outputs": [{
                    "type": "video",
                    "url": "https://kling.example/result.mp4",
                    "duration": "5",
                }],
            }],
        })


class FakeKling:
    def __init__(self):
        self.created = []

    def create_image_video(self, prompt, first_frame_url, **kwargs):
        self.created.append((prompt, first_frame_url, kwargs))
        return KlingTask("kling-task-1", "submitted")

    def get_task(self, task_id):
        return KlingTask(
            task_id,
            "succeeded",
            "https://kling.example/result.mp4",
            duration=5.0,
        )


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, *args):
        self.calls.append(args)
        return SimpleNamespace(remote_post_id="remote-1", remote_post_url="https://example.com/post")


class FakePublishResponse:
    def __init__(self, data, *, content=b"", content_type="application/json"):
        self._data = data
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class FakeXPublishSession:
    def __init__(self, image_data):
        self.image_data = image_data
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return FakePublishResponse({}, content=self.image_data, content_type="image/png")

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        if url.endswith("/media/upload"):
            return FakePublishResponse({"data": {"id": "media-1"}})
        return FakePublishResponse({"data": {"id": "post-1"}})


class FakeThreadsPublishSession:
    def __init__(self):
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        if url.endswith("/threads_publish"):
            return FakePublishResponse({"id": "thread-1"})
        return FakePublishResponse({"id": "container-1"})


class FakeInstagramPublisher:
    def __init__(self):
        self.submissions = []
        self.published = []

    def submit(self, video_url, caption):
        self.submissions.append((video_url, caption))
        return SimpleNamespace(remote_post_id="ig-container-1")

    def status(self, container_id):
        return "FINISHED"

    def publish(self, container_id):
        self.published.append(container_id)
        return SimpleNamespace(remote_post_id="ig-media-1", remote_post_url=None)


class FakeTikTokPublisher:
    def __init__(self):
        self.submissions = []

    def submit(self, video_url, caption):
        self.submissions.append((video_url, caption))
        return SimpleNamespace(remote_post_id="tt-publish-1")

    def status(self, publish_id):
        return "PUBLISH_COMPLETE", "tt-video-1"


class FakeParsed:
    def __init__(self, data):
        self.data = data

    def model_dump(self):
        return self.data


class FakeResponsesApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeOpenAI:
    def __init__(self, responses):
        self.responses = FakeResponsesApi(responses)


def fake_model_response(data, *, searches=0, input_tokens=100, output_tokens=50):
    search_items = [
        SimpleNamespace(
            type="web_search_call",
            action=SimpleNamespace(
                sources=[SimpleNamespace(url="https://example.com/verified-source")]
            ),
        )
        for _ in range(searches)
    ]
    return SimpleNamespace(
        output_parsed=FakeParsed(data),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        output=search_items,
    )


class SocialPipelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.trivia = Trivia(
            title="タコの心臓",
            content="タコには心臓が3つあります。",
            explanation="2つはえらへ血液を送ります。",
            source="https://example.com/source",
            category="生物",
            hee_count=10,
        )
        self.db.add(self.trivia)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_x_text_is_trimmed_to_weighted_limit(self):
        text = trim_for_x("雑" * 200)
        self.assertLessEqual(x_weighted_length(text), 280)
        self.assertTrue(text.endswith("…"))

    def test_story_pattern_uses_origin_before_generic_misconception(self):
        pattern = select_story_pattern({
            "subject": "ネギトロ",
            "common_misconception": "ネギとトロが由来だと思われる",
            "verified_fact": "名前の語源は動作名だといわれる",
            "explanation": "身をねぎ取るという呼び方に由来する",
        })
        self.assertEqual(pattern, "origin_story")

    def test_aivis_client_sends_bearer_auth_and_mp3_settings(self):
        session = FakeHttpSession()
        client = AivisTTSClient(
            "secret-key",
            base_url="https://aivis.example/v1",
            session=session,
        )
        audio = client.synthesize(
            "<speak><s>タコです。</s></speak>",
            model_uuid="model-1",
            style_name="Normal",
        )
        self.assertEqual(audio, b"fake-audio")
        method, url, request = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://aivis.example/v1/tts/synthesize")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-key")
        self.assertEqual(request["json"]["output_format"], "mp3")
        self.assertEqual(request["json"]["style_name"], "Normal")

    def test_aivis_ssml_escapes_script_text(self):
        ssml = build_narration_ssml(["魚 & 肉", "答えです"])
        self.assertIn("魚 &amp; 肉", ssml)
        self.assertIn('<break time="180ms"/>', ssml)
        self.assertNotIn("<speak>", ssml)
        self.assertTrue(ssml.startswith("<s>"))

    def test_aivis_error_identifies_rejected_key_without_echoing_it(self):
        client = AivisTTSClient(
            "private-secret",
            base_url="https://aivis.example/v1",
            session=FakeAivisErrorSession(),
        )
        with self.assertRaisesRegex(RuntimeError, "API key was rejected") as raised:
            client.synthesize("テスト", model_uuid="model-1")
        self.assertNotIn("private-secret", str(raised.exception))

    def test_aivis_production_narration_uses_selected_surprise_style(self):
        class RecordingAivis:
            def __init__(self):
                self.style_name = None

            def synthesize(self, text, *, style_name=None, **kwargs):
                self.style_name = style_name
                return b"audio"

        client = RecordingAivis()
        with patch.dict("os.environ", {"AIVIS_SELECTED_STYLE": "Surprise"}):
            audio = generate_aivis_narration(["タコの雑学です。"], client=client)
        self.assertEqual(audio, b"audio")
        self.assertEqual(client.style_name, "Surprise")

    def test_x_publisher_uploads_image_and_attaches_media_id(self):
        source = BytesIO()
        Image.new("RGB", (320, 480), "teal").save(source, format="PNG")
        session = FakeXPublishSession(source.getvalue())
        publisher = XTextPublisher("token", session=session)

        result = publisher.publish("完結した雑学です。", "https://cdn.example/image.png", "画像説明")

        self.assertEqual(result.remote_post_id, "post-1")
        upload_request = session.requests[1]
        post_request = session.requests[2]
        self.assertTrue(upload_request[1].endswith("/media/upload"))
        self.assertEqual(post_request[2]["json"]["media"]["media_ids"], ["media-1"])

    def test_threads_publisher_creates_and_publishes_image_container(self):
        session = FakeThreadsPublishSession()
        publisher = ThreadsTextPublisher("token", "user-1", session=session)

        result = publisher.publish(
            "完結した雑学です。",
            "雑学",
            "https://cdn.example/image.png",
            "画像説明",
        )

        self.assertEqual(result.remote_post_id, "thread-1")
        self.assertEqual(session.requests[0][2]["params"]["media_type"], "IMAGE")
        self.assertEqual(session.requests[0][2]["params"]["image_url"], "https://cdn.example/image.png")
        self.assertTrue(session.requests[1][1].endswith("/threads_publish"))

    def test_normalization_clamps_seedance_duration_and_adds_guard(self):
        content = sample_content()
        content["video"]["visual_prompts"][1]["duration"] = 50
        normalized = normalize_social_content(content)
        self.assertEqual(normalized["video"]["visual_prompts"][1]["duration"], 15)
        self.assertIn("No text", normalized["video"]["visual_prompts"][1]["prompt"])

    def test_normalization_builds_retention_scenes(self):
        normalized = normalize_social_content(sample_scene_content())
        self.assertEqual(len(normalized["video"]["scenes"]), 4)
        self.assertEqual(normalized["video"]["subtitles"][0], "心臓はいくつ？")
        self.assertGreaterEqual(sum(item["duration"] for item in normalized["video"]["scenes"]), 18)
        self.assertEqual(normalized["video"]["scenes"][1]["motion"], "pan_left")
        self.assertEqual(normalized["x"]["text"], normalized["threads"]["text"])

    def test_quality_check_rejects_contextless_hook_and_overlong_scene(self):
        content = sample_scene_content()
        content["video"]["hook_candidates"] = ["これ、脳に見える？"] * 3
        content["video"]["scenes"][0]["narration"] = "これ、脳に見える？"
        content["video"]["scenes"][2]["narration"] = "長い説明です。" * 20
        issues = script_quality_issues(content, "カニみそ")
        self.assertTrue(any("これ・それ・あれ" in issue for issue in issues))
        self.assertTrue(any("対象名" in issue for issue in issues))
        self.assertTrue(any("シーン3" in issue for issue in issues))

    def test_quality_check_rejects_generic_clickbait_hook(self):
        content = sample_scene_content()
        content["video"]["hook_candidates"] = [
            "タコの心臓、かなり意外です",
            "タコの心臓には秘密があります",
            "タコの心臓、知っていますか",
        ]
        content["video"]["scenes"][0]["narration"] = "タコの心臓、かなり意外です。"

        issues = script_quality_issues(content, "タコ")

        self.assertTrue(any("抽象的な煽り" in issue for issue in issues))

    def test_quality_check_rejects_duplicate_hook_candidates(self):
        content = sample_scene_content()
        content["video"]["hook_candidates"] = ["タコの心臓は一つじゃない"] * 3

        issues = script_quality_issues(content, "タコ")

        self.assertTrue(any("異なる角度" in issue for issue in issues))

    def test_social_prompt_requests_polite_but_conversational_narration(self):
        research = {
            "subject": "タコ",
            "common_misconception": "心臓は一つだと思われやすい",
            "verified_fact": "心臓は三つある",
            "explanation": "二つはえらへ血液を送る",
            "supporting_details": ["残る一つは全身へ送る"],
            "caveats": [],
            "visual_anchors": ["タコ"],
            "sources": ["https://example.com"],
        }

        prompt = build_social_prompt(self.trivia, research)

        self.assertIn("丁寧だけれど話がうまい友人", prompt)
        self.assertIn("敬語のです・ます調", prompt)
        self.assertIn("思い込みと事実の差", prompt)
        self.assertIn("結論として", prompt)

    def test_quality_check_rejects_stiff_explanatory_narration(self):
        content = sample_scene_content()
        content["video"]["scenes"][2]["narration"] = "結論として、心臓は三つあるということです。"

        issues = script_quality_issues(content, "タコ")

        self.assertTrue(any("硬い解説口調" in issue for issue in issues))

    def test_shared_text_requires_an_explicit_answer_and_explanation(self):
        research = {
            "subject": "タコ",
            "verified_fact": "タコの心臓は三つある",
        }
        vague = {
            "text": "タコの心臓には、とても意外な秘密があります。知っていましたか？ #雑学",
            "answer": "タコの心臓は三つあります。",
            "alt_text": "海中を泳ぐタコの写真",
        }

        issues = shared_text_quality_issues(vague, research)

        self.assertTrue(any("答えを明言" in issue for issue in issues))
        self.assertTrue(any("問いかけで終わらず" in issue for issue in issues))

    def test_shared_text_prompt_uses_one_complete_post_for_both_platforms(self):
        research = {
            "subject": "タコ",
            "common_misconception": "心臓は一つ",
            "verified_fact": "心臓は三つ",
            "explanation": "二つはえらへ血液を送る",
            "supporting_details": [],
            "caveats": [],
            "visual_anchors": ["タコ"],
            "sources": ["https://example.com"],
        }

        prompt = build_shared_text_prompt(self.trivia, research)

        self.assertIn("XとThreadsの両方へそのまま投稿する共通本文", prompt)
        self.assertIn("結論を明言", prompt)
        self.assertIn("問いかけたまま答えを伏せて終わらない", prompt)

    def test_content_generation_researches_then_writes_script(self):
        research = {
            "subject": "タコ",
            "common_misconception": "心臓は一つだと思われやすい",
            "verified_fact": "タコの心臓は三つある",
            "explanation": "二つはえらへ血液を送る",
            "supporting_details": ["残る一つは全身へ送る"],
            "caveats": [],
            "visual_anchors": ["タコ", "心臓を示す抽象表現"],
            "sources": ["https://example.com/source"],
        }
        draft = sample_scene_content()
        draft["video"]["hook_candidates"] = [
            "タコの心臓、いくつだと思う？",
            "タコには心臓が一つでは足りない？",
            "タコの体には心臓が三つある",
        ]
        client = FakeOpenAI([
            fake_model_response(research, searches=1, input_tokens=400, output_tokens=150),
            fake_model_response(draft, input_tokens=700, output_tokens=500),
        ])
        generated = generate_social_content(self.trivia, client=client)
        self.assertEqual(len(client.responses.calls), 2)
        self.assertEqual(client.responses.calls[0]["tool_choice"], "required")
        self.assertNotIn("tools", client.responses.calls[1])
        self.assertEqual(generated["research"]["subject"], "タコ")
        self.assertEqual(
            generated["research"]["sources"], ["https://example.com/verified-source"]
        )
        self.assertEqual(generated["generation_meta"]["web_search_calls"], 1)
        self.assertFalse(generated["generation_meta"]["repaired"])
        self.assertGreater(generated["generation_meta"]["estimated_cost_usd"], 0)

    def test_content_generation_repairs_an_unnatural_script_once(self):
        research = {
            "subject": "タコ",
            "common_misconception": "心臓は一つだと思われやすい",
            "verified_fact": "タコの心臓は三つある",
            "explanation": "二つはえらへ血液を送る",
            "supporting_details": [],
            "caveats": [],
            "visual_anchors": ["タコ"],
            "sources": ["https://example.com/source"],
        }
        invalid = sample_scene_content()
        invalid["video"]["hook_candidates"] = ["これ、いくつ？"] * 3
        invalid["video"]["scenes"][0]["narration"] = "これ、いくつだと思う？"
        repaired = sample_scene_content()
        repaired["video"]["hook_candidates"] = [
            "タコの心臓はいくつ？",
            "タコには心臓が三つある？",
            "タコの体は心臓が一つではない",
        ]
        client = FakeOpenAI([
            fake_model_response(research, searches=1),
            fake_model_response(invalid),
            fake_model_response(repaired),
        ])
        generated = generate_social_content(self.trivia, client=client)
        self.assertEqual(len(client.responses.calls), 3)
        self.assertTrue(generated["generation_meta"]["repaired"])
        self.assertIn("前回案の問題点", client.responses.calls[2]["input"])

    def test_seedance_client_sends_vertical_silent_video(self):
        session = FakeHttpSession()
        client = SeedanceClient(api_key="test", base_url="https://ark.example/v3", session=session)
        created = client.create_video("A quiet ocean", duration=8, model="seedance-test")
        fetched = client.get_task(created.id)
        payload = session.requests[0][2]["json"]
        self.assertEqual(payload["ratio"], "9:16")
        self.assertFalse(payload["generate_audio"])
        self.assertEqual(fetched.video_url, "https://example.com/video.mp4")

    def test_kling_client_sends_720p_silent_five_second_video(self):
        session = FakeKlingHttpSession()
        client = KlingClient(api_key="test", base_url="https://kling.example", session=session)

        created = client.create_image_video(
            "Subtle natural movement",
            "https://cdn.example/first-frame.png",
            duration=5,
        )
        fetched = client.get_task(created.id)

        payload = session.requests[0][2]["json"]
        self.assertEqual(
            session.requests[0][1],
            "https://kling.example/image-to-video/kling-3.0",
        )
        self.assertEqual(payload["settings"]["resolution"], "720p")
        self.assertEqual(payload["settings"]["duration"], 5)
        self.assertEqual(payload["settings"]["audio"], "off")
        self.assertFalse(payload["settings"]["multi_shot"])
        self.assertEqual(fetched.video_url, "https://kling.example/result.mp4")

    def test_create_job_is_idempotent_and_creates_platform_jobs(self):
        first = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        second = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(first.publish_jobs), 2)
        self.assertEqual(len(first.video_jobs), 1)
        self.assertEqual(first.video_jobs[0].provider, "static")

    def test_unapproved_content_can_be_regenerated_before_media_creation(self):
        content_job = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        regenerated = regenerate_content_job(
            self.db,
            content_job.id,
            generator=lambda trivia: normalize_social_content(sample_scene_content()),
        )
        self.assertEqual(len(regenerated.content_json["video"]["scenes"]), 4)
        self.assertEqual(len(regenerated.video_jobs[0].prompt_json["image_prompts"]), 4)
        self.assertEqual(regenerated.video_jobs[0].status, "pending")

    def test_static_video_render_archives_image_and_video(self):
        content_job = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        video_job = self.db.query(SocialVideoJob).filter_by(content_job_id=content_job.id).one()
        uploads = []

        def fake_composer(image_data, title, subtitles, output_path, **kwargs):
            self.assertEqual(image_data, b"image")
            self.assertEqual(title, "タコの心臓")
            output_path.write_bytes(b"mp4")
            return 12.0

        def fake_uploader(data, content_type, extension, **kwargs):
            uploads.append((data, content_type, extension, kwargs["prefix"]))
            return f"https://cdn.example/{kwargs['prefix']}.{extension}"

        rendered = render_static_video_job(
            self.db,
            video_job.id,
            image_generator=lambda prompt: b"image",
            narration_generator=lambda lines: b"audio",
            background_music_loader=lambda: None,
            promo_video_loader=lambda: None,
            intro_video_loader=lambda: None,
            composer=fake_composer,
            uploader=fake_uploader,
        )
        self.assertEqual(rendered.status, "ready")
        self.assertEqual(rendered.final_video_url, "https://cdn.example/videos.mp4")
        self.assertEqual(rendered.thumbnail_url, "https://cdn.example/images.png")
        self.assertEqual([item[3] for item in uploads], ["images", "videos"])
        approve_content_job(self.db, content_job.id)
        video_publish_jobs = [job for job in content_job.publish_jobs if job.content_type == "video"]
        self.assertTrue(all(job.status == "queued" for job in video_publish_jobs))

    def test_static_video_render_generates_and_archives_each_scene_image(self):
        content_job = create_content_job(
            self.db, self.trivia.id, generator=lambda trivia: normalize_social_content(sample_scene_content())
        )
        video_job = self.db.query(SocialVideoJob).filter_by(content_job_id=content_job.id).one()
        uploads = []

        def fake_uploader(data, content_type, extension, **kwargs):
            uploads.append((data, kwargs["prefix"]))
            return f"https://cdn.example/{kwargs['prefix']}-{len(uploads)}.{extension}"

        def fake_composer(images, title, subtitles, output_path, **kwargs):
            self.assertEqual(len(images), 4)
            self.assertEqual(len(kwargs["scenes"]), 4)
            self.assertEqual(kwargs["narration"][-1], "毎日3つの雑学を、ウィジェットで。毎日雑学。")
            self.assertEqual(kwargs["promo_video_data"], b"promo-video")
            output_path.write_bytes(b"mp4")
            return 24.0

        render_static_video_job(
            self.db,
            video_job.id,
            image_generator=lambda prompt: prompt.encode(),
            narration_generator=lambda lines: b"audio",
            background_music_loader=lambda: b"bgm",
            promo_video_loader=lambda: b"promo-video",
            composer=fake_composer,
            uploader=fake_uploader,
        )
        self.assertEqual([prefix for _, prefix in uploads], ["images"] * 4 + ["videos"])
        self.assertEqual(len(video_job.prompt_json["image_urls"]), 4)

    def test_static_video_composer_creates_vertical_mp4(self):
        source = BytesIO()
        Image.new("RGB", (200, 300), "#325b8c").save(source, "PNG")
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.mp4"
            with (
                patch("services.static_video.WIDTH", 270),
                patch("services.static_video.HEIGHT", 480),
                patch("services.static_video.FPS", 5),
            ):
                duration = compose_static_video(
                    [source.getvalue(), source.getvalue()],
                    "タコの心臓",
                    ["タコには", "心臓が3つあります"],
                    output_path,
                    narration=["タコには心臓が3つあります"],
                )
            self.assertGreaterEqual(duration, 12)
            self.assertTrue(output_path.read_bytes().startswith(b"\x00\x00\x00"))

    def test_scene_durations_expand_to_fit_complete_narration(self):
        durations = _fit_scene_durations_to_audio(
            [2.5, 3.5, 7.0, 6.0],
            28.0,
            fixed_duration=0.0,
        )
        self.assertGreaterEqual(sum(durations), 28.4)
        self.assertAlmostEqual(durations[0] / durations[-1], 2.5 / 6.0, places=2)

    def test_ready_static_video_can_be_force_rendered(self):
        content_job = create_content_job(
            self.db, self.trivia.id, generator=lambda trivia: sample_content()
        )
        video_job = content_job.video_jobs[0]
        video_job.status = "ready"
        video_job.final_video_url = "https://cdn.example/old.mp4"
        self.db.commit()
        uploads = []

        def fake_uploader(data, content_type, extension, **kwargs):
            uploads.append(kwargs["prefix"])
            return f"https://cdn.example/new-{kwargs['prefix']}.{extension}"

        def fake_composer(images, title, subtitles, output_path, **kwargs):
            output_path.write_bytes(b"new-video")
            return 30.0

        rendered = render_static_video_job(
            self.db,
            video_job.id,
            force=True,
            image_generator=lambda prompt: b"image",
            narration_generator=lambda lines: b"audio",
            background_music_loader=lambda: b"escort",
            promo_video_loader=lambda: None,
            intro_video_loader=lambda: None,
            composer=fake_composer,
            uploader=fake_uploader,
        )
        self.assertEqual(rendered.final_video_url, "https://cdn.example/new-videos.mp4")
        self.assertEqual(rendered.duration_seconds, 30.0)
        self.assertEqual(rendered.prompt_json["render_meta"]["bgm"], "DOVA-SYNDROME Escort")

    def test_seedance_submit_and_poll(self):
        content_job = create_content_job(
            self.db, self.trivia.id, generator=lambda trivia: sample_content(), video_mode="seedance"
        )
        video_job = self.db.query(SocialVideoJob).filter_by(content_job_id=content_job.id).one()
        client = FakeSeedance()
        submit_seedance_job(self.db, video_job.id, client)
        self.assertEqual(video_job.status, "generating")
        self.assertEqual(len(video_job.provider_task_ids), 2)
        poll_seedance_job(self.db, video_job.id, client)
        self.assertEqual(video_job.status, "clips_ready")
        self.assertEqual(len(video_job.source_video_urls), 2)

    def test_kling_submit_and_poll_archives_paid_assets(self):
        content_job = create_content_job(
            self.db, self.trivia.id, generator=lambda trivia: sample_scene_content(), video_mode="kling"
        )
        video_job = self.db.query(SocialVideoJob).filter_by(content_job_id=content_job.id).one()
        uploads = []

        def fake_uploader(data, content_type, extension, **kwargs):
            uploads.append((data, content_type, extension, kwargs["prefix"]))
            return f"https://cdn.example/{kwargs['prefix']}-{len(uploads)}.{extension}"

        client = FakeKling()
        submit_kling_job(
            self.db,
            video_job.id,
            client,
            image_generator=lambda prompt: b"first-frame",
            uploader=fake_uploader,
        )
        self.assertEqual(video_job.status, "generating")
        self.assertEqual(video_job.provider_task_ids, ["kling-task-1"])
        _, first_frame_url, options = client.created[0]
        self.assertEqual(first_frame_url, video_job.thumbnail_url)
        self.assertEqual(options["resolution"], "720p")
        self.assertFalse(options["audio"])
        self.assertEqual(options["duration"], 5)

        poll_kling_job(
            self.db,
            video_job.id,
            client,
            downloader=lambda url: b"kling-video",
            uploader=fake_uploader,
        )
        self.assertEqual(video_job.status, "clips_ready")
        self.assertEqual(video_job.duration_seconds, 5.0)
        self.assertEqual(len(video_job.source_video_urls), 1)
        self.assertEqual(
            [item[3] for item in uploads],
            ["images/kling-first-frames", "clips/kling"],
        )

    def test_approved_text_jobs_publish_once(self):
        self.trivia.image_url = "https://cdn.example/octopus.png"
        self.db.commit()
        text = "タコの心臓は一つではありません。実は三つあります。二つがえらへ血液を送ります。 #雑学"
        content_job = create_daily_text_job(
            self.db,
            generator=lambda trivia: {
                "x": {"text": text},
                "threads": {"text": text, "topic_tag": "雑学"},
                "shared_image": {"url": trivia.image_url, "alt_text": "海中にいるタコの画像"},
            },
        )
        x = FakePublisher()
        threads = FakePublisher()
        completed = publish_due_text_jobs(
            self.db,
            now=datetime.utcnow(),
            enabled_platforms={"x", "threads"},
            publishers={"x": x, "threads": threads},
        )
        self.assertEqual(len(completed), 2)
        self.assertEqual(len(x.calls), 1)
        self.assertEqual(len(threads.calls), 1)
        self.assertEqual(
            self.db.query(SocialPublishJob).filter_by(status="published").count(),
            2,
        )
        self.assertEqual(
            publish_due_text_jobs(
                self.db,
                enabled_platforms={"x", "threads"},
                publishers={"x": x, "threads": threads},
            ),
            [],
        )

    def test_daily_text_job_reuses_one_image_for_x_and_threads(self):
        self.trivia.image_url = "https://cdn.example/octopus.png"
        self.db.commit()
        shared_text = (
            "タコの心臓は一つでは足りません。実は三つあります。"
            "二つがえらへ、残る一つが全身へ血液を送ります。 #雑学"
        )
        content = {
            "automation": {"mode": "daily_text"},
            "x": {"text": shared_text},
            "threads": {"text": shared_text, "topic_tag": "雑学"},
            "shared_image": {
                "url": self.trivia.image_url,
                "alt_text": "海中にいるタコの姿を撮影した画像",
            },
        }
        job = create_daily_text_job(self.db, generator=lambda trivia: content)
        x = FakePublisher()
        threads = FakePublisher()

        completed = publish_due_text_jobs(
            self.db,
            enabled_platforms={"x", "threads"},
            publishers={"x": x, "threads": threads},
            content_job_id=job.id,
        )

        self.assertEqual(job.status, "approved")
        self.assertEqual(job.video_jobs, [])
        self.assertEqual(len(completed), 2)
        self.assertEqual(x.calls[0][1], self.trivia.image_url)
        self.assertEqual(threads.calls[0][2], self.trivia.image_url)

    def test_line_review_contains_video_and_explicit_approval(self):
        content_job = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        video_job = content_job.video_jobs[0]
        video_job.status = "ready"
        video_job.final_video_url = "https://cdn.example/video.mp4"
        video_job.thumbnail_url = "https://cdn.example/preview.png"
        video_job.duration_seconds = 21.5
        self.db.commit()

        messages = social_review_messages(content_job, video_job)

        self.assertEqual(messages[0]["type"], "video")
        self.assertIn("【脚本】", messages[1]["text"])
        self.assertIn("【Instagram】", messages[1]["text"])
        approval = messages[2]["contents"]["footer"]["contents"][0]["action"]
        self.assertEqual(approval["type"], "postback")
        self.assertIn(f"content_job_id={content_job.id}", approval["data"])

    def test_line_video_preview_is_exactly_nine_by_sixteen(self):
        source = BytesIO()
        Image.new("RGB", (1024, 1536), "navy").save(source, format="PNG")

        preview = make_line_video_preview(source.getvalue())

        with Image.open(BytesIO(preview)) as image:
            self.assertEqual(image.size, (720, 1280))
            self.assertEqual(image.format, "JPEG")

    def test_approved_video_jobs_submit_then_finish_without_duplicates(self):
        content_job = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        video_job = content_job.video_jobs[0]
        video_job.status = "ready"
        video_job.final_video_url = "https://cdn.example/video.mp4"
        self.db.commit()
        approve_content_job(self.db, content_job.id)
        instagram = FakeInstagramPublisher()
        tiktok = FakeTikTokPublisher()
        publishers = {"instagram": instagram, "tiktok": tiktok}

        process_due_video_jobs(
            self.db,
            enabled_platforms={"instagram", "tiktok"},
            publishers=publishers,
        )
        self.assertEqual(len(instagram.submissions), 1)
        self.assertEqual(len(tiktok.submissions), 1)
        self.assertEqual(
            self.db.query(SocialPublishJob).filter_by(content_type="video", status="publishing").count(),
            2,
        )

        process_due_video_jobs(
            self.db,
            enabled_platforms={"instagram", "tiktok"},
            publishers=publishers,
        )
        self.assertEqual(len(instagram.submissions), 1)
        self.assertEqual(len(tiktok.submissions), 1)
        self.assertEqual(
            self.db.query(SocialPublishJob).filter_by(content_type="video", status="published").count(),
            2,
        )


if __name__ == "__main__":
    unittest.main()
