# -*- coding: utf-8 -*-
"""
Create placeholder illustrations that follow the renderer's naming contract, so the demo renders without the
study's illustration set (which is not distributed). Each picture is a plain drawing labelled with its slot.

  python tools/make_placeholder_images.py [assets/images]

Naming contract (folder / band / sex / topic; underscores and spaces are interchangeable):
  about_ich/{band}_{sex}_*.png                                   "What is the bleed" picture
  prognosis_discharge/{emergency|recovery}/{eng|kor}/{band}_{sex}_*.png
  warning_signs/{eng|kor}/{folder}/{band}_{sex}_*.png            one per warning-sign folder (red label banner on top)
  health_habits/**/{band}_{sex}_*_{habit_id}.png                 one per habit topic
  band = baby | child | adolescent | young_adult | middle_age | senior ; sex = male | female
To use your own illustrations, keep the same folders and file-name prefixes.
"""
import ast
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _renderer_tables():
    """SIGN_FOLDER, HABIT_IDS and HABIT_IMAGE_V4 read from render_brochures.py (no import, so no fonts are needed)."""
    tree = ast.parse(open(os.path.join(HERE, "render_brochures.py"), encoding="utf-8").read())
    want, out = {"SIGN_FOLDER", "HABIT_IDS", "HABIT_IMAGE_V4"}, {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", None) in want:
            out[n.targets[0].id] = ast.literal_eval(n.value)
    return out

BANDS = ["baby", "child", "adolescent", "young_adult", "middle_age", "senior"]
SEXES = ["male", "female"]
LANGS = {"eng": "EN", "kor": "KO"}


def _font(size):
    for f in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _picture(path, label, sub, banner=None, size=(600, 760), tint=(226, 236, 244)):
    """A light drawing on white paper; warning pictures get a red banner with white text on top."""
    W, H = size
    im = Image.new("RGB", size, "white"); d = ImageDraw.Draw(im)
    top = 0
    if banner:
        top = int(H * 0.12)
        d.rectangle([0, 0, W, top], fill=(200, 30, 30))
        d.text((W // 2, top // 2), banner, fill="white", font=_font(30), anchor="mm")
    d.rounded_rectangle([40, top + 40, W - 40, H - 60], radius=30, fill=tint, outline=(150, 165, 180), width=3)
    d.ellipse([W // 2 - 80, top + 90, W // 2 + 80, top + 250], fill=(190, 205, 220))          # a simple figure
    d.rounded_rectangle([W // 2 - 130, top + 270, W // 2 + 130, H - 140], radius=40, fill=(190, 205, 220))
    d.text((W // 2, H - 110), label, fill=(40, 50, 60), font=_font(26), anchor="mm")
    d.text((W // 2, H - 80), sub, fill=(90, 100, 110), font=_font(20), anchor="mm")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, optimize=True)


def main(root):
    R = _renderer_tables()                                           # folders and habit ids the renderer looks up
    n = 0
    habit_ids = set(R["HABIT_IDS"]) | {k for v in R["HABIT_IMAGE_V4"].values() for k in v}
    for band in BANDS:
        for sex in SEXES:
            who = f"{band.replace('_', ' ')}, {sex}"
            _picture(os.path.join(root, "about_ich", f"{band}_{sex}_demo.png"), "DEMO: about the bleed", who); n += 1
            for il, tag in LANGS.items():
                for kind in ("emergency", "recovery"):
                    _picture(os.path.join(root, "prognosis_discharge", kind, il, f"{band}_{sex}_demo.png"),
                             f"DEMO: {kind} ({tag})", who, size=(760, 560)); n += 1
                for folder in sorted(set(R["SIGN_FOLDER"].values())):
                    _picture(os.path.join(root, "warning_signs", il, folder, f"{band}_{sex}_demo.png"),
                             f"DEMO: {folder}", who, banner=f"{folder.upper()} ({tag})", tint=(250, 232, 228)); n += 1
            for hid in sorted(habit_ids):
                _picture(os.path.join(root, "health_habits", f"{band}_{sex}_demo_{hid}.png"),
                         f"DEMO: {hid}", who, size=(700, 520), tint=(232, 244, 232)); n += 1
    print(f"{n} placeholder pictures -> {root}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "assets", "images"))
