"""Generate the app icons (PWA) from code, so they can be tweaked and rebuilt.

Usage: python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent.parent / "icons"
SKY_TOP, SKY_BOTTOM = (2, 132, 199), (125, 211, 252)


def draw_icon(size: int, maskable: bool = False) -> Image.Image:
    scale = 4  # draw big, then downsample for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s))
    d = ImageDraw.Draw(img)
    for y in range(s):  # vertical sky gradient
        k = y / s
        d.line([(0, y), (s, y)], fill=tuple(round(a + (b - a) * k) for a, b in zip(SKY_TOP, SKY_BOTTOM)))
    if not maskable:  # rounded square, transparent corners
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=255)
        img.putalpha(mask)

    # Paraglider: canopy arc, lines and pilot. Maskable icons keep a safe zone.
    pad = s * (0.22 if maskable else 0.14)
    w = s - 2 * pad
    canopy = (pad, pad + w * 0.02, pad + w, pad + w * 0.62)
    d.arc(canopy, 200, 340, fill="white", width=round(w * 0.075))
    cx, pilot_y = s / 2, pad + w * 0.86
    left, right = (pad + w * 0.1, pad + w * 0.24), (pad + w * 0.9, pad + w * 0.24)
    for x, y in (left, right, (pad + w * 0.33, pad + w * 0.1), (pad + w * 0.67, pad + w * 0.1)):
        d.line([(x, y), (cx, pilot_y)], fill=(255, 255, 255, 190), width=max(1, round(w * 0.018)))
    r = w * 0.065
    d.ellipse((cx - r, pilot_y - r, cx + r, pilot_y + r), fill="white")
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for size in (192, 512):
        draw_icon(size).save(OUT / f"icon-{size}.png", optimize=True)
    draw_icon(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)
    draw_icon(180).save(OUT / "apple-touch-icon.png", optimize=True)
    print(f"Icônes écrites dans {OUT}")
