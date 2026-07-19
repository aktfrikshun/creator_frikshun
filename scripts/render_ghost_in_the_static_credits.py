#!/usr/bin/env python3
"""Render the square end-credit still for "Ghost in the Static."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


SERIF = "/System/Library/Fonts/NewYork.ttf"
SANS = "/System/Library/Fonts/Avenir Next Condensed.ttc"


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size, index=index)


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, face: ImageFont.FreeTypeFont, fill: str) -> None:
    box = draw.textbbox((0, 0), text, font=face)
    draw.text(((draw._image.width - (box[2] - box[0])) / 2, y), text, font=face, fill=fill)


def render(background_path: Path, output_path: Path) -> None:
    image = Image.open(background_path).convert("RGB")
    side = min(image.size)
    image = image.crop(((image.width - side) // 2, (image.height - side) // 2,
                        (image.width + side) // 2, (image.height + side) // 2))
    image = image.resize((1500, 1500), Image.Resampling.LANCZOS)
    image = ImageEnhance.Brightness(image).enhance(0.72)

    # A soft archive-glass field keeps the typography legible while allowing the
    # generated static and transmission tower to remain visible at the edges.
    veil = Image.new("RGBA", image.size, (0, 0, 0, 0))
    veil_draw = ImageDraw.Draw(veil)
    veil_draw.rounded_rectangle((210, 210, 1290, 1215), radius=24,
                                fill=(3, 6, 16, 188), outline=(125, 91, 153, 105), width=2)
    veil = veil.filter(ImageFilter.GaussianBlur(0.4))
    image = Image.alpha_composite(image.convert("RGBA"), veil)
    draw = ImageDraw.Draw(image)

    lavender = "#C8A7DD"
    violet = "#A768D2"
    white = "#F1ECF2"
    muted = "#A39AAC"
    rose = "#E17B94"

    centered(draw, "DAUGHTER OF ECHOES  //  TRACK 11", 280, font(SANS, 34, 1), lavender)
    centered(draw, "GHOST IN THE STATIC", 365, font(SERIF, 86), white)
    draw.line((440, 490, 1060, 490), fill=(167, 104, 210, 185), width=2)

    centered(draw, "WRITTEN BY", 585, font(SANS, 27, 1), muted)
    centered(draw, "ALLEN TAYLOR", 630, font(SANS, 48, 1), white)
    centered(draw, "PRODUCED BY", 735, font(SANS, 27, 1), muted)
    centered(draw, "FRIKSHUN.COM", 780, font(SANS, 48, 1), white)

    centered(draw, "CHLOE KATASTROPHE", 930, font(SANS, 44, 1), lavender)
    centered(draw, "MUSIC AVAILABLE ON ALL MAJOR STREAMING PLATFORMS", 1015, font(SANS, 26, 1), white)
    centered(draw, "EVERY SIGNAL LEAVES A TRACE", 1130, font(SANS, 25, 1), rose)

    # Signal markers echo the concentric broadcast rings from the cover.
    for radius, alpha in ((10, 235), (26, 150), (46, 95), (70, 55)):
        draw.ellipse((750 - radius, 1264 - radius, 750 + radius, 1264 + radius),
                     outline=(225, 123, 148, alpha), width=2)
    centered(draw, "FRIKSHUN  //  DAUGHTER OF ECHOES  //  TRACK 11", 1350, font(SANS, 23, 1), muted)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, "PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    render(args.background, args.output)


if __name__ == "__main__":
    main()
