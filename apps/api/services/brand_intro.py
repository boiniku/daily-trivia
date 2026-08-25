import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from services.static_video import _ffmpeg_executable, _font


WIDTH = 720
HEIGHT = 1280
FPS = 30
DURATION_SECONDS = 1.0


def generate_brand_intro_video(output_path: str | Path) -> float:
    """Render the reusable one-second pattern-interrupt intro."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _ffmpeg_executable(), "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-threads", "1",
        "-x264-params", "ref=1:bframes=0:rc-lookahead=0",
        "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for index in range(round(FPS * DURATION_SECONDS)):
            frame = _render_frame(index / FPS)
            try:
                process.stdin.write(frame.tobytes())
            finally:
                frame.close()
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait(timeout=180)
    except Exception:
        process.kill()
        process.wait()
        raise
    if return_code != 0:
        raise RuntimeError(f"Brand intro FFmpeg failed: {stderr[-1500:]}")
    return DURATION_SECONDS


def _render_frame(time_seconds: float) -> Image.Image:
    progress = min(1.0, time_seconds / DURATION_SECONDS)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#070b14")
    draw = ImageDraw.Draw(canvas)

    # Immediate high-contrast first frame; no fade-in.
    pulse = 1 + 0.025 * math.sin(progress * math.pi * 5)
    radius = int(530 * pulse)
    draw.ellipse((-250, 110, -250 + radius * 2, 110 + radius * 2), fill="#241019")
    draw.polygon(((0, 1040), (720, 760), (720, 1280), (0, 1280)), fill="#151025")
    draw.rounded_rectangle((55, 65, 665, 1215), radius=54, outline="#343b4c", width=2)

    badge_width = int(190 * _ease_out(min(1, progress * 5)))
    if badge_width > 5:
        badge = (360 - badge_width // 2, 175, 360 + badge_width // 2, 245)
        draw.rounded_rectangle(badge, radius=35, fill="#ff2020")
        _center_in_box(draw, "今日の雑学", badge, _font(30), "#ffffff")

    first_progress = _ease_out(min(1, progress * 3.8))
    second_progress = _ease_out(max(0, min(1, (progress - 0.18) * 3.7)))
    first_y = int(365 + (1 - first_progress) * 90)
    second_y = int(585 + (1 - second_progress) * 120)
    _center_scaled(draw, "これ知ってたら", first_y, 67, first_progress, "#ffffff")
    _center_scaled(draw, "ちょっとすごい", second_y, 91, second_progress, "#fff09a")

    line_width = int(480 * _ease_out(max(0, min(1, (progress - 0.28) * 3))))
    if line_width:
        draw.rounded_rectangle(
            (360 - line_width // 2, 790, 360 + line_width // 2, 806),
            radius=8,
            fill="#ff2727",
        )
    _center(draw, "答えはこのあと", 920, _font(37), "#d5d9e4")
    return canvas


def _center_scaled(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font_size: int,
    progress: float,
    fill,
) -> None:
    if progress <= 0.02:
        return
    font = _font(max(8, int(font_size * (0.72 + 0.28 * progress))))
    _center(draw, text, y, font, fill)


def _center(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.FreeTypeFont, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    x = (WIDTH - (box[2] - box[0])) // 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=2, stroke_fill="#04060b")


def _center_in_box(draw: ImageDraw.ImageDraw, text: str, box, font: ImageFont.FreeTypeFont, fill) -> None:
    text_box = draw.textbbox((0, 0), text, font=font)
    x = box[0] + (box[2] - box[0] - (text_box[2] - text_box[0])) // 2
    y = box[1] + (box[3] - box[1] - (text_box[3] - text_box[1])) // 2 - text_box[1]
    draw.text((x, y), text, font=font, fill=fill)


def _ease_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3
