import base64
import importlib.util
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Iterable

import requests
from openai import OpenAI
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


# 720p is accepted by short-video platforms and keeps the complete rendering
# pipeline within small Render instances. 1080p x264 encoding can exceed 512 MB.
WIDTH = 720
HEIGHT = 1280
FPS = 30


def generate_social_image(prompt: str, client: OpenAI | None = None) -> bytes:
    client = client or OpenAI(api_key=_openai_key())
    response = client.images.generate(
        model=os.getenv("SOCIAL_IMAGE_MODEL", "gpt-image-1-mini"),
        prompt=(
            "Create a visually striking editorial illustration for a Japanese trivia short video. "
            "Vertical composition, clear central subject, realistic details, safe for all audiences. "
            f"{prompt} No text, letters, captions, logos, or watermarks."
        ),
        size="1024x1536",
        quality=os.getenv("SOCIAL_IMAGE_QUALITY", "low"),
        n=1,
    )
    encoded = response.data[0].b64_json
    if not encoded:
        raise RuntimeError("Image API returned no image data")
    return base64.b64decode(encoded)


def generate_narration_audio(lines: Iterable[str], client: OpenAI | None = None) -> bytes:
    text = "\n".join(str(line).strip() for line in lines if str(line).strip())
    if not text:
        raise ValueError("Narration is empty")
    client = client or OpenAI(api_key=_openai_key())
    response = client.audio.speech.create(
        model=os.getenv("SOCIAL_TTS_MODEL", "tts-1"),
        voice=os.getenv("SOCIAL_TTS_VOICE", "alloy"),
        input=text,
        response_format="mp3",
    )
    return response.read() if hasattr(response, "read") else response.content


def download_image(url: str, session=requests) -> bytes:
    if not url.startswith(("http://", "https://")):
        base_url = os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            raise ValueError("Relative image URL requires TRIVIA_IMAGE_R2_BASE_URL")
        url = f"{base_url}/{url.lstrip('/')}"
    response = session.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if content_type and not content_type.startswith("image/"):
        raise ValueError(f"Expected an image but received {content_type}")
    if len(response.content) > 15 * 1024 * 1024:
        raise ValueError("Source image exceeds 15 MB")
    return response.content


