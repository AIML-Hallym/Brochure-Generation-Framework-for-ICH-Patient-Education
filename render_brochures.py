# -*- coding: utf-8 -*-
"""
Brochure renderer: cache JSON (from run_batch.py) -> two-page A4-landscape tri-fold PDF (6 panels), English and Korean.

  python render_brochures.py --cache outputs/demo/cache --out outputs/demo/pdf --images assets/images

Layout
  page 1 (inside)   [What is the bleed + picture + Hospital stay]
                    [Nurse call button: warning-sign checklist + pictures of the first 4 signs + red closing line]
                    [After leaving the hospital + emergency picture on the bottom edge]
  page 2 (outside)  [Healthy habits + pictures of the activity and safety items, side by side]
                    [Support and resources + AI/IRB notice]
                    [Cover]
  Fit: one font scale per brochure, the largest at which every panel fits (up to V4_S_MAX); pictures shrink first,
  following the size ladders in V4_IMG. Text stays vector (selectable).

Pictures are looked up by file name (see tools/make_placeholder_images.py for the naming contract):
  about_ich/{band}_{sex}_*.png, prognosis_discharge/emergency/{eng|kor}/{band}_{sex}_*.png,
  warning_signs/{eng|kor}/{folder}/{band}_{sex}_*.png, health_habits/**/{band}_{sex}_*_{habit_id}.png
  band = baby | child | adolescent | young_adult | middle_age | senior ; sex = male | female
The illustration set used in the study is not distributed with this repository.

Fonts: Georgia / Arial Black / Arial Bold / Malgun Gothic / Segoe UI Symbol are used when present (Windows).
Set ICH_FONT_DIR, or install the open fallbacks (Noto Serif, Noto Sans KR TTF, DejaVu Sans), see README.
"""
import os, re, io, csv, sys, json, html, time, argparse, tempfile, hashlib, functools
from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "outputs", "run", "cache")          # run_batch.py default output
IMG_ROOT = os.path.join(HERE, "assets", "images")
OUT_ROOT = os.path.join(HERE, "outputs", "run", "pdf")
IMG_CACHE = os.path.join(tempfile.gettempdir(), "ich_brochure_imgcache")
IRB_NO = ""                       # fills "IRB No. ____" in the generated footer (--irb); empty keeps the blank
IMG_DPI = 220                     # resolution images are embedded at

# ------------------------------------------------------------------ fonts
FONT_DIRS = [d for d in (os.environ.get("ICH_FONT_DIR"), os.path.join(HERE, "assets", "fonts"), r"C:\Windows\Fonts",
                         "/usr/share/fonts", "/usr/local/share/fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts"),
                         os.path.expanduser("~/.fonts")) if d and os.path.isdir(d)]
