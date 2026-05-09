"""Genera iconos PWA: 192x192, 512x512, 180x180 (apple-touch)."""
from PIL import Image, ImageDraw, ImageFilter
import os

VIOLET = (167, 139, 250)
AMBER = (251, 191, 36)
BG = (10, 10, 15)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_logo(img, scale, padding):
    """Draw M+arrow logo centered, sized to fit (scale * 100 = base size)."""
    draw = ImageDraw.Draw(img, "RGBA")
    s = scale
    width = int(11 * s)
    pts_m = [(15, 78), (15, 25), (50, 58), (85, 25), (85, 78)]
    pts_arrow = [(38, 70), (50, 86), (62, 70)]

    def transform(pts):
        return [(padding + p[0] * s, padding + p[1] * s) for p in pts]

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


def make_icon(size, fname, rounded=False, padding_pct=0.15):
    img = Image.new("RGBA", (size, size), BG + (255,))
    inner = size * (1 - 2 * padding_pct)
    scale = inner / 100
    padding = size * padding_pct
    draw_logo(img, scale, padding)

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


def main():
    make_icon(192, "icon-192.png", rounded=False)
    make_icon(512, "icon-512.png", rounded=False)
    make_icon(180, "apple-touch-icon.png", rounded=True)
    make_icon(512, "icon-512-maskable.png", rounded=False, padding_pct=0.2)


if __name__ == "__main__":
    main()
