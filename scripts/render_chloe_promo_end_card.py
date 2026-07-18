#!/usr/bin/env python3
"""Render the reusable vertical end card for Chloe promotional videos."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 720
HEIGHT = 1280
SANS = "/System/Library/Fonts/Avenir Next.ttc"
SERIF = "/System/Library/Fonts/NewYork.ttf"


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size, index=index)


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, face: ImageFont.FreeTypeFont, fill: str) -> int:
    box = draw.textbbox((0, 0), text, font=face)
    width = box[2] - box[0]
    draw.text(((WIDTH - width) / 2, y), text, font=face, fill=fill)
    return y + box[3] - box[1]


def render(track: str, output: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = image.load()
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        glow = math.exp(-((t - 0.30) / 0.24) ** 2)
        pixels_y = (
            int(7 + 4 * glow),
            int(10 + 22 * glow),
            int(17 + 27 * glow),
        )
        for x in range(WIDTH):
            pixels[x, y] = pixels_y

    draw = ImageDraw.Draw(image)
    cyan = "#8FE4E3"
    white = "#F4F2EC"
    muted = "#AEB9BD"
    dim = "#718188"
    ruby = "#A83E58"

    # Recovered-signal ornament: tidal lines, a ruby memory marker, and archive ticks.
    for offset, alpha_color in ((0, "#27606A"), (25, "#1A4752"), (52, "#11343E")):
        points = []
        for x in range(-40, WIDTH + 41, 8):
            y = 365 + offset + 13 * math.sin((x + offset * 2) / 82)
            points.append((x, y))
        draw.line(points, fill=alpha_color, width=2)

    draw.ellipse((571, 112, 621, 162), outline=ruby, width=2)
    draw.ellipse((586, 127, 606, 147), fill=ruby)
    draw.line((596, 162, 596, 206), fill="#6D263B", width=1)
    for y in range(212, 1070, 58):
        draw.line((83, y, 101, y), fill="#24434C", width=1)
        draw.line((619, y, 637, y), fill="#24434C", width=1)

    artist = font(SANS, 31)
    track_face = font(SERIF, 72)
    label = font(SANS, 20)
    credit = font(SANS, 28)
    callout = font(SANS, 23)

    centered(draw, "RECOVERED SIGNAL  //  NEW SINGLE", 188, label, ruby)
    centered(draw, "CHLOE KATASTROPHE", 244, artist, cyan)
    draw.line((222, 308, 498, 308), fill="#4B9299", width=2)
    centered(draw, track.upper(), 366, track_face, white)

    draw.rounded_rectangle((168, 555, 552, 812), radius=18, fill="#09141ECC", outline="#24434C", width=1)
    centered(draw, "WRITTEN BY", 598, label, dim)
    centered(draw, "Allen Taylor", 633, credit, white)

    centered(draw, "PRODUCED BY", 712, label, dim)
    centered(draw, "FrikShun.com", 747, credit, white)

    draw.line((116, 885, 604, 885), fill="#355B63", width=1)
    centered(draw, "DISCOVER MORE CHLOE KATASTROPHE MUSIC", 936, callout, muted)
    centered(draw, "ON ALL MAJOR STREAMING PLATFORMS", 978, callout, white)

    centered(draw, "FRIKSHUN  /  ARCHIVE CK-AUDIO-01", 1145, label, "#53656C")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def render_overlay(track: str, output: Path) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    white = "#F4F2EC"
    cyan = "#8FE4E3"
    ruby = "#A83E58"

    # Translucent archive-glass title plaque, safely inside mobile UI margins.
    draw.rounded_rectangle((46, 900, 586, 1090), radius=20, fill=(5, 13, 21, 168), outline=(68, 132, 141, 170), width=2)
    draw.rectangle((46, 900, 55, 1090), fill=ruby)
    draw.text((86, 936), track.upper(), font=font(SERIF, 46), fill=white)
    draw.text((88, 1012), "CHLOE KATASTROPHE", font=font(SANS, 23), fill=cyan)
    draw.line((88, 1060, 285, 1060), fill=(143, 228, 227, 150), width=2)

    output.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overlay-output", type=Path)
    args = parser.parse_args()
    render(args.track, args.output)
    if args.overlay_output:
        render_overlay(args.track, args.overlay_output)


if __name__ == "__main__":
    main()