FONT_FILES = {   # logical name -> candidate TrueType files (first found wins). Korean needs a TTF with Hangul glyphs.
    "Georgia": ["georgia.ttf", "NotoSerif-Regular.ttf", "DejaVuSerif.ttf"],
    "Georgia-Bold": ["georgiab.ttf", "NotoSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
    "Georgia-Italic": ["georgiai.ttf", "NotoSerif-Italic.ttf", "DejaVuSerif-Italic.ttf"],
    "Georgia-BoldItalic": ["georgiaz.ttf", "NotoSerif-BoldItalic.ttf", "DejaVuSerif-BoldItalic.ttf"],
    "ArialBlack": ["ariblk.ttf", "NotoSans-Black.ttf", "DejaVuSans-Bold.ttf"],
    "Arial-Bold": ["arialbd.ttf", "NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "Malgun": ["malgun.ttf", "NotoSansKR-Regular.ttf", "NanumGothic.ttf"],
    "Malgun-Bold": ["malgunbd.ttf", "NotoSansKR-Bold.ttf", "NanumGothicBold.ttf"],
    "SegoeSymbol": ["seguisym.ttf", "DejaVuSans.ttf"],
}

def _find_font(cands):
    for d in FONT_DIRS:
        for root, _, files in os.walk(d):
            low = {f.lower(): f for f in files}
            for c in cands:
                if c.lower() in low: return os.path.join(root, low[c.lower()])
    raise FileNotFoundError(f"none of {cands} found; set ICH_FONT_DIR (see README)")

for name, cands in FONT_FILES.items():
    pdfmetrics.registerFont(TTFont(name, _find_font(cands)))
pdfmetrics.registerFontFamily("Georgia", normal="Georgia", bold="Georgia-Bold", italic="Georgia-Italic", boldItalic="Georgia-BoldItalic")
pdfmetrics.registerFontFamily("Malgun", normal="Malgun", bold="Malgun-Bold", italic="Malgun", boldItalic="Malgun-Bold")

INK, BODY, RED, GRAY, RULE = (colors.HexColor(h) for h in ("#111418", "#22272E", "#D7261E", "#4B5563", "#DDE3E7"))

# ------------------------------------------------------------------ page geometry (pt)
PW, PH = landscape(A4)
PANEL_W = PW / 3
PAD_X, PAD_T, PAD_B = 18, 22, 20
CW, CH = PANEL_W - 2 * PAD_X, PH - PAD_T - PAD_B
GAP, GAP_MAX = 9, 26                      # min / max space between blocks
HELP_GAP = 30                             # space above the "For more help" paragraph in the support panel
S_MAX, S_MIN, S_STEP = 1.14, 0.80, 0.02   # font-scale search range

LANG = {
    "en": dict(
        titles=["What is Brain Bleeding?", "Hospital Stay", "When to Use the Nurse Call Button",
                "What to Expect After Leaving the Hospital", "Healthy Habits", "Support and Resources"],
        body="Georgia", bold="Georgia-Bold", title="ArialBlack", accent="Arial-Bold",
        z=dict(title=15.5, body=10.2, lead=13.4, check=9.8, check_lead=12.7, closing=10.6, foot=7.4, foot_lead=9.8),
        cover_title=("Patient-", "Education", "BROCHURE"), guide="A Guide for Patients and Families",
        fields=["Patient Name", "Date of Scan", "Ward Phone", "Verification Name"], img_lang="eng", suffix="EN",
        emergency_no="911",       # fallback only: the number is taken from the cache (emergency_number) when present
        alt_titles={"What to Expect After Discharge?": "What to Expect After Leaving the Hospital"}),   # legacy v2 title
        # "Support and Resources in <country>" (any locale) is matched by its prefix in parse_md
    "ko": dict(
        titles=["뇌출혈이란 무엇인가요?", "입원 중 치료", "간호사 호출 버튼은 언제 누르나요?",
                "퇴원 후에는 어떻게 되나요?", "건강한 생활 습관", "도움받을 수 있는 곳"],
        body="Malgun", bold="Malgun-Bold", title="Malgun-Bold", accent="Malgun-Bold",
        z=dict(title=15.0, body=9.8, lead=14.4, check=9.5, check_lead=13.6, closing=10.2, foot=7.2, foot_lead=10.4),
        cover_title=("환자 교육", "브로셔"), guide=None,
        fields=["환자 이름", "검사일", "병동 전화", "확인자"], img_lang="kor", suffix="KO",
        emergency_no="119", alt_titles={}),
}

# ------------------------------------------------------------------ image lookup (exact, by folder / age / sex / id)
SIGN_FOLDER = {"cannot_wake": "drowsy", "pupil": "pupil", "seizure": "seizure", "headache": "headache", "vomiting": "vomiting",
               "weakness": "weakness", "csf_leak": "clear", "swallow": "swallowing", "speech": "dysarthria",
               "confusion": "confusion", "vision": "visual", "facial_palsy": "facial"}
HABIT_IDS = ["meds_daily", "scans", "bp_check", "work_stress", "smoke", "alcohol", "salt", "strain", "gentle_walk", "apnea",
             "cough", "anger", "energy", "home_falls", "cane", "thinners", "eyes_ears", "sleep_med", "helmet", "sleep_seizure",
             "rest_return", "bone", "pregnancy", "child_helmet", "child_sports", "child_rest", "child_sleep", "child_headache",
             "child_school", "infant_carseat", "infant_watch", "infant_shake", "infant_sleep", "infant_visits"]

HABIT_IMAGE_ALIAS = {"pace_tbi": "gentle_walk", "daily_older": "gentle_walk", "rails": "home_falls", "swallow_safe": "salt",
                     "rehab_practice": "gentle_walk", "cog_pace": "anger",
                     "memory_aids": "anger", "strain_lift": "strain", "bowel_care": "strain"}   # v3 habits that reuse another habit's image
# v4: one image per habit item, matching what the item says; first entry that exists for the age/sex band wins
HABIT_IMAGE_V4 = {"thinners": ["thinners", "meds_daily"], "meds_ask": ["meds_daily"], "swallow_safe": ["salt"],
                  "pace_tbi": ["rest_return", "gentle_walk"], "cog_pace": ["rest_return", "anger"],
                  "rest_return": ["rest_return", "gentle_walk"], "daily_older": ["gentle_walk"], "rehab_practice": ["gentle_walk"],
                  "helmet": ["helmet", "home_falls"], "cane": ["cane", "home_falls"], "eyes_ears": ["eyes_ears", "home_falls"],
                  "rails": ["home_falls"], "strain_lift": ["strain"], "bowel_care": ["strain"], "memory_aids": ["anger"],
                  "energy": ["energy", "smoke"]}
# v4: medicine and food/drink/smoking items are general, so they keep their text but get no picture (2026-10-02)
HABIT_NO_IMAGE_V4 = {"meds_daily", "thinners", "meds_ask", "alcohol", "smoke", "salt", "swallow_safe", "pregnancy", "energy"}
V4_HABIT_IMAGES = 2
V4_S_MAX = 1.60                  # v4: text as large as each brochure allows (EN body 10.2 pt x 1.60 = 16.3 pt at most)
V4_PARA_GAP = 11                                                 # space after each discharge paragraph (pt, x font scale)
V4_WARN_KEEP = 0.85              # warning pictures: keep the top 85% (label + person; drops the bed/feet strip at the bottom)
V4_TRIM_PAD = 0.015              # white-margin trim keeps this much (fraction of the image) around the drawing
V4_BANNER_PAD = 0.04             # warning pictures: red banner kept at least this far beyond its text on each side
V4_WARN_KEEP_BY = {"vomiting": 0.97}   # warning pictures whose key object sits at the bottom (the basin): keep more
V4_SEAM_TRIM = 0.025             # habit strip: trim this much off the inner edges where the two pictures meet
V4_TITLE_CAP = 1.30              # section titles stop growing here, so the body text can grow further
# warning pictures (portrait): (columns, width fraction), largest pictures first. 2x2 is used when it fits at the chosen
# text size; otherwise one row of 4 (half the height) so the text size is never limited by the pictures.
V4_WARN_OPTS = tuple((2, f) for f in (0.90, 0.84, 0.78, 0.72, 0.66, 0.60)) + tuple((4, f) for f in (1.00, 0.96, 0.92, 0.88))
V4_IMG = [(0.80, 0.74, 0.68, 0.62, 0.56, 0.50, 0.45),            # about image (width fraction)
          V4_WARN_OPTS,                                          # warning pictures
          tuple(round(1.0 - 0.04 * k, 2) for k in range(14)),     # emergency image: as large as fits (1.00 ... 0.48)
          (1.00, 0.94, 0.88, 0.82, 0.76, 0.70, 0.64, 0.58)]      # habit pictures: one strip of 2 (width fraction)

def age_token(age):
    return ("baby" if age <= 2 else "child" if age <= 12 else "adolescent" if age <= 18 else
            "young adult" if age <= 39 else "middle age" if age <= 64 else "senior")

# caches that store the generator's age band use it for the pictures too, so text and pictures always agree
BAND_TOKEN = {"infant": "baby", "child": "child", "teen": "adolescent", "young": "young adult", "middle": "middle age",
              "older": "senior"}

class ImageIndex:
    def __init__(self, root):
        self.files = []                                   # (normalized relative path, absolute path)
        for r, _, fs in os.walk(root):
            for f in fs:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and not f.startswith("_"):
                    p = os.path.join(r, f)
                    rel = os.path.relpath(p, root).replace("\\", "/").lower().replace("_", " ")
                    self.files.append((rel, p))
        self.habit = {}
        ids = set(HABIT_IDS) | set(HABIT_IMAGE_V4) | {k for v in HABIT_IMAGE_V4.values() for k in v}   # incl. --image-map ids
        norm_ids = sorted(((h.replace("_", " "), h) for h in ids), key=lambda x: -len(x[0]))
        for rel, p in self.files:
            if not rel.startswith("health habits/"): continue
            name = os.path.splitext(rel.split("/")[-1])[0]
            vid = next((h for n, h in norm_ids if name.endswith(" " + n)), None)
            m = re.match(r"(baby|child|adolescent|young adult|middle age|senior) (male|female) ", name)
            if vid and m: self.habit[(m.group(1), m.group(2), vid)] = p

    def one(self, prefix, age, sex):
        hits = [p for rel, p in self.files if rel.startswith(prefix) and rel[len(prefix):].startswith(f"{age} {sex} ")]
        if len(hits) != 1: raise LookupError(f"{len(hits)} images for {prefix}{age} {sex}")
        return hits[0]

    def about(self, age, sex): return self.one("about ich/", age, sex)
    def prognosis(self, kind, lang, age, sex): return self.one(f"prognosis discharge/{kind}/{lang}/", age, sex)
    def sign(self, vid, lang, age, sex): return self.one(f"warning signs/{lang}/{SIGN_FOLDER[vid]}/", age, sex)
    def habits(self, ids, age, sex, n=2):
        got = []                                          # first n habits that have an image (aliases for v3 ids)
        for h in ids:
            k = (age, sex, HABIT_IMAGE_ALIAS.get(h, h))
            if k in self.habit and all(p != self.habit[k] for _, p in got): got.append((h, self.habit[k]))
        if len(got) < n: raise LookupError(f"only {len(got)} habit images for {age} {sex} {ids}")
        return got[:n]
    def habits_v4(self, ids, age, sex, n=V4_HABIT_IMAGES):
        """Pictures for the activity and safety items only (medicine/food items are text only), in item order, no repeats."""
        pick = [h for h in ids if h not in HABIT_NO_IMAGE_V4]
        pick += [h for h in ids if h not in pick]                 # only if fewer than n picturable items (e.g. children)
        got = []
        for h in pick[:n]:
            opts = [k for k in HABIT_IMAGE_V4.get(h, [h]) if (age, sex, k) in self.habit
                    and all(p != self.habit[(age, sex, k)] for _, p in got)]
            if not opts: raise LookupError(f"no image for habit {h} ({age} {sex})")
            got.append((h, self.habit[(age, sex, opts[0])]))
        return got

def embed(path, w_pt, h_pt, box=None):
    """Resize once to the placed size at IMG_DPI and cache as JPEG (reportlab embeds JPEG files as-is).
    box = (left, top, right, bottom) as fractions of the image: v4 crops white margins (see trim_box)."""
    px = (max(1, round(w_pt / 72 * IMG_DPI)), max(1, round(h_pt / 72 * IMG_DPI)))
    key = hashlib.md5(f"{path}|{px}|{os.path.getmtime(path)}".encode() + (f"|{box}".encode() if box else b"")).hexdigest()
    out = os.path.join(IMG_CACHE, key + ".jpg")
    if not os.path.exists(out):
        os.makedirs(IMG_CACHE, exist_ok=True)
        im = Image.open(path).convert("RGB")
        if box:
            l, t, r, b = box
            im = im.crop((round(im.width * l), round(im.height * t), round(im.width * r), round(im.height * b)))
        im.resize(px, Image.LANCZOS).save(out, "JPEG", quality=86, optimize=True)
    return out

@functools.lru_cache(maxsize=None)
def aspect(path):
    with Image.open(path) as im: return im.width / im.height

def aspect_box(path, box=None):
    if not box: return aspect(path)
    l, t, r, b = box
    return aspect(path) * (r - l) / (b - t)

@functools.lru_cache(maxsize=None)
def trim_box(path, kind="plain"):
    """v4: crop box (l, t, r, b fractions) that removes the white margins around the drawing; None if nothing to trim.
    kind "warn": warning pictures — keep the red label banner and its text, trim the white strips beside the picture,
    and keep only the top V4_WARN_KEEP of the height (the bottom strip is bed/feet)."""
    import numpy as np
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16); H, W, _ = a.shape
    ink = a.min(axis=2) < 238                                   # anything that is not (near-)white paper
    pad = V4_TRIM_PAD
    if kind == "warn":
        red = (a[:, :, 0] > 150) & (a[:, :, 1] < 110) & (a[:, :, 2] < 110)
        rows = np.where(red.mean(axis=1) > 0.5)[0]
        bh = int(rows.max()) + 1 if len(rows) else 0
        txt = np.where((a[:bh].min(axis=2) > 200).mean(axis=0) > 0.02)[0] if bh else np.array([], dtype=int)
        pic = np.where(ink[bh + 5:].mean(axis=0) > 0.01)[0]
        norm = path.replace("\\", "/")
        keep = next((v for k, v in V4_WARN_KEEP_BY.items() if f"/{k}/" in norm), V4_WARN_KEEP)
        lo = [pic.min() / W - pad] if len(pic) else []
        hi = [(pic.max() + 1) / W + pad] if len(pic) else []
        if len(txt): lo.append(txt.min() / W - V4_BANNER_PAD); hi.append((txt.max() + 1) / W + V4_BANNER_PAD)
        if not lo: return (0.0, 0.0, 1.0, keep)
        return (float(max(0.0, min(lo))), 0.0, float(min(1.0, max(hi))), keep)
    rows = np.where(ink.mean(axis=1) > 0.01)[0]; cols = np.where(ink.mean(axis=0) > 0.01)[0]
    if not len(rows) or not len(cols): return None
    box = (float(max(0.0, cols.min() / W - pad)), float(max(0.0, rows.min() / H - pad)),
           float(min(1.0, (cols.max() + 1) / W + pad)), float(min(1.0, (rows.max() + 1) / H + pad)))
    return None if (box[2] - box[0]) * (box[3] - box[1]) > 0.97 else box

# ------------------------------------------------------------------ text parsing
def parse_md(md, titles, alts=None):
    """Sections are keyed by the canonical titles; `shown` keeps the title as written in the text (v3 renames two)."""
    alts = alts or {}
    body, _, footer = md.partition("\n---\n")
    lines = [l.strip() for l in body.split("\n")]
    cover = lines[0].strip("*").strip()
    sections, shown, cur = {}, {}, None
    for l in lines[1:]:
        m = re.fullmatch(r"\*\*(.+)\*\*", l)
        key = None
        if m:
            key = alts.get(m.group(1), m.group(1))
            if key not in titles and key.startswith("Support and Resources"): key = "Support and Resources"
        if key in titles:
            cur = key; sections[cur] = []; shown[cur] = m.group(1); continue
        if cur and l: sections[cur].append(l)
    missing = [t for t in titles if t not in sections]
    if missing: raise ValueError(f"missing sections {missing}")
    foot = [l.strip().replace("IRB No. ____", f"IRB No. {IRB_NO}") if IRB_NO else l.strip() for l in footer.split("\n") if l.strip()]
    return cover, sections, foot, shown

HANGUL = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]+(?:[ ·]+[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]+)*")
def mk(text, lang, bold=False):
    t = html.escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    if lang == "en":                                        # Georgia has no Hangul: switch those runs to Malgun
        t = HANGUL.sub(lambda m: f'<font name="Malgun">{m.group(0)}</font>', t)
    return f"<b>{t}</b>" if bold else t

