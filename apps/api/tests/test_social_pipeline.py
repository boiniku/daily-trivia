import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, SocialPublishJob, SocialVideoJob, Trivia
from services.seedance import SeedanceClient, SeedanceTask
from services.social_content import normalize_social_content, trim_for_x, x_weighted_length
from services.static_video import compose_static_video
from services.social_pipeline import (
    approve_content_job,
    create_content_job,
    poll_seedance_job,
    publish_due_text_jobs,
    render_static_video_job,
    submit_seedance_job,
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


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


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


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, *args):
        self.calls.append(args)
        return SimpleNamespace(remote_post_id="remote-1", remote_post_url="https://example.com/post")


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

    def test_normalization_clamps_seedance_duration_and_adds_guard(self):
        content = sample_content()
        content["video"]["visual_prompts"][1]["duration"] = 50
        normalized = normalize_social_content(content)
        self.assertEqual(normalized["video"]["visual_prompts"][1]["duration"], 15)
        self.assertIn("No text", normalized["video"]["visual_prompts"][1]["prompt"])

    def test_seedance_client_sends_vertical_silent_video(self):
        session = FakeHttpSession()
        client = SeedanceClient(api_key="test", base_url="https://ark.example/v3", session=session)
        created = client.create_video("A quiet ocean", duration=8, model="seedance-test")
        fetched = client.get_task(created.id)
        payload = session.requests[0][2]["json"]
        self.assertEqual(payload["ratio"], "9:16")
        self.assertFalse(payload["generate_audio"])
        self.assertEqual(fetched.video_url, "https://example.com/video.mp4")

    def test_create_job_is_idempotent_and_creates_platform_jobs(self):
        first = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        second = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(first.publish_jobs), 4)
        self.assertEqual(len(first.video_jobs), 1)
        self.assertEqual(first.video_jobs[0].provider, "static")

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
                    source.getvalue(),
                    "タコの心臓",
                    ["タコには", "心臓が3つあります"],
                    output_path,
                    narration=["タコには心臓が3つあります"],
                )
            self.assertGreaterEqual(duration, 12)
            self.assertTrue(output_path.read_bytes().startswith(b"\x00\x00\x00"))

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

    def test_approved_text_jobs_publish_once(self):
        content_job = create_content_job(self.db, self.trivia.id, generator=lambda trivia: sample_content())
        approve_content_job(self.db, content_job.id)
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


if __name__ == "__main__":
    unittest.main()
