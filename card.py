from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).parent / "assets"
W, H = 934, 282
SS = 2
BG = (30, 31, 34)
PANEL = (43, 45, 49)
TRACK = (64, 66, 73)
TEXT = (242, 243, 245)
MUTED = (148, 155, 164)


@lru_cache
def font(weight, size):
    return ImageFont.truetype(str(ASSETS / f"Pretendard-{weight}.otf"), size * SS)


def short(n):
    for unit, div in (("M", 1_000_000), ("K", 1_000)):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + unit
    return str(n)


def drawable(f, text):
    missing = f.getmask("\U0010FFFD").getbbox()
    return "".join(c for c in text if c.isspace() or f.getmask(c).getbbox() != missing).strip()


def fit(draw, f, text, width):
    if draw.textlength(text, font=f) <= width:
        return text
    while text and draw.textlength(text + "…", font=f) > width:
        text = text[:-1]
    return text + "…"


def s(v):
    return round(v * SS)


def render(name, fallback_name, avatar, rank, level, xp, need, points, accent):
    img = Image.new("RGBA", (s(W), s(H)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s(W), s(H)), s(28), fill=BG)
    d.rounded_rectangle((s(16), s(16), s(W - 16), s(H - 16)), s(20), fill=PANEL)

    size = 184
    ax, ay = 46, (H - size) // 2
    d.ellipse((s(ax - 6), s(ay - 6), s(ax + size + 6), s(ay + size + 6)), fill=accent)
    mask = Image.new("L", (s(size), s(size)), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, s(size), s(size)), fill=255)
    if avatar:
        face = Image.open(BytesIO(avatar)).convert("RGBA").resize((s(size), s(size)), Image.LANCZOS)
    else:
        face = Image.new("RGBA", (s(size), s(size)), TRACK)
    img.paste(face, (s(ax), s(ay)), mask)

    left, right = 270, W - 48
    big, label = font("Bold", 50), font("Medium", 24)
    x = s(right)
    for value, caption, color in ((str(level), "레벨", accent), (f"#{rank}", "순위", TEXT)):
        d.text((x, s(86)), value, font=big, fill=color, anchor="rs")
        x -= d.textlength(value, font=big) + s(10)
        d.text((x, s(86)), caption, font=label, fill=MUTED, anchor="rs")
        x -= d.textlength(caption, font=label) + s(30)

    name_font = font("Bold", 38)
    shown = drawable(name_font, name) or drawable(name_font, fallback_name) or "?"
    xp_text = f"{short(xp)} / {short(need)} XP"
    xp_font = font("Medium", 26)
    name_width = s(right - left) - d.textlength(xp_text, font=xp_font) - s(24)
    d.text((s(left), s(158)), fit(d, name_font, shown, name_width), font=name_font, fill=TEXT, anchor="ls")
    d.text((s(right), s(158)), xp_text, font=xp_font, fill=MUTED, anchor="rs")

    top, bottom = 174, 210
    d.rounded_rectangle((s(left), s(top), s(right), s(bottom)), s(18), fill=TRACK)
    filled = left + (right - left) * xp / need
    if filled - left >= bottom - top:
        d.rounded_rectangle((s(left), s(top), s(filled), s(bottom)), s(18), fill=accent)
    elif xp:
        d.ellipse((s(left), s(top), s(left + bottom - top), s(bottom)), fill=accent)

    d.text((s(left), s(246)), f"포인트 {points:,}", font=font("Medium", 24), fill=MUTED, anchor="ls")

    out = BytesIO()
    img.resize((W, H), Image.LANCZOS).save(out, "PNG")
    out.seek(0)
    return out