def emphasize_emergency(par, lang, num):
    """Bold every sentence of the discharge section that contains the edition's emergency number."""
    parts = re.split(r"(?<=[.!?])\s+", par)
    return " ".join(f"**{p}**" if re.search(rf"(?<!\d){re.escape(num)}(?!\d)", p) else p for p in parts)

# ------------------------------------------------------------------ styles
def styles(lang, s, title_cap=None):
    L, z = LANG[lang], LANG[lang]["z"]
    ts = min(s, title_cap) if title_cap else s                  # v4: titles stop growing at title_cap
    body = ParagraphStyle("body", fontName=L["body"], fontSize=z["body"] * s, leading=z["lead"] * s, textColor=BODY,
                          spaceAfter=4.5 * s, alignment=TA_LEFT)
    return dict(
        title=ParagraphStyle("title", fontName=L["title"], fontSize=z["title"] * ts, leading=z["title"] * ts * 1.2,
                             textColor=INK, spaceAfter=6 * s),
        title_red=ParagraphStyle("title_red", fontName=L["title"], fontSize=z["title"] * ts, leading=z["title"] * ts * 1.2,
                                 textColor=RED, spaceAfter=6 * s),
        body=body,
        sub=ParagraphStyle("sub", parent=body, fontName=L["bold"], spaceAfter=3 * s),
        check=ParagraphStyle("check", parent=body, fontSize=z["check"] * s, leading=z["check_lead"] * s,
                             leftIndent=14 * s, bulletIndent=0, bulletFontName="SegoeSymbol",
                             bulletFontSize=z["check"] * s * 1.1, spaceAfter=2.4 * s),
        bullet=ParagraphStyle("bullet", parent=body, leftIndent=11 * s, bulletIndent=1 * s, bulletFontName=L["body"],
                              bulletFontSize=z["body"] * s, spaceAfter=3.2 * s),
        closing=ParagraphStyle("closing", fontName=L["accent"], fontSize=z["closing"] * s, leading=z["closing"] * s * 1.28,
                               textColor=RED, spaceAfter=0),
        foot=ParagraphStyle("foot", fontName=L["body"], fontSize=max(6.6, z["foot"] * min(s, 1.0)),
                            leading=max(8.8, z["foot_lead"] * min(s, 1.0)), textColor=GRAY, spaceAfter=3.5),
    )

