"""Derive the brand assets from the master logo.

Everything here is generated, not hand-drawn: the master file is the single
source of truth, so re-running this after a logo change reproduces every asset.
"""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "brand" / "logo-master.png"
OUT = ROOT / "apps" / "web" / "public"
APP = ROOT / "apps" / "web" / "app"

master = Image.open(SRC).convert("RGBA")
a = np.array(master)
rgb = a[..., :3].astype(int)
alpha = a[..., 3].astype(int)
ink = ((255 - rgb).max(axis=2) > 18) & (alpha > 20)
ys, xs = np.where(ink)
x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()

# The mark and the wordmark are separated by a clear column gap at x≈453–474.
MARK_END = 460
mark_cols = ink[:, x0:MARK_END]
mys = np.where(mark_cols.any(axis=1))[0]
mark_box = (x0, mys.min(), MARK_END, mys.max())


def transparent_background(img: Image.Image) -> Image.Image:
    """Drop the white matte so the logo sits on any surface."""
    arr = np.array(img.convert("RGBA")).astype(int)
    near_white = (arr[..., :3].min(axis=2) > 244)
    arr[near_white, 3] = 0
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def pad(img: Image.Image, ratio: float = 0.06) -> Image.Image:
    p = int(max(img.size) * ratio)
    canvas = Image.new("RGBA", (img.width + 2 * p, img.height + 2 * p), (0, 0, 0, 0))
    canvas.paste(img, (p, p), img)
    return canvas


def square(img: Image.Image, size: int, background=(0, 0, 0, 0)) -> Image.Image:
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), background)
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return canvas.resize((size, size), Image.LANCZOS)


def for_dark_background(img: Image.Image, wordmark_starts_at: int) -> Image.Image:
    """Flip only the neutral ink of the wordmark to white.

    Restricted to the wordmark on purpose: the mark contains white circuit
    lines, and inverting luminance across the whole image would turn them black.
    The blue and orange are saturated, so they are left exactly as designed.
    """
    arr = np.array(img.convert("RGBA")).astype(int)
    region = arr[:, wordmark_starts_at:, :]
    r, g, b = region[..., 0], region[..., 1], region[..., 2]
    saturation = region[..., :3].max(axis=2) - region[..., :3].min(axis=2)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b)
    neutral = (saturation < 45) & (region[..., 3] > 0)
    flipped = np.clip(255 - luminance, 0, 255)
    for channel in range(3):
        region[..., channel] = np.where(neutral, flipped, region[..., channel])
    arr[:, wordmark_starts_at:, :] = region
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


# --- full lockup -------------------------------------------------------------
lockup = transparent_background(master.crop((x0, y0, x1 + 1, y1 + 1)))
lockup = pad(lockup, 0.03)
target_w = 960
lockup = lockup.resize((target_w, round(lockup.height * target_w / lockup.width)), Image.LANCZOS)
lockup.save(OUT / "logo.png")

dark = for_dark_background(lockup, wordmark_starts_at=int(lockup.width * 0.26))
dark.save(OUT / "logo-dark.png")

# --- mark only ---------------------------------------------------------------
mark = transparent_background(master.crop(mark_box))
mark = pad(mark, 0.04)
square(mark, 512).save(OUT / "logo-mark.png")

# App Router picks these up automatically and emits the right <link> tags.
square(mark, 512).save(APP / "icon.png")
square(mark, 180, background=(255, 255, 255, 255)).convert("RGB").save(APP / "apple-icon.png")

# Multi-resolution .ico for browsers and bookmark bars that still ask for it.
ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
square(mark, 256).save(OUT / "favicon.ico", sizes=ico_sizes)
square(mark, 256).save(APP / "favicon.ico", sizes=ico_sizes)

for path in [
    OUT / "logo.png", OUT / "logo-dark.png", OUT / "logo-mark.png",
    OUT / "favicon.ico", APP / "favicon.ico", APP / "icon.png", APP / "apple-icon.png",
]:
    with Image.open(path) as img:
        print(f"{path.name:<18} {img.size} {img.mode}")
