import os
from PIL import Image, ImageDraw, ImageFont

# Constants
W, H = 320, 150
OUTPUT_DIR = "assets/widgets"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Try fetching fonts
try:
    font_bold = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 20)
    font_normal = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 13)
    font_small = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", 12)
    font_dot_bold = ImageFont.truetype("assets/fonts/DotGothic16-Regular.ttf", 20)
    font_dot_normal = ImageFont.truetype("assets/fonts/DotGothic16-Regular.ttf", 13)
    font_dot_small = ImageFont.truetype("assets/fonts/DotGothic16-Regular.ttf", 10)
except Exception:
    font_bold = ImageFont.load_default()
    font_normal = ImageFont.load_default()
    font_small = ImageFont.load_default()
    font_dot_bold = font_bold
    font_dot_normal = font_normal
    font_dot_small = font_small

def create_base(bg_color):
    return Image.new("RGBA", (W, H), bg_color)

def draw_badge(draw, text, x, y, bg_color, text_color, font, border_color=None, border_width=0, is_rpg=False):
    # Calculate text size using textbbox
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    pad_x, pad_y = 8, 4
    if is_rpg:
        pad_x, pad_y = 10, 5

    rect = [x, y, x + text_w + pad_x*2, y + text_h + pad_y*2]
    
    # Draw border
    if border_color and border_width > 0:
        draw.rectangle([rect[0]-border_width, rect[1]-border_width, rect[2]+border_width, rect[3]+border_width], fill=border_color)
    
    # Draw background
    if not is_rpg:
        # Rounded rectangle equivalent
        draw.rounded_rectangle(rect, radius=8, fill=bg_color)
    else:
        draw.rectangle(rect, fill=bg_color)
        
    # Draw text
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=text_color)

def draw_text_with_shadow(draw, text, x, y, font, color, shadow_color=None, max_lines=4, line_spacing=4):
    if shadow_color:
        draw.text((x, y+1), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=color, spacing=line_spacing)

# ---------------------------------------------------------
# LIGHT THEME
# ---------------------------------------------------------
img = create_base("#FFFFFF")
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, W-1, H-1], radius=22, outline="#EAEAEA", width=2)
draw_badge(draw, "💡 毎日雑学", 16, 16, "#F2F2F2", "#333333", font_small)
draw.text((16, 50), "富士山の高さ", font=font_bold, fill="#1A1A1A")
draw.text((16, 80), "富士山の高さは3776メートルです。", font=font_normal, fill="#4D4D4D")
img.save(f"{OUTPUT_DIR}/light.png")

# ---------------------------------------------------------
# DARK THEME
# ---------------------------------------------------------
img = create_base("#1C1C1E")
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, W-1, H-1], radius=22, outline="#2C2C2E", width=1)
draw_badge(draw, "💡 毎日雑学", 16, 16, "#2B2B2B", "#E5E5EA", font_small)
draw.text((16, 50), "富士山の高さ", font=font_bold, fill="#FFFFFF")
draw.text((16, 80), "富士山の高さは3776メートルです。", font=font_normal, fill="#AEAEB2")
img.save(f"{OUTPUT_DIR}/dark.png")

# ---------------------------------------------------------
# GAMEBOY THEME
# ---------------------------------------------------------
img = create_base("#9BBC0F")
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([0, 0, W-1, H-1], radius=6, outline="#0F380F", width=4)
draw_badge(draw, "DAILY TRIVIA", 16, 16, "#8BAC0F", "#0F380F", font_dot_small, border_color="#0F380F", border_width=2, is_rpg=True)
draw.text((16, 50), "富士山の高さ", font=font_dot_bold, fill="#0F380F")
draw.text((16, 80), "富士山の高さは3776メートルです。", font=font_dot_normal, fill="#0F380F", spacing=4)
img.save(f"{OUTPUT_DIR}/gameboy.png")

# ---------------------------------------------------------
# RPG THEME
# ---------------------------------------------------------
img = create_base("#000000")
draw = ImageDraw.Draw(img)
draw.rectangle([2, 2, W-3, H-3], outline="#FFFFFF", width=4)
draw_badge(draw, "▼ まいにちざつがく", 16, 16, "#000000", "#FFFFFF", font_dot_small, border_color="#FFFFFF", border_width=2, is_rpg=True)
draw.text((16, 55), "富士山の高さ", font=font_dot_bold, fill="#FFFFFF")
draw.text((16, 85), "ふじさんの たかさは\n3776メートル である！", font=font_dot_normal, fill="#FFFFFF", spacing=4)
img.save(f"{OUTPUT_DIR}/rpg.png")