# ------------------------------------------------------------------ blocks
class Flow:
    def __init__(self, paras): self.paras = paras
    def height(self):
        h = 0
        for i, p in enumerate(self.paras):
            _, ph = p.wrap(CW, 1e6); h += ph + (p.style.spaceAfter if i < len(self.paras) - 1 else 0)
        return h
    def draw(self, c, x, top):
        y = top
        for p in self.paras:
            _, ph = p.wrap(CW, 1e6); p.drawOn(c, x, y - ph); y -= ph + p.style.spaceAfter

def rounded_image(c, path, x, y_bottom, w, h, r, box=None):
    c.saveState()
    pth = c.beginPath(); pth.roundRect(x, y_bottom, w, h, r); c.clipPath(pth, stroke=0, fill=0)
    c.drawImage(embed(path, w, h, box), x, y_bottom, w, h)
    c.restoreState()

class Pic:
    def __init__(self, path, f=1.0, box=None): self.path, self.f, self.box, self.a = path, f, box, aspect_box(path, box)
    def height(self): return CW * self.f / self.a
    def draw(self, c, x, top):
        w = CW * self.f; h = w / self.a
        rounded_image(c, self.path, x + (CW - w) / 2, top - h, w, h, 6, self.box)

class Strip:
    """v4 habit pictures: side by side, no gap, same height, one rounded frame, so the pair reads as one picture."""
    def __init__(self, paths, f=1.0, boxes=None):
        self.paths, self.f = paths, f
        bx = [list(b) if b else [0.0, 0.0, 1.0, 1.0] for b in (boxes or [None] * len(paths))]
        for i, b in enumerate(bx):                                  # trim the inner edges (pale strips at the join)
            if i > 0: b[0] += V4_SEAM_TRIM * (b[2] - b[0])
            if i < len(bx) - 1: b[2] -= V4_SEAM_TRIM * (b[2] - b[0])
        self.boxes = [tuple(round(v, 4) for v in b) for b in bx]
        self.aspects = [aspect_box(q, b) for q, b in zip(paths, self.boxes)]
    def size(self):
        w = CW * self.f; return w, w / sum(self.aspects)
    def height(self): return self.size()[1]
    def draw(self, c, x, top):
        w, h = self.size(); x0 = x + (CW - w) / 2; y = top - h
        c.saveState()
        pth = c.beginPath(); pth.roundRect(x0, y, w, h, 6); c.clipPath(pth, stroke=0, fill=0)
        cx = x0
        for i, (q, b, a) in enumerate(zip(self.paths, self.boxes, self.aspects)):
            pw = h * a
            ow = 0.6 if i < len(self.paths) - 1 else 0                # tiny overlap: no hairline seam between the two
            c.drawImage(embed(q, pw + ow, h, b), cx, y, pw + ow, h); cx += pw
        c.restoreState()

