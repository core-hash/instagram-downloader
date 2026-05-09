"""Genera iconos PWA y OG con el logo (sparkle bezier sharp)."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os

VIOLET_LIGHT = (196, 181, 253)
PINK = (244, 114, 182)
AMBER = (251, 191, 36)
BG_DARK = (10, 10, 15)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_color(t):
    if t < 0.5:
        return lerp(VIOLET_LIGHT, PINK, t * 2)
    return lerp(PINK, AMBER, (t - 0.5) * 2)


def sparkle_outline(cx, cy, size, points_per_side=40):
    """4-point sparkle: sharp tips, concave Bezier sides."""
    s = size / 2
    tips_unit = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    pts = []
    pull = 0.18
    for i in range(4):
        a = tips_unit[i]
        b = tips_unit[(i + 1) % 4]
        midx = (a[0] + b[0]) / 2
        midy = (a[1] + b[1]) / 2
        cx_ctrl = midx * pull
        cy_ctrl = midy * pull
        for j in range(points_per_side):
            t = j / points_per_side
            x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * cx_ctrl + t ** 2 * b[0]
            y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * cy_ctrl + t ** 2 * b[1]
            pts.append((cx + x * s, cy + y * s))
    return pts


def draw_sparkle(img, cx, cy, size, with_glow=True):
    draw = ImageDraw.Draw(img, "RGBA")

    if with_glow:
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow_layer)
        gpts = sparkle_outline(cx, cy, size * 1.4)
        gdraw.polygon(gpts, fill=(*PINK, 80))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(int(size * 0.08)))
        img.alpha_composite(glow_layer)

    points = sparkle_outline(cx, cy, size)

    # Mask for the sparkle
    mask = Image.new("L", img.size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.polygon(points, fill=255)

    # Build vertical gradient covering the bbox
    bbox = mask.getbbox()
    if not bbox:
        return
    grad = Image.new("RGB", img.size, BG_DARK)
    gdraw = ImageDraw.Draw(grad)
    x1, y1, x2, y2 = bbox
    h = y2 - y1
    for i in range(h):
        t = i / max(1, h - 1)
        color = gradient_color(t)
        gdraw.line([(x1, y1 + i), (x2, y1 + i)], fill=color)
    grad_rgba = grad.convert("RGBA")
    grad_rgba.putalpha(mask)
    img.alpha_composite(grad_rgba)


def make_icon(size, fname, rounded=False, padding_pct=0.18, with_bg=True):
    if with_bg:
        img = Image.new("RGBA", (size, size), BG_DARK + (255,))
    else:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    sparkle_size = size * (1 - 2 * padding_pct)
    draw_sparkle(img, size / 2, size / 2, sparkle_size, with_glow=size >= 192)

    if rounded:
        mask = Image.new("L", (size, size), 0)
        mdraw = ImageDraw.Draw(mask)
        radius = int(size * 0.22)
        mdraw.rounded_rectangle([(0, 0), (size, size)], radius=radius, fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        img = out

    out_path = os.path.join(os.path.dirname(__file__), fname)
    img.save(out_path, "PNG", optimize=True)
    print(f"Wrote {out_path} ({os.path.getsize(out_path) // 1024} KB)")


def find_font(size):
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_og_image():
    W, H = 1200, 630
    img = Image.new("RGBA", (W, H), BG_DARK + (255,))

    def radial_glow(size, color, intensity=0.4):
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = size[0] // 2, size[1] // 2
        max_r = max(size) // 2
        for r in range(max_r, 0, -8):
            alpha = int(255 * intensity * (1 - r / max_r) ** 1.4)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, alpha))
        return layer.filter(ImageFilter.GaussianBlur(40))

    glow1 = radial_glow((900, 700), VIOLET_LIGHT, intensity=0.55)
    img.alpha_composite(glow1, dest=(-200, -200))
    glow2 = radial_glow((800, 600), AMBER, intensity=0.32)
    img.alpha_composite(glow2, dest=(700, 200))
    glow3 = radial_glow((700, 500), PINK, intensity=0.25)
    img.alpha_composite(glow3, dest=(300, 300))

    # Big sparkle on the right
    draw_sparkle(img, W - 250, H / 2, 380, with_glow=True)

    draw = ImageDraw.Draw(img, "RGBA")
    title_font = find_font(140)
    sub_font = find_font(40)
    small_font = find_font(24)

    draw.text((80, H / 2 - 130), "muse", font=title_font, fill=(245, 245, 247))
    draw.text((80, H / 2 + 25), "Guarda lo que te inspira.", font=sub_font, fill=PINK)
    draw.text(
        (80, H / 2 + 80),
        "Instagram · TikTok · X · Reddit · Pinterest",
        font=small_font,
        fill=(139, 139, 149),
    )
    draw.text((80, H - 60), "muse-co.pages.dev", font=small_font, fill=AMBER)

    out_path = os.path.join(os.path.dirname(__file__), "og-image.png")
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    print(f"Wrote {out_path} ({os.path.getsize(out_path) // 1024} KB)")


def main():
    make_icon(192, "icon-192.png", rounded=False, with_bg=True)
    make_icon(512, "icon-512.png", rounded=False, with_bg=True)
    make_icon(180, "apple-touch-icon.png", rounded=True, with_bg=True)
    make_icon(512, "icon-512-maskable.png", rounded=False, padding_pct=0.22, with_bg=True)
    make_og_image()


if __name__ == "__main__":
    main()
