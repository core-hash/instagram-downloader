"""Generate Play Store assets: feature graphic + screenshot mocks."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import os, math

VIOLET_LIGHT = (196, 181, 253)
PINK = (244, 114, 182)
AMBER = (251, 191, 36)
BG_DARK = (10, 10, 15)
TEXT = (245, 245, 247)
MUTED = (139, 139, 149)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_color(t):
    if t < 0.5:
        return lerp(VIOLET_LIGHT, PINK, t * 2)
    return lerp(PINK, AMBER, (t - 0.5) * 2)


def sparkle_outline(cx, cy, size, points_per_side=160):
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
    if with_glow:
        glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow_layer)
        gpts = sparkle_outline(cx, cy, size * 1.4)
        gdraw.polygon(gpts, fill=(*PINK, 80))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(int(size * 0.08)))
        img.alpha_composite(glow_layer)

    points = sparkle_outline(cx, cy, size)
    mask = Image.new("L", img.size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.polygon(points, fill=255)

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


def radial_glow(size, color, intensity=0.4):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = size[0] // 2, size[1] // 2
    max_r = max(size) // 2
    for r in range(max_r, 0, -8):
        alpha = int(255 * intensity * (1 - r / max_r) ** 1.4)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, alpha))
    return layer.filter(ImageFilter.GaussianBlur(40))


def find_font(size, bold=True):
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


def make_feature_graphic():
    """Play Store feature graphic — 1024x500."""
    W, H = 1024, 500
    img = Image.new("RGBA", (W, H), BG_DARK + (255,))

    glow1 = radial_glow((800, 600), VIOLET_LIGHT, intensity=0.6)
    img.alpha_composite(glow1, dest=(-200, -200))
    glow2 = radial_glow((700, 500), AMBER, intensity=0.35)
    img.alpha_composite(glow2, dest=(600, 100))
    glow3 = radial_glow((600, 400), PINK, intensity=0.25)
    img.alpha_composite(glow3, dest=(200, 300))

    # Big sparkle right
    draw_sparkle(img, W - 220, H / 2, 320, with_glow=True)

    # Wordmark
    draw = ImageDraw.Draw(img, "RGBA")
    title_font = find_font(120)
    sub_font = find_font(36)
    small_font = find_font(22)

    draw.text((60, H / 2 - 110), "muse", font=title_font, fill=TEXT)
    muse_w = title_font.getbbox("muse")[2] - title_font.getbbox("muse")[0]
    draw.text((60 + muse_w - 8, H / 2 - 110), ".", font=title_font, fill=AMBER)
    draw.text((60, H / 2 + 20), "Guarda lo que te inspira", font=sub_font, fill=PINK)
    draw.text(
        (60, H / 2 + 70),
        "Instagram · TikTok · X · Reddit · Pinterest",
        font=small_font,
        fill=MUTED,
    )

    out_path = os.path.join(os.path.dirname(__file__), "playstore-feature.png")
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    print(f"✓ Feature graphic: {out_path} ({os.path.getsize(out_path) // 1024} KB)")


def make_screenshot_mock(idx, headline, sub):
    """1080x1920 portrait — phone screenshot mock."""
    W, H = 1080, 1920
    img = Image.new("RGBA", (W, H), BG_DARK + (255,))

    glow1 = radial_glow((1200, 800), VIOLET_LIGHT, intensity=0.4)
    img.alpha_composite(glow1, dest=(-300, -200))
    glow2 = radial_glow((1000, 700), AMBER, intensity=0.20)
    img.alpha_composite(glow2, dest=(300, 1000))

    # Sparkle decoration top
    draw_sparkle(img, W / 2, 300, 180, with_glow=True)

    draw = ImageDraw.Draw(img, "RGBA")
    title_font = find_font(98)
    sub_font = find_font(44)
    cta_font = find_font(38)
    label_font = find_font(28)

    # Headline
    bbox = title_font.getbbox(headline)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) / 2, 540), headline, font=title_font, fill=TEXT)

    # Sub
    bbox2 = sub_font.getbbox(sub)
    sw = bbox2[2] - bbox2[0]
    draw.text(((W - sw) / 2, 700), sub, font=sub_font, fill=PINK)

    # Mock card
    card_x, card_y, card_w, card_h = 90, 900, W - 180, 360
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([(0, 0), (card_w, card_h)], radius=32,
                          fill=(24, 24, 32, 230), outline=(38, 38, 47, 255), width=2)
    img.alpha_composite(card, dest=(card_x, card_y))

    # Inside card: input mock
    draw.text((card_x + 36, card_y + 40), "PEGA TU LINK", font=label_font, fill=MUTED)
    inp_y = card_y + 100
    draw.rounded_rectangle(
        [(card_x + 36, inp_y), (card_x + card_w - 36, inp_y + 90)],
        radius=18, fill=(0, 0, 0, 100), outline=(38, 38, 47, 255), width=2,
    )
    placeholder = "https://www.instagram.com/p/..."
    draw.text((card_x + 60, inp_y + 28), placeholder, font=cta_font, fill=(80, 80, 90))

    # Button
    btn_y = inp_y + 130
    btn_x1, btn_x2 = card_x + 36, card_x + card_w - 36
    btn_w = btn_x2 - btn_x1
    grad_btn = Image.new("RGB", (btn_w, 100))
    gd = ImageDraw.Draw(grad_btn)
    for i in range(btn_w):
        t = i / btn_w
        c = lerp(VIOLET_LIGHT, AMBER, t)
        gd.line([(i, 0), (i, 100)], fill=c)
    btn_mask = Image.new("L", (btn_w, 100), 0)
    bm = ImageDraw.Draw(btn_mask)
    bm.rounded_rectangle([(0, 0), (btn_w, 100)], radius=22, fill=255)
    btn_layer = grad_btn.convert("RGBA")
    btn_layer.putalpha(btn_mask)
    img.alpha_composite(btn_layer, dest=(btn_x1, btn_y))
    bbox3 = cta_font.getbbox("Descargar")
    bw = bbox3[2] - bbox3[0]
    draw.text((btn_x1 + (btn_w - bw) / 2, btn_y + 30), "Descargar", font=cta_font, fill=(10, 10, 15))

    # Bottom branding
    draw.text((W / 2 - 110, H - 120), "muse", font=find_font(72), fill=TEXT)
    muse_b = find_font(72).getbbox("muse")[2]
    draw.text((W / 2 - 110 + muse_b - 6, H - 120), ".", font=find_font(72), fill=AMBER)

    out_path = os.path.join(os.path.dirname(__file__), f"playstore-screen-{idx}.png")
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    print(f"✓ Screenshot {idx}: {out_path} ({os.path.getsize(out_path) // 1024} KB)")


def main():
    make_feature_graphic()
    make_screenshot_mock(1, "Pega y descarga", "De Instagram, TikTok y más")
    make_screenshot_mock(2, "Máxima calidad", "HD/4K · sin marca de agua")
    make_screenshot_mock(3, "Sin login", "Privado, gratis, sin fricción")
    make_screenshot_mock(4, "Como app nativa", "Instalable en tu home")


if __name__ == "__main__":
    main()