class Grid:
    def __init__(self, paths, cols=3, gap=3, f=1.0, box=None):
        self.paths, self.cols, self.gap, self.f, self.box = paths, cols, gap, f, box     # box: same crop for every cell
        self.a = aspect_box(paths[0], box); self.rows = -(-len(paths) // cols)
    def cell(self):
        w = (CW * self.f - self.gap * (self.cols - 1)) / self.cols
        return w, w / self.a
    def height(self):
        _, h = self.cell(); return self.rows * h + (self.rows - 1) * self.gap
    def draw(self, c, x, top):
        w, h = self.cell(); x0 = x + (CW - CW * self.f) / 2
        for i, p in enumerate(self.paths):
            r, k = divmod(i, self.cols)
            cx, cy = x0 + k * (w + self.gap), top - r * (h + self.gap) - h
            a = aspect_box(p, self.box)                     # contain-fit if an image deviates from the grid aspect
            dw, dh = (w, w / a) if a >= w / h else (h * a, h)
            rounded_image(c, p, cx + (w - dw) / 2, cy + (h - dh) / 2, dw, dh, 3, self.box)

# ------------------------------------------------------------------ panels
def build_panels(d, lang, s, img_f):
    st, L = styles(lang, s, V4_TITLE_CAP if d.get("layout") == "v4" else None), LANG[lang]
    T, sec = L["titles"], d["sections"]
    TD = [d.get("shown", {}).get(t, t) for t in T]          # section titles as written in the text
    P = lambda t, style, bold=False, **kw: Paragraph(mk(t, lang, bold), style, **kw)

    what = Flow([P(TD[0], st["title"])] + [P(l, st["body"]) for l in sec[T[0]]])
    hosp = Flow([P(TD[1], st["title"])] + [P(l, st["body"]) for l in sec[T[1]]])

    nurse_lines = sec[T[2]]
    checks = [l[1:].strip() for l in nurse_lines if l.startswith("☐")]
    first = next(i for i, l in enumerate(nurse_lines) if l.startswith("☐"))
    last = max(i for i, l in enumerate(nurse_lines) if l.startswith("☐"))
    pre, closing = nurse_lines[:first], [l for l in nurse_lines[last + 1:]]
    header = pre[-1] if pre and pre[-1].rstrip().endswith((":", ")", "):")) else None
    intro = pre[:-1] if header else pre
    nurse = Flow([P(TD[2], st["title_red"])] + [P(l, st["body"]) for l in intro]
                 + ([P(header, st["sub"])] if header else [])
                 + [Paragraph(mk(ck, lang), st["check"], bulletText="☐") for ck in checks])
    close = Flow([P(" ".join(closing), st["closing"])]) if closing else None

    num = d.get("emergency_no", L["emergency_no"])
    dis = Flow([P(TD[3], st["title"])] + [P(emphasize_emergency(l, lang, num), st["body"]) for l in sec[T[3]]])

    hab_lines = sec[T[4]]
    habits = Flow([P(TD[4], st["title"])]
                  + [P(l, st["body"]) for l in hab_lines if not l.startswith("- ")]
                  + [Paragraph(mk(l[2:], lang), st["bullet"], bulletText="•") for l in hab_lines if l.startswith("- ")])

    sup_lines = sec[T[5]]
    support = Flow([P(TD[5], st["title_red"])]
                   + [Paragraph(mk(l[2:], lang), st["bullet"], bulletText="•") for l in sup_lines if l.startswith("- ")])
    help_lines = [l for l in sup_lines if not l.startswith("- ")]          # "For more help: ..." sits lower, on its own
    foot = Flow([P(l, st["foot"]) for l in d["footer"]])

    im = d["images"]
    if d.get("layout") == "v4":
        para = ParagraphStyle("para", parent=st["body"], spaceAfter=V4_PARA_GAP * s)   # discharge: visibly separate paragraphs
        dis = Flow([P(TD[3], st["title"])] + [P(emphasize_emergency(l, lang, num), para) for l in sec[T[3]]])
        wb = [trim_box(p, "warn") for p in im["warnings"]]          # one crop for the whole row: union of the four
        wbox = (min(b[0] for b in wb), 0.0, max(b[2] for b in wb), max(b[3] for b in wb))
        return [
            ("between", [what, Pic(im["about_ich"], img_f[0], trim_box(im["about_ich"])), hosp]),
            ("between", [nurse, Grid(im["warnings"], cols=img_f[1][0], gap=4, f=img_f[1][1], box=wbox)] + ([close] if close else [])),
            ("bottom", [dis, Pic(im["emergency"], img_f[2], trim_box(im["emergency"]))]),   # emergency picture on the bottom edge
            ("between", [habits, Strip([p for _, p in im["habits"]], img_f[3], [trim_box(p) for _, p in im["habits"]])]),
            ("support", [support] + ([Flow([P(l, st["body"]) for l in help_lines])] if help_lines else []) + [foot]),
        ]
    return [
        ("between", [what, Pic(im["about_ich"], img_f[0]), hosp]),
        ("between", [nurse, Grid(im["warnings"], f=img_f[1])] + ([close] if close else [])),
        ("between", [dis, Pic(im["recovery"], img_f[2]), Pic(im["emergency"], img_f[2])]),
        ("between", [habits, Pic(im["habits"][0][1], img_f[3]), Pic(im["habits"][1][1], img_f[3])]),
        ("support", [support] + ([Flow([P(l, st["body"]) for l in help_lines])] if help_lines else []) + [foot]),
    ]

def panel_height(mode, blocks):
    extra = (HELP_GAP - GAP) if mode == "support" and len(blocks) == 3 else 0
    return sum(b.height() for b in blocks) + GAP * (len(blocks) - 1) + extra

def fit_v4(d, lang):
    """v4: text first. Largest font scale at which every panel fits with its images at some size in V4_IMG
    (each panel keeps the largest image size that still fits at that scale)."""
    s = V4_S_MAX
    while s >= S_MIN - 1e-9:
        img_f = []
        for i in range(4):
            for f in V4_IMG[i]:
                trial = img_f + [f] + [V4_IMG[j][-1] for j in range(i + 1, 4)]
                if panel_height(*build_panels(d, lang, s, trial)[i]) <= CH:
                    img_f.append(f); break
            else:
                break
        if len(img_f) == 4 and panel_height(*build_panels(d, lang, s, img_f)[4]) <= CH:
            return s, img_f, []
        s = round(s - S_STEP, 4)
    raise RuntimeError("content does not fit even at minimum scale")

def fit(d, lang):
    """Largest uniform font scale at which all content panels fit; shrink images only as a last resort."""
    if d.get("layout") == "v4": return fit_v4(d, lang)
    img_f = [1.0] * 4
    s = S_MAX
    while s >= S_MIN - 1e-9:
        if all(panel_height(m, b) <= CH for m, b in build_panels(d, lang, s, img_f)): return s, img_f, []
        s = round(s - S_STEP, 4)
    s, notes = S_MIN, []
    for f in (0.94, 0.88, 0.82, 0.76):
        panels = build_panels(d, lang, s, img_f)
        over = [i for i, (m, b) in enumerate(panels) if panel_height(m, b) > CH]
        if not over: return s, img_f, notes
        for i in over:
            if i < 4: img_f[i] = f; notes.append(f"panel{i + 1} images x{f}")
    raise RuntimeError("content does not fit even at minimum scale")

def draw_panel(c, idx, mode, blocks):
    x = (idx % 3) * PANEL_W + PAD_X
    if mode == "support":                               # items at top, help paragraph lower, footer on the bottom edge
        y = PH - PAD_T
        for b in blocks[:-1]:
            b.draw(c, x, y); y -= b.height() + HELP_GAP
        blocks[-1].draw(c, x, PAD_B + blocks[-1].height())
        return
    if mode == "bottom":                                # text from the top, last block (picture) on the bottom edge
        y = PH - PAD_T
        for b in blocks[:-1]:
            b.draw(c, x, y); y -= b.height() + GAP
        blocks[-1].draw(c, x, PAD_B + blocks[-1].height())
        return
    total = sum(b.height() for b in blocks)
    spread = (CH - total - GAP * (len(blocks) - 1)) / max(1, len(blocks) - 1)
    gap = GAP if mode == "top" or len(blocks) == 1 else GAP + min(spread, GAP_MAX - GAP)   # leftover beyond the cap goes to the bottom
    y = PH - PAD_T
    for b in blocks:
        b.draw(c, x, y); y -= b.height() + gap

def draw_cover(c, d, lang):
    L = LANG[lang]; x0 = 2 * PANEL_W + PAD_X; cx = x0 + CW / 2
    serif_b = "Georgia-Bold" if lang == "en" else "Malgun-Bold"
    serif = "Georgia" if lang == "en" else "Malgun"
    lines = L["cover_title"]
    size = 36 if len(lines) > 2 else 40                     # largest size at which every title line fits the panel
    while size > 20 and max(pdfmetrics.stringWidth(t, serif_b, size) for t in lines) > CW - 8: size -= 1
    y = PH - 130 if len(lines) > 2 else PH - 165
    c.setFillColor(INK)
    for text in lines:
        c.setFont(serif_b, size); c.drawCentredString(cx, y, text); y -= size + 8
    c.setStrokeColor(RED); c.setLineWidth(2); c.line(cx - 22, y + 2, cx + 22, y + 2); y -= 28
    sub = d["cover"].split(":")[0].strip() if lang == "en" else d["cover"]
    ps = ParagraphStyle("cv", fontName=serif_b, fontSize=19 if lang == "en" else 17, leading=24, alignment=TA_CENTER, textColor=INK)
    p = Paragraph(mk(sub, lang), ps); _, h = p.wrap(CW, 200); p.drawOn(c, x0, y - h); y -= h + 6
    if L["guide"]:
        pg = Paragraph(mk(L["guide"], lang), ParagraphStyle("gd", fontName=serif, fontSize=11, leading=14, alignment=TA_CENTER, textColor=GRAY))
        _, h = pg.wrap(CW, 100); pg.drawOn(c, x0, y - h); y -= h
    fy = min(200, y - 40)                                   # fields start well below the title block
    if fy - 34 * (len(L["fields"]) - 1) < 48:
        raise RuntimeError(f"cover overflow (fields start at {fy:.0f}pt)")
    for f in L["fields"]:
        c.setFont(serif_b, 11.5); c.setFillColor(INK); c.drawString(x0 + 10, fy, f + ":")
        lw = pdfmetrics.stringWidth(f + ":", serif_b, 11.5)
        c.setStrokeColor(colors.HexColor("#9AA3AB")); c.setLineWidth(0.7); c.line(x0 + 14 + lw, fy - 2.5, x0 + CW - 8, fy - 2.5)
        fy -= 34
    c.setFont(serif, 7); c.setFillColor(GRAY)
    c.drawCentredString(cx, 30, f"Case {d['no']:03d} · {d.get('dataset', 'BHSD')} {d['patient_id']}")

def fold_lines(c):
    c.setStrokeColor(RULE); c.setLineWidth(0.6)
    for k in (1, 2): c.line(k * PANEL_W, 16, k * PANEL_W, PH - 16)

def render(d, lang, out_path):
    s, img_f, notes = fit(d, lang)
    panels = build_panels(d, lang, s, img_f)
    c = rl_canvas.Canvas(out_path, pagesize=(PW, PH))
    c.setTitle(f"ICH patient-education brochure — case {d['no']:03d} ({LANG[lang]['suffix']})")
    c.setAuthor("ICH patient-education framework"); c.setSubject(d["subtypes"])
    fold_lines(c)
    for i in range(3): draw_panel(c, i, *panels[i])
    c.showPage()
    fold_lines(c)
    for i in range(3, 5): draw_panel(c, i - 3, *panels[i])
    draw_cover(c, d, lang)
    c.showPage(); c.save()
    return s, img_f, notes

# ------------------------------------------------------------------ main
def safe(x): return re.sub(r'[\\/:*?"<>|]', "", x)
def stem(o): return f"patient_{o['no']:03d}_{safe(o['subtypes'].replace(',', '-').replace(' ', ''))}_{o['sex']}_{safe(o['age_group'].replace('~', '-'))}"

def main():
    global IMG_ROOT
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=""); ap.add_argument("--lang", choices=["en", "ko"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cache", default=CACHE); ap.add_argument("--out", default=OUT_ROOT)
    ap.add_argument("--irb", default=None, help="IRB number printed in the footer (default: IRB_NO)")
    ap.add_argument("--images", default=IMG_ROOT, help="illustration folder (see tools/make_placeholder_images.py)")
    ap.add_argument("--image-map", default=None,
                    help="JSON that extends SIGN_FOLDER / HABIT_IMAGE_V4 / HABIT_NO_IMAGE_V4 for other content packs")
    a = ap.parse_args()
    IMG_ROOT = a.images
    if a.image_map:
        m = json.load(open(a.image_map, encoding="utf-8"))
        SIGN_FOLDER.update(m.get("SIGN_FOLDER", {})); HABIT_IMAGE_V4.update(m.get("HABIT_IMAGE_V4", {}))
        HABIT_NO_IMAGE_V4.update(m.get("HABIT_NO_IMAGE_V4", [])); HABIT_IDS.extend(m.get("HABIT_IDS", []))
    if not os.path.isdir(a.cache):
        sys.exit(f"cache folder not found: {a.cache} (run run_batch.py first, or pass --cache)")
    cache_dir, out_root = a.cache, a.out
    if a.irb is not None:
        global IRB_NO
        IRB_NO = a.irb
    idx = ImageIndex(IMG_ROOT)
    files = sorted(f for f in os.listdir(cache_dir) if f.endswith(".json"))
    if a.only: files = [f for f in files if int(f[:-5]) in {int(x) for x in a.only.split(",")}]
    if a.limit: files = files[:a.limit]
    langs = [a.lang] if a.lang else ["en", "ko"]
    for l in langs: os.makedirs(os.path.join(out_root, LANG[l]["suffix"]), exist_ok=True)
    rows, t0, errs = [], time.time(), 0
    for f in files:
        o = json.load(open(os.path.join(cache_dir, f), encoding="utf-8"))
        age, sex = BAND_TOKEN.get(o.get("age_band")) or age_token(o["age_used"]), "male" if o["sex"] == "M" else "female"
        for lang in langs:
            L = LANG[lang]; il = L["img_lang"]
            try:
                cover, sections, foot, shown = parse_md(o["en_md" if lang == "en" else "ko_md"], L["titles"], L["alt_titles"])
                n_em = 0                                        # emergency number in the body text (image untouched)
                v4 = str(o.get("generator", "")).startswith("v4")
                if L["emergency_no"] != "119" and not v4:       # legacy v2 English text still says 119
                    for t in sections:
                        fixed = [re.subn(r"\b119\b", L["emergency_no"], line) for line in sections[t]]
                        sections[t] = [x for x, _ in fixed]; n_em += sum(k for _, k in fixed)
                en_ko = o.get("emergency_number") or [LANG["en"]["emergency_no"], LANG["ko"]["emergency_no"]]
                num = str(en_ko[0 if lang == "en" else 1])                   # the edition's number, as the engine wrote it
                n_num = sum(len(re.findall(rf"(?<!\d){re.escape(num)}(?!\d)", line)) for line in sections[L["titles"][3]])
                if n_num != 1: print(f"  WARN #{o['no']:03d} {lang}: emergency number appears {n_num}x in the discharge section", flush=True)
                # v4: pictures for those of the first 4 checklist items that have a picture folder (others stay text only)
                warn_ids = ([v for v in o["signs"][:4] if v in SIGN_FOLDER] if v4
                            else [v for v in o["signs"] if v in SIGN_FOLDER][:6])        # v2/v3: grid of 6
                images = dict(about_ich=idx.about(age, sex),
                              warnings=[idx.sign(v, il, age, sex) for v in warn_ids],
                              emergency=idx.prognosis("emergency", il, age, sex),
                              habits=idx.habits_v4(o["habits"], age, sex) if v4 else idx.habits(o["habits"], age, sex))
                if not v4: images["recovery"] = idx.prognosis("recovery", il, age, sex)
                d = dict(no=o["no"], patient_id=o["patient_id"], dataset=o.get("dataset", "BHSD"), subtypes=o["subtypes"], cover=cover,
                         sections=sections, footer=foot, images=images, shown=shown, layout="v4" if v4 else "v2",
                         emergency_no=num)
                out = os.path.join(out_root, L["suffix"], f"{stem(o)}_{L['suffix']}.pdf")
                s, img_f, notes = render(d, lang, out)
                rows.append(dict(no=o["no"], patient_id=o["patient_id"], lang=L["suffix"], file=os.path.relpath(out, out_root),
                                 age=age, sex=sex, category=o["category"], font_scale=s, image_scale=";".join(f"{v[0]}col@{v[1]}" if isinstance(v, tuple) else str(v) for v in img_f),
                                 notes="; ".join(notes), emergency_no=num, emergency_replaced=n_em,
                                 signs="|".join(o["signs"]),
                                 habit_images="|".join(h for h, _ in images["habits"]),
                                 habit_image_files="|".join(os.path.relpath(q, IMG_ROOT) for _, q in images["habits"]),
                                 warning_images="|".join(os.path.relpath(p, IMG_ROOT) for p in images["warnings"]),
                                 about=os.path.relpath(images["about_ich"], IMG_ROOT),
                                 recovery=os.path.relpath(images["recovery"], IMG_ROOT) if "recovery" in images else "",
                                 emergency=os.path.relpath(images["emergency"], IMG_ROOT)))
            except Exception as e:
                errs += 1; print(f"  ERROR #{o['no']:03d} {lang}: {e}", flush=True)
        if o["no"] % 16 == 0: print(f"  ... #{o['no']:03d}  {round(time.time() - t0)}s", flush=True)
    if rows:
        mpath = os.path.join(out_root, "_manifest.csv")
        with open(mpath, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"done: {len(rows)} PDFs, {errs} errors, {round(time.time() - t0)}s -> {out_root}", flush=True)

if __name__ == "__main__":
    main()
