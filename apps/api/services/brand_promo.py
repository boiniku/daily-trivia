import math
import os
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from services.static_video import _ffmpeg_executable, _font


WIDTH = 720
HEIGHT = 1280
FPS = 30
DURATION_SECONDS = 5


def generate_brand_promo_video(output_path: str | Path) -> float:
    """Render the reusable, silent Daily Trivia promo clip."""
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
        for frame_index in range(FPS * DURATION_SECONDS):
            frame = _render_frame(frame_index / FPS)
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
        raise RuntimeError(f"Brand promo FFmpeg failed: {stderr[-1500:]}")
    return float(DURATION_SECONDS)


def _render_frame(time_seconds: float) -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#090d18")
    draw = ImageDraw.Draw(canvas)
    _background(draw, time_seconds)
    if time_seconds < 1.65:
        _frequency_scene(draw, time_seconds / 1.65)
    elif time_seconds < 3.45:
        _widget_scene(draw, (time_seconds - 1.65) / 1.8)
    else:
        _brand_scene(canvas, draw, (time_seconds - 3.45) / 1.55)
    return canvas


def _background(draw: ImageDraw.ImageDraw, time_seconds: float) -> None:
    shift = int(25 * math.sin(time_seconds * 1.4))
    draw.ellipse((-250 + shift, -180, 420 + shift, 490), fill="#23111a")
    draw.ellipse((420 - shift, 850, 940 - shift, 1370), fill="#171326")
    draw.rounded_rectangle((45, 50, 675, 1230), radius=56, outline="#2b3140", width=2)


def _frequency_scene(draw: ImageDraw.ImageDraw, progress: float) -> None:
    eased = _ease_out(progress)
    y_offset = int((1 - eased) * 70)
    _center(draw, "毎日", 205 + y_offset, _font(54), "#ffffff")
    _center(draw, "3つ", 310 + y_offset, _font(154), "#ff3737")
    _center(draw, "新しい雑学が届く", 520 + y_offset, _font(54), "#fff5d8")
    labels = (("朝", "#ff9f75"), ("昼", "#ffca4b"), ("夜", "#7769dd"))
    for index, (label, color) in enumerate(labels):
        delay = index * 0.1
        local = _ease_out(max(0, min(1, (progress - delay) * 2.2)))
        size = int(132 * local)
        if size <= 4:
            continue
        center_x = 190 + index * 170
        top = 760 - size // 2
        box = (center_x - size // 2, top, center_x + size // 2, top + size)
        draw.rounded_rectangle(box, radius=max(2, size // 3), fill=color)
        _center_in_box(draw, label, box, _font(max(10, int(48 * local))), "#11131a")
    _center(draw, "朝・昼・夜、ちょっと賢く", 965, _font(38), "#ffffff")


def _widget_scene(draw: ImageDraw.ImageDraw, progress: float) -> None:
    eased = _ease_out(progress)
    _center(draw, "アプリを開かなくても", 150, _font(43), "#ffffff")
    _center(draw, "ウィジェットで見られる", 220, _font(54), "#fff0a0")
    card_y = int(430 + (1 - eased) * 90)
    draw.rounded_rectangle((88, card_y + 18, 632, card_y + 458), radius=42, fill="#000000")
    card = (70, card_y, 650, card_y + 440)
    draw.rounded_rectangle(card, radius=42, fill="#fff5e8")
    draw.ellipse((108, card_y + 45, 154, card_y + 91), fill="#ff1616")
    draw.text((172, card_y + 48), "毎日雑学", font=_font(31), fill="#222222")
    draw.text((110, card_y + 130), "今日の雑学", font=_font(29), fill="#a34b3c")
    draw.text((110, card_y + 185), "タコの心臓は", font=_font(49), fill="#171717")
    draw.text((110, card_y + 255), "3つある", font=_font(66), fill="#e21f26")
    draw.text((110, card_y + 360), "次の雑学はお昼に更新", font=_font(27), fill="#66605b")
    _center(draw, "ホーム画面で、すぐ『へぇ』", 1030, _font(39), "#ffffff")


def _brand_scene(canvas: Image.Image, draw: ImageDraw.ImageDraw, progress: float) -> None:
    icon = _load_icon()
    if icon:
        target = int(250 * _ease_out(progress))
        if target > 4:
            icon.thumbnail((target, target), Image.Resampling.LANCZOS)
            canvas.paste(icon, ((WIDTH - icon.width) // 2, 225), icon)
        icon.close()
    _center(draw, "毎日雑学", 570, _font(88), "#ffffff")
    _center(draw, "毎日3つの雑学を", 740, _font(43), "#fff0a0")
    _center(draw, "ウィジェットで。", 810, _font(53), "#fff0a0")
    button = (125, 970, 595, 1070)
    draw.rounded_rectangle(button, radius=50, fill="#ff1717")
    _center_in_box(draw, "毎日に、新しい『へぇ』を", button, _font(34), "#ffffff")


def _load_icon() -> Image.Image | None:
    configured = os.getenv("SOCIAL_BRAND_ICON_PATH", "").strip()
    here = Path(__file__).resolve()
    candidates = [
        Path(configured) if configured else None,
        here.parents[2] / "mobile" / "assets" / "icon.png",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            try:
                return Image.open(BytesIO(candidate.read_bytes())).convert("RGBA")
            except OSError:
                continue
    return None


def _center(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.FreeTypeFont, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font, stroke_width=1)
    x = (WIDTH - (box[2] - box[0])) // 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=1, stroke_fill="#05070c")


def _center_in_box(draw: ImageDraw.ImageDraw, text: str, box, font: ImageFont.FreeTypeFont, fill) -> None:
    text_box = draw.textbbox((0, 0), text, font=font)
    width = text_box[2] - text_box[0]
    height = text_box[3] - text_box[1]
    x = box[0] + (box[2] - box[0] - width) // 2
    y = box[1] + (box[3] - box[1] - height) // 2 - text_box[1]
    draw.text((x, y), text, font=font, fill=fill)


def _ease_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3