# ---------------------------------------------------------
# STANDARD THEME - MORNING
# ---------------------------------------------------------
img = Image.new("RGBA", (W, H))
draw = ImageDraw.Draw(img)
for i in range(H):
    # gradient from #FFA366 to #FF9999
    r = int(255 + (255 - 255) * i / H)
    g = int(163 + (153 - 163) * i / H)
    b = int(102 + (153 - 102) * i / H)
    draw.line([(0, i), (W, i)], fill=(r, g, b, 255))
# Sun
draw.ellipse([W*0.8-50, H*0.3-50, W*0.8+50, H*0.3+50], fill=(255, 165, 0, 100))
draw_badge(draw, "☀️ おはよう雑学", 16, 16, (0,0,0,50), (255,255,255,230), font_small)
draw_text_with_shadow(draw, "富士山の高さ", 16, 50, font_bold, "#FFFFFF", (0,0,0,76))
draw_text_with_shadow(draw, "富士山の高さは3776メートルです。", 16, 80, font_normal, "#FFFFFF", (0,0,0,76))
# Apply clipping mask logic (rounded corners)
mask = Image.new("L", (W, H), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.rounded_rectangle([0, 0, W-1, H-1], radius=22, fill=255)
img.putalpha(mask)
img.save(f"{OUTPUT_DIR}/standard_morning.png")

# ---------------------------------------------------------
# STANDARD THEME - NOON
# ---------------------------------------------------------
img = Image.new("RGBA", (W, H))
draw = ImageDraw.Draw(img)
for i in range(H):
    # gradient from #66CCFF to #99E6FF
    r = int(102 + (153 - 102) * i / H)
    g = int(204 + (230 - 204) * i / H)
    b = int(255)
    draw.line([(0, i), (W, i)], fill=(r, g, b, 255))
# Clouds
draw.ellipse([0, 0, 60, 60], fill=(255, 255, 255, 150))
draw.ellipse([W-80, 10, W, 90], fill=(255, 255, 255, 180))
# Grass
draw.rounded_rectangle([0, H-15, W, H+15], radius=15, fill=(0, 128, 0, 150))
draw_badge(draw, "⛅️ こんにちは雑学", 16, 16, (0,0,0,50), (255,255,255,230), font_small)
draw_text_with_shadow(draw, "富士山の高さ", 16, 50, font_bold, "#FFFFFF", (0,0,0,76))
draw_text_with_shadow(draw, "富士山の高さは3776メートルです。", 16, 80, font_normal, "#FFFFFF", (0,0,0,76))
img.putalpha(mask)
img.save(f"{OUTPUT_DIR}/standard_noon.png")

# ---------------------------------------------------------
# STANDARD THEME - NIGHT
# ---------------------------------------------------------
img = Image.new("RGBA", (W, H))
draw = ImageDraw.Draw(img)
for i in range(H):
    # gradient from #1A1A66 to #333399
    r = int(26 + (51 - 26) * i / H)
    g = int(26 + (51 - 26) * i / H)
    b = int(102 + (153 - 102) * i / H)
    draw.line([(0, i), (W, i)], fill=(r, g, b, 255))
# Stars & Moon
draw.ellipse([18, 18, 22, 22], fill="#FFFF00")
draw.ellipse([98, 38, 101, 101], fill="#FFFF00")
draw.ellipse([W-32, 28, W-27, 33], fill="#FFFF00")
draw.ellipse([20, 20, 60, 60], fill=(255, 255, 0, 200))

draw_badge(draw, "🌙 こんばんは雑学", 16, 16, (0,0,0,50), (255,255,255,230), font_small)
draw_text_with_shadow(draw, "富士山の高さ", 16, 50, font_bold, "#FFFFFF", (0,0,0,76))
draw_text_with_shadow(draw, "富士山の高さは3776メートルです。", 16, 80, font_normal, "#FFFFFF", (0,0,0,76))
img.putalpha(mask)
img.save(f"{OUTPUT_DIR}/standard_night.png")

print("All 7 widget mockups have been generated.")
