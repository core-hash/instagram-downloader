"""Generates web/og-image.png — 1200x630 social-share preview for muse."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 1200, 630
BG = (10, 10, 15)
VIOLET = (167, 139, 250)
AMBER = (251, 191, 36)
WHITE = (245, 245, 247)
MUTED = (139, 139, 149)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def radial_glow(size, color, intensity=0.4):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = size[0] // 2, size[1] // 2
    max_r = max(size) // 2
    for r in range(max_r, 0, -8):
        alpha = int(255 * intensity * (1 - r / max_r) ** 1.4)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*color, alpha),
        )
    return layer.filter(ImageFilter.GaussianBlur(40))


def find_font(size, weight="Bold"):
    candidates = [
        f"/System/Library/Fonts/SFNS.ttf",
        f"/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        f"/System/Library/Fonts/Helvetica.ttc",
        f"/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_logo(img, x, y, scale):
    """Draw the M+arrow logo at (x,y) with scale (1.0 = 100x100 base)."""
    draw = ImageDraw.Draw(img, "RGBA")
    s = scale
    width = int(11 * s)

    pts_m = [(15, 78), (15, 25), (50, 58), (85, 25), (85, 78)]
    pts_arrow = [(38, 70), (50, 86), (62, 70)]

    def transform(pts):
        return [(x + p[0] * s, y + p[1] * s) for p in pts]

    def draw_path(pts):
        tr = transform(pts)
        draw.line(tr, fill=AMBER, width=width, joint="curve")
        for i, t in enumerate(tr):
            r = width // 2
            color = lerp(VIOLET, AMBER, i / max(1, len(tr) - 1))
            draw.ellipse([t[0] - r, t[1] - r, t[0] + r, t[1] + r], fill=color)

    def draw_gradient_path(pts):
        tr = transform(pts)
        for i in range(len(tr) - 1):
            t = i / max(1, len(tr) - 2)
            color = lerp(VIOLET, AMBER, t)
            x1, y1 = tr[i]
            x2, y2 = tr[i + 1]
            draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
            r = width // 2
            for px, py in [(x1, y1), (x2, y2)]:
                draw.ellipse([px - r, py - r, px + r, py + r], fill=color)

    draw_gradient_path(pts_m)
    draw_gradient_path(pts_arrow)


def main():
    img = Image.new("RGB", (W, H), BG)
    img = img.convert("RGBA")

    glow1 = radial_glow((900, 700), VIOLET, intensity=0.55)
    img.paste(glow1, (-200, -200), glow1)
    glow2 = radial_glow((800, 600), AMBER, intensity=0.30)
    img.paste(glow2, (700, 200), glow2)

    draw_logo(img, 80, 80, scale=1.6)

    draw = ImageDraw.Draw(img, "RGBA")

    title_font = find_font(140, "Bold")
    sub_font = find_font(42, "Regular")
    small_font = find_font(24, "Regular")

    draw.text((80, 280), "muse", font=title_font, fill=WHITE)

    spacer = title_font.getbbox("muse")[2]

    draw.text(
        (80, 280 + 145),
        "Guarda lo que te inspira.",
        font=sub_font,
        fill=VIOLET,
    )

    draw.text(
        (80, 280 + 145 + 70),
        "Posts · Reels · Carruseles · Stories — máxima calidad",
        font=small_font,
        fill=MUTED,
    )

    draw.text(
        (80, H - 70),
        "muse-co.pages.dev",
        font=small_font,
        fill=AMBER,
    )

    out_path = os.path.join(os.path.dirname(__file__), "og-image.png")
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    print(f"Wrote {out_path} ({os.path.getsize(out_path) // 1024} KB)")


if __name__ == "__main__":
    main()