def load_background_music(location: str | None = None, session=requests) -> bytes | None:
    """Load one reusable, cross-platform licensed BGM track when configured."""
    location = (location or os.getenv("SOCIAL_BGM_URL", "")).strip()
    if not location:
        return None
    if location.startswith(("http://", "https://")):
        response = session.get(location, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if content_type and not (content_type.startswith("audio/") or "octet-stream" in content_type):
            raise ValueError(f"Expected audio but received {content_type}")
        data = response.content
    else:
        data = Path(location).read_bytes()
    if not data:
        raise ValueError("Background music is empty")
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Background music exceeds 20 MB")
    return data


def compose_static_video(
    image_data: bytes | list[bytes],
    title: str,
    subtitles: list[str],
    output_path: str | Path,
    *,
    audio_data: bytes | None = None,
    narration: list[str] | None = None,
    scenes: list[dict] | None = None,
    background_music_data: bytes | None = None,
) -> float:
    """Create a low-memory vertical MP4 with one animated still per scene."""
    if not subtitles:
        raise ValueError("At least one subtitle is required")
    narration_text = "".join(narration or subtitles)
    if scenes and len(scenes) == len(subtitles):
        scene_durations = [max(2.0, min(float(scene.get("duration", 5)), 8.0)) for scene in scenes]
        motions = [str(scene.get("motion", "zoom_in")) for scene in scenes]
    else:
        duration = max(12.0, min(45.0, len(narration_text) / 5.0 + 2.0))
        scene_durations = [duration / len(subtitles)] * len(subtitles)
        motions = ["zoom_in" if index % 2 == 0 else "pan_right" for index in range(len(subtitles))]
    duration = sum(scene_durations)
    images = image_data if isinstance(image_data, list) else [image_data]
    if not images or any(not item for item in images):
        raise ValueError("At least one image is required")
    images = [images[min(index, len(images) - 1)] for index in range(len(subtitles))]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="daily-trivia-video-") as temp_dir:
        temp = Path(temp_dir)
        clip_paths = []
        for index, (raw_image, subtitle, scene_duration, motion) in enumerate(
            zip(images, subtitles, scene_durations, motions)
        ):
            frame_path = temp / f"frame-{index:02d}.jpg"
            with Image.open(BytesIO(raw_image)) as opened:
                source = ImageOps.exif_transpose(opened).convert("RGB")
                card = _render_card(source, title, subtitle, index, len(subtitles))
                try:
                    card.save(frame_path, "JPEG", quality=88, optimize=True)
                finally:
                    card.close()
                    source.close()
            clip_path = temp / f"scene-{index:02d}.mp4"
            clip_command = [
                _ffmpeg_executable(), "-y", "-loop", "1", "-i", str(frame_path),
                "-vf", _motion_filter(motion, scene_duration),
                "-t", f"{scene_duration:.3f}", "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-threads", "1",
                "-x264-params", "ref=1:bframes=0:rc-lookahead=0",
                "-crf", "23", "-pix_fmt", "yuv420p", str(clip_path),
            ]
            _run_ffmpeg(clip_command)
            clip_paths.append(clip_path)

        concat_path = temp / "clips.txt"
        lines = [
            f"file '{path.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
            for path in clip_paths
        ]
        concat_path.write_text("\n".join(lines), encoding="utf-8")

        command = [
            _ffmpeg_executable(), "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_path),
        ]
        if audio_data:
            audio_path = temp / "narration.mp3"
            audio_path.write_bytes(audio_data)
            command.extend(["-i", str(audio_path)])
        if background_music_data:
            bgm_path = temp / "background-music.mp3"
            bgm_path.write_bytes(background_music_data)
            command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        command.extend(["-map", "0:v:0", "-c:v", "copy", "-movflags", "+faststart"])
        if audio_data and background_music_data:
            command.extend([
                "-filter_complex",
                "[1:a]volume=1.0[voice];[2:a]volume=0.10[bgm];"
                "[voice][bgm]amix=inputs=2:duration=longest:dropout_transition=2[a]",
                "-map", "[a]", "-c:a", "aac", "-b:a", "128k",
            ])
        elif audio_data:
            command.extend(["-map", "1:a:0", "-c:a", "aac", "-b:a", "128k"])
        elif background_music_data:
            command.extend(["-map", "1:a:0", "-c:a", "aac", "-b:a", "128k"])
        else:
            command.extend(["-an"])
        command.extend(["-t", f"{duration:.3f}"])
        command.append(str(output_path))
        _run_ffmpeg(command)
    return duration


def _motion_filter(motion: str, duration: float) -> str:
    frames = max(1, round(duration * FPS))
    progress = f"on/{max(1, frames - 1)}"
    if motion == "zoom_out":
        zoom, x, y = f"1.08-0.08*{progress}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        zoom, x, y = "1.08", f"(iw-iw/zoom)*(1-{progress})", "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        zoom, x, y = "1.08", f"(iw-iw/zoom)*{progress}", "ih/2-(ih/zoom/2)"
    else:
        zoom, x, y = f"1+0.08*{progress}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-1500:]}")


