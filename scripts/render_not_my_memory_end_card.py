#!/usr/bin/env python3
"""Render the punk-collage end card for Chloe's "Not My Memory!" video."""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1080, 1920
PAPER = "#E9E2D8"
INK = "#090909"
PINK = "#ED2778"
WHITE = "#F7F2E9"
MUTED = "#9B9288"
CONDENSED = "/System/Library/Fonts/Avenir Next Condensed.ttc"
MARKER = "/System/Library/Fonts/MarkerFelt.ttc"
IMPACT = "/System/Library/Fonts/Supplemental/Impact.ttf"


def face(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size, index=index)


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.FreeTypeFont, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((WIDTH - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def rough_polygon(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, rng: random.Random) -> None:
    x0, y0, x1, y1 = box
    points = []
    for x in range(x0, x1 + 1, 36):
        points.append((x, y0 + rng.randint(-8, 8)))
    for y in range(y0, y1 + 1, 30):
        points.append((x1 + rng.randint(-7, 7), y))
    for x in range(x1, x0 - 1, -36):
        points.append((x, y1 + rng.randint(-8, 8)))
    for y in range(y1, y0 - 1, -30):
        points.append((x0 + rng.randint(-7, 7), y))
    draw.polygon(points, fill=fill)


def render(output: Path) -> None:
    rng = random.Random(1977)
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    px = image.load()

    # Xerox-paper grain and bruised edges.
    for y in range(HEIGHT):
        edge = max(0.0, abs(y - HEIGHT / 2) / (HEIGHT / 2) - 0.72)
        for x in range(WIDTH):
            side = max(0.0, abs(x - WIDTH / 2) / (WIDTH / 2) - 0.75)
            n = rng.randint(-13, 11) - int((edge + side) * 44)
            base = (233, 226, 216)
            px[x, y] = tuple(max(0, min(255, c + n)) for c in base)

    draw = ImageDraw.Draw(image)

    # Ink splatter, registration marks, and hand-drawn seams.
    for _ in range(210):
        x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        r = rng.choice((1, 1, 2, 2, 3, 5, 8))
        color = PINK if rng.random() < 0.22 else INK
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
    for y in (126, 1780):
        draw.line((40, y, 1040, y + rng.randint(-8, 8)), fill=INK, width=5)
        draw.line((66, y + 16, 1016, y + 22), fill=PINK, width=3)

    # Torn masthead and ransom-note title.
    rough_polygon(draw, (58, 116, 1024, 348), INK, rng)
    centered(draw, "CHLOE KATASTROPHE", 157, face(CONDENSED, 52, 1), WHITE)
    centered(draw, "NOT MY MEMORY!", 222, face(IMPACT, 103), PINK)
    draw.text((800, 335), "ARCHIVE FRAGMENT", font=face(MARKER, 27), fill=INK)
    draw.line((793, 369, 1003, 360), fill=PINK, width=5)

    # Reconstructed-head emblem: profile circle, thread, and an emphatic X.
    draw.ellipse((387, 426, 693, 732), outline=INK, width=13)
    for i in range(13):
        yy = 465 + i * 18
        wobble = int(14 * math.sin(i * 1.7))
        draw.line((421 + wobble, yy, 657 - wobble, yy + rng.randint(-24, 24)), fill=PINK, width=5)
    draw.line((489, 516, 593, 635), fill=INK, width=18)
    draw.line((595, 513, 487, 638), fill=INK, width=18)
    draw.arc((675, 454, 865, 706), 85, 270, fill=INK, width=8)
    draw.line((777, 684, 842, 792), fill=INK, width=8)
    draw.text((747, 735), "WHO STITCHED\nTHIS INTO ME?", font=face(MARKER, 29), fill=PINK)

    # Pasted credit slabs.
    rough_polygon(draw, (93, 846, 987, 1136), INK, rng)
    draw.text((143, 897), "WRITTEN BY", font=face(CONDENSED, 32, 1), fill=PINK)
    draw.text((143, 943), "ALLEN TAYLOR", font=face(IMPACT, 71), fill=WHITE)
    draw.line((139, 1032, 845, 1025), fill="#554F49", width=3)
    draw.text((143, 1054), "PRODUCED BY", font=face(CONDENSED, 32, 1), fill=PINK)
    draw.text((405, 1042), "FRIKSHUN.COM", font=face(IMPACT, 57), fill=WHITE)

    # Tape and safety-pin gestures.
    draw.polygon(((63, 813), (286, 794), (299, 862), (74, 879)), fill="#C9BDAF")
    draw.line((83, 833, 273, 817), fill="#887E74", width=2)
    draw.arc((827, 758, 1010, 922), 165, 500, fill=INK, width=8)
    draw.line((849, 846, 990, 779), fill=INK, width=7)
    draw.ellipse((966, 765, 1000, 799), outline=INK, width=5)

    # CTA as clipped lyric strips, echoing the cover's left column.
    strips = [
        ("MORE CHLOE KATASTROPHE", 1260, WHITE),
        ("ON ALL MAJOR", 1340, WHITE),
        ("STREAMING PLATFORMS", 1420, PINK),
    ]
    for text, y, color in strips:
        box = draw.textbbox((0, 0), text, font=face(MARKER, 48))
        w = box[2] - box[0]
        x = 84 + rng.randint(-8, 12)
        rough_polygon(draw, (x - 16, y - 8, x + w + 18, y + 63), INK, rng)
        draw.text((x, y), text, font=face(MARKER, 48), fill=color)

    # Chloe's signature and archive footer.
    draw.text((710, 1545), "CHLOE", font=face(MARKER, 75), fill=PINK)
    draw.line((697, 1632, 995, 1594), fill=INK, width=7)
    draw.line((699, 1645, 1002, 1607), fill=PINK, width=3)
    centered(draw, "NOT YOUR STORY  /  NOT YOUR MEMORY", 1704, face(CONDENSED, 30, 1), INK)
    centered(draw, "FRIKSHUN  //  CK-AUDIO-01  //  1977 NYC PUNK", 1810, face(CONDENSED, 24, 1), MUTED)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)


if __name__ == "__main__":
    render(Path("instance/uploads/song_videos/not-my-memory-2026-07-18/not-my-memory-punk-credits.png"))
