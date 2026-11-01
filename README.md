# Brochure Generation Framework for ICH Patient Education

A framework that turns structured findings of an intracranial hemorrhage (ICH) — bleed type, location, volume,
age and sex — into a bilingual (English / Korean), two-page tri-fold patient-education brochure.

The framework is built around one rule: **Python decides what is said, the language model only decides how it is said.**

```
findings ─► PatientProfile ─► ContentPlan ─────────► LLM wording ─► validators ─► Markdown (EN, KO) ─► tri-fold PDF
            parse type,       rules choose every     narrative and   keep facts,    fixed headings,      6 panels on 2 pages,
            location, volume, fact: risk tier,       habit items     hedges, the    checklist, support   pictures matched to
            age band          hospital, warning      (EN), then      emergency      and footnotes as     sign, habit, age band
                              signs, discharge,      Korean          number; else   EN/KO pairs          and sex, text-first
                              habits, support        translation     fixed text                          fit
```

* **Deterministic, auditable content.** Every fact on the page comes from a content pack and is chosen by rules from
  the patient profile. The plan is saved with each brochure.
* **The LLM rewrites; it does not add.** Wording is checked for missing facts, lost hedges ("may", "some"), new time
  frames, second-person address and the emergency number. A section or item that fails is replaced by the fixed
  sentences, so a complete brochure is always produced (also with no LLM at all: `ICH_DRY_RUN=1`).
* **Bilingual by construction.** Headings, the warning-sign checklist, support items and footnotes are fixed EN/KO pairs
  and never pass through the LLM. The two narrative sections and the four habit items are worded by the LLM in English
  and translated, with the Korean fixed text attached as required content; each habit item is checked on its own and
  replaced by its fixed EN/KO pair if it fails.
* **Layout.** One font scale per brochure, the largest at which all panels fit; pictures shrink before the text does.

## Contents

| Path | What it does |
|---|---|
| `ich_brochure/engine.py` | Input parsing, rule-based risk tier, content plan, LLM wording and translation, validators and fallback, Markdown rendering, readability (FKGL) |
| `ich_brochure/content_demo.py` | **Demo content pack** with the structure of the study's pack and illustrative sentences only |
| `ich_brochure/common.py` | Shared constants (categories, age bands, locales) |
| `run_batch.py` | Batch generation from a CSV to JSON caches |
| `render_brochures.py` | Tri-fold PDF layout: picture selection, cropping, text-first fit, cover |
| `tools/make_placeholder_images.py` | Placeholder pictures that follow the renderer's naming contract |
| `examples/` | Six synthetic cases and a one-command demo |
| `docs/content_pack.md` | How to write a content pack |

### Not included

* **The clinician-reviewed content pack used in the study** (sentence tables, age-, location- and laterality-specific
  branches, content-specific selection rules). It can be shared for non-commercial research under an agreement;
  please contact the corresponding author of the paper.
* **The illustration set used in the study.** The demo renders with generated placeholders.
* **Patient data.** No CT images or patient records are part of this repository. The brochures generated for the
  BHSD dataset in the study are archived on Zenodo (DOI to be added on publication).
* **API credentials.** The key is read from the environment only.

> **Not for clinical use.** The demo content is illustrative and is not medical advice. Brochures produced with any
> content pack must be reviewed by clinicians before they are given to patients. The risk tier in `engine.py`
> (`RISK_RULES`) only selects which level-of-care and procedure sentences are shown; its thresholds are a
> content-selection heuristic, not a validated clinical risk or triage score. `ICH_RISK_MODE=llm` is experimental:
> the LLM, not Python, then chooses the tier.

## Quick start

Python 3.10 or later.

```bash
pip install -r requirements.txt
python examples/run_demo.py
```

This creates placeholder pictures in `assets/images/`, generates six synthetic cases with fixed sentences (no LLM
call) and writes twelve PDFs to `outputs/demo/pdf/EN` and `outputs/demo/pdf/KO`.

To let an LLM write the narrative sections:

```bash
export ICH_API_KEY=...            # or OPENAI_API_KEY
export ICH_MODEL=...              # any chat model on an OpenAI-compatible endpoint
export ICH_BASE_URL=...           # optional, for a non-OpenAI endpoint
python examples/run_demo.py --llm
```

Step by step:

```bash
python tools/make_placeholder_images.py assets/images
python run_batch.py --inputs examples/demo_inputs.csv --out outputs/demo --dry
python render_brochures.py --cache outputs/demo/cache --out outputs/demo/pdf --images assets/images
```

## Input

One row per patient (`examples/demo_inputs.csv`):

| Column | Example | Notes |
|---|---|---|
| `case_id` | `3` | printed on the cover as "Case 003" |
| `age`, `sex` | `74`, `F` | age in years; sex M or F |
| `subtypes` | `IPH,IVH` | IPH, IVH, SAH, EDH, SDH |
| `location` | `right frontal convexity` | free text, mapped to location groups (`LOCATION_MAP` in `engine.py`) |
| `volume_ml` | `22` | total volume; empty = not measured |
| `traumatic` | `1` | optional; 1 = after a head injury (trauma path) |
| `dataset` | `demo` | optional label on the cover |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ICH_CONTENT` | `ich_brochure.content_demo` | content pack module |
| `ICH_DRY_RUN` | `0` | `1` = no LLM, fixed sentences only |
| `ICH_API_KEY` / `OPENAI_API_KEY` | – | API key |
| `ICH_BASE_URL` | OpenAI default | OpenAI-compatible endpoint |
| `ICH_MODEL` | model used in the study | chat model name |
| `ICH_TEMPERATURE`, `ICH_SEED` | `0.2`, `42` | sampling settings (recorded in every cache) |
| `ICH_RISK_MODE` | `rules` | `rules` (default) or `llm` |
| `ICH_EN_LOCALE` | `United States` | English edition: emergency number (`EMERGENCY_NUMBERS` in `engine.py`) and the support items of the content pack |
| `ICH_IRB_NO` | empty | IRB number in the footer (the renderer also takes `--irb`) |
| `ICH_FONT_DIR` | – | folder with the fonts below |

**Fonts.** The renderer uses Georgia, Arial Black, Arial Bold, Malgun Gothic and Segoe UI Symbol when they are present
(Windows). On other systems put open fonts in `assets/fonts/` or point `ICH_FONT_DIR` to them: Noto Serif
(Regular/Bold/Italic/BoldItalic), Noto Sans (Black, Bold), Noto Sans KR or NanumGothic (TrueType, Regular/Bold) and
DejaVu Sans.

## Using your own content and pictures

* **Content.** Copy `ich_brochure/content_demo.py` (for example to `my_pack.py` next to `run_batch.py`), replace the
  sentences and rules, and set `ICH_CONTENT=my_pack`. The module must be importable from the repository root. The
  required names, their shapes and the keywords the validators rely on are listed in
  [`docs/content_pack.md`](docs/content_pack.md).
* **Pictures.** Keep the folder and file-name contract described in `tools/make_placeholder_images.py`. New warning-sign
  or habit ids can be mapped to picture folders with `render_brochures.py --image-map map.json`.

## Outputs

`run_batch.py` writes one JSON per case (`outputs/<run>/cache/NNN.json`) with the profile, the plan (chosen facts,
signs, habits, support), the LLM text, the EN and KO Markdown, FKGL, word count, the validator log and the model
settings, plus `metrics.csv`. `render_brochures.py` writes the PDFs and `_manifest.csv` (font scale, picture sizes and
the picture file used in every slot).

## Tests

```bash
pip install pytest
python -m pytest tests
```

## Citation

If you use this framework, please cite the paper (reference to be added on publication) and this repository
(see `CITATION.cff`).

## License

Code: MIT (see `LICENSE`). The demo content and the placeholder pictures are illustrative only.

---

### 한국어 요약

뇌출혈의 유형, 위치, 출혈량, 나이, 성별을 입력하면 영문·국문 2페이지 3단 접지 환자 교육 브로셔를 만드는
프레임워크입니다. 내용은 파이썬 규칙이 콘텐츠 팩에서 고르고, LLM은 고른 사실을 쉬운 문장으로만 바꾸며, 검증을
통과하지 못하면 고정 문장을 씁니다. 이 저장소에는 엔진, 레이아웃, 데모 콘텐츠 팩이 있습니다. 연구에서 쓴 임상
검토 콘텐츠 팩과 그림 세트는 포함하지 않았습니다(연구 목적의 비상업적 사용은 논문 교신저자에게 문의). 데모
콘텐츠는 예시이며 진료에 쓸 수 없습니다.