def _render_card(source: Image.Image, title: str, subtitle: str, index: int, total: int) -> Image.Image:
    fitted = ImageOps.fit(source, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
    background = fitted.filter(ImageFilter.GaussianBlur(_scale(22)))
    fitted.close()
    dimmed = ImageEnhance.Brightness(background).enhance(0.48)
    background.close()
    background = dimmed
    foreground = ImageOps.contain(
        source,
        (WIDTH - _scale(100), _scale(1180)),
        method=Image.Resampling.LANCZOS,
    )
    canvas = background.copy()
    canvas.paste(
        foreground,
        ((WIDTH - foreground.width) // 2, _scale(260)),
        foreground if foreground.mode == "RGBA" else None,
    )
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        (_scale(55), _scale(65), WIDTH - _scale(55), _scale(230)),
        radius=_scale(32), fill=(8, 12, 20, 205),
    )
    draw.rounded_rectangle(
        (_scale(55), _scale(1250), WIDTH - _scale(55), _scale(1625)),
        radius=_scale(38), fill=(8, 12, 20, 225),
    )
    progress_left = _scale(55)
    progress_right = WIDTH - _scale(55)
    progress_y = _scale(245)
    draw.rounded_rectangle(
        (progress_left, progress_y, progress_right, progress_y + _scale(12)),
        radius=_scale(6), fill=(255, 255, 255, 80),
    )
    draw.rounded_rectangle(
        (
            progress_left,
            progress_y,
            progress_left + (progress_right - progress_left) * (index + 1) / total,
            progress_y + _scale(12),
        ),
        radius=_scale(6), fill=(255, 224, 92, 235),
    )
    font_title = _font(_scale(50))
    font_subtitle = _font(_scale(72))
    font_small = _font(_scale(30))
    _draw_centered(draw, _wrap(title, 17), _scale(100), font_title, fill="white", spacing=_scale(10))
    _draw_centered(draw, _wrap(subtitle, 12), _scale(1320), font_subtitle, fill="#fff4a8", spacing=_scale(16))
    draw.text(
        (WIDTH - _scale(145), _scale(1665)),
        f"{index + 1}/{total}",
        font=font_small,
        fill=(255, 255, 255, 190),
    )
    canvas_rgba = canvas.convert("RGBA")
    composited = Image.alpha_composite(canvas_rgba, overlay)
    result = composited.convert("RGB")
    for image in (background, foreground, canvas, overlay, canvas_rgba, composited):
        image.close()
    return result


def _scale(value: int) -> int:
    return max(1, round(value * WIDTH / 1080))


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, font, **kwargs) -> None:
    box = draw.multiline_textbbox((0, 0), text, font=font, align="center", **{k: v for k, v in kwargs.items() if k == "spacing"})
    x = (WIDTH - (box[2] - box[0])) / 2
    draw.multiline_text((x, y), text, font=font, align="center", stroke_width=2, stroke_fill="#000000", **kwargs)


def _wrap(text: str, width: int) -> str:
    value = str(text).strip()
    return "\n".join(value[index:index + width] for index in range(0, len(value), width))


def _font(size: int):
    configured = os.getenv("SOCIAL_VIDEO_FONT_PATH", "").strip()
    here = Path(__file__).resolve()
    candidates = [
        Path(configured) if configured else None,
        here.parents[2] / "mobile" / "assets" / "fonts" / "DotGothic16-Regular.ttf",
        *_packaged_japanese_fonts(),
        Path("C:/Windows/Fonts/meiryo.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            try:
                # Loading by path fails on some Pillow/FreeType builds when
                # the Windows workspace path contains Japanese characters.
                return ImageFont.truetype(BytesIO(candidate.read_bytes()), size)
            except OSError:
                # Ignore a corrupt optional font and continue to the bundled
                # IPA/system fallback.
                continue
    raise RuntimeError("Japanese video font not found; set SOCIAL_VIDEO_FONT_PATH")


def _packaged_japanese_fonts() -> list[Path]:
    # japanize-matplotlib ships IPAex Gothic. Resolve it without importing the
    # package, whose plotting integration is irrelevant to video rendering.
    spec = importlib.util.find_spec("japanize_matplotlib")
    if not spec or not spec.submodule_search_locations:
        return []
    package_dir = Path(next(iter(spec.submodule_search_locations)))
    return [package_dir / "fonts" / "ipaexg.ttf"]


def _ffmpeg_executable() -> str:
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return configured
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError("Install imageio-ffmpeg or set FFMPEG_PATH") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def _openai_key() -> str:
    value = os.getenv("OPENAI_API_KEY", "").strip()
    if not value:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return value
