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


WIDTH = 1080
HEIGHT = 1920
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


def compose_static_video(
    image_data: bytes,
    title: str,
    subtitles: list[str],
    output_path: str | Path,
    *,
    audio_data: bytes | None = None,
    narration: list[str] | None = None,
) -> float:
    """Create a vertical H.264 MP4 from still subtitle cards."""
    if not subtitles:
        raise ValueError("At least one subtitle is required")
    narration_text = "".join(narration or subtitles)
    duration = max(12.0, min(45.0, len(narration_text) / 5.0 + 2.0))
    segment_duration = duration / len(subtitles)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="daily-trivia-video-") as temp_dir:
        temp = Path(temp_dir)
        frame_paths = []
        with Image.open(BytesIO(image_data)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            for index, subtitle in enumerate(subtitles):
                frame_path = temp / f"frame-{index:02d}.jpg"
                _render_card(source, title, subtitle, index, len(subtitles)).save(
                    frame_path, "JPEG", quality=91, optimize=True
                )
                frame_paths.append(frame_path)

        concat_path = temp / "frames.txt"
        lines = []
        for frame_path in frame_paths:
            safe_path = frame_path.as_posix().replace("'", "'\\''")
            lines.extend((f"file '{safe_path}'", f"duration {segment_duration:.4f}"))
        lines.append(f"file '{frame_paths[-1].as_posix()}'")
        concat_path.write_text("\n".join(lines), encoding="utf-8")

        command = [
            _ffmpeg_executable(), "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_path),
        ]
        if audio_data:
            audio_path = temp / "narration.mp3"
            audio_path.write_bytes(audio_data)
            command.extend(["-i", str(audio_path)])
        command.extend([
            "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
            "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ])
        if audio_data:
            command.extend(["-c:a", "aac", "-b:a", "128k", "-shortest"])
        else:
            command.extend(["-an", "-t", f"{duration:.3f}"])
        command.append(str(output_path))
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[-1500:]}")
    return duration


def _render_card(source: Image.Image, title: str, subtitle: str, index: int, total: int) -> Image.Image:
    background = ImageOps.fit(source, (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(22))
    background = ImageEnhance.Brightness(background).enhance(0.48)
    foreground = ImageOps.contain(source, (WIDTH - 100, 1180), method=Image.Resampling.LANCZOS)
    canvas = background.copy()
    canvas.paste(foreground, ((WIDTH - foreground.width) // 2, 260), foreground if foreground.mode == "RGBA" else None)
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((55, 65, WIDTH - 55, 230), radius=32, fill=(8, 12, 20, 205))
    draw.rounded_rectangle((55, 1500, WIDTH - 55, 1815), radius=38, fill=(8, 12, 20, 225))
    font_title = _font(50)
    font_subtitle = _font(72)
    font_small = _font(30)
    _draw_centered(draw, _wrap(title, 17), 100, font_title, fill="white", spacing=10)
    _draw_centered(draw, _wrap(subtitle, 12), 1570, font_subtitle, fill="#fff4a8", spacing=16)
    draw.text((WIDTH - 145, 1845), f"{index + 1}/{total}", font=font_small, fill=(255, 255, 255, 190))
    return Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")


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
