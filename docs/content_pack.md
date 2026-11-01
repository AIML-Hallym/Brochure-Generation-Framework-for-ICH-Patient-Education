# Content packs

A content pack is a Python module that holds every sentence the brochure can show and the content-specific selection
rules. The engine (`ich_brochure/engine.py`) loads it at import time from `ICH_CONTENT`
(default `ich_brochure.content_demo`) and refuses to start if a required name is missing.

All sentences are `(English, Korean)` pairs. Write each fact as one complete, plain sentence. Keep hedges ("may",
"can", "some"): the validators check that the LLM does not drop them. Do not put numbers in habit sentences (the habit
validator rejects digits).

`p` below is a `PatientProfile` (`engine.py`): `types` (e.g. `["IPH", "IVH"]`), `category` (`ICH` | `SAH` | `TBI`),
`locs` (location groups), `vol_ml`, `age`, `age_band` (`infant` | `child` | `teen` | `young` | `middle` | `older`),
`sex`, `risk` (`low` | `medium` | `high`), `loc_raw`.

## Required names

### Cover and footer
| Name | Shape |
|---|---|
| `CONTENT_NAME` | short label stored in every cache |
| `COVER_TITLE` | `{category: (EN, KO)}` |
| `GUIDELINES` | `{category: ([EN sources], [KO sources])}` — footnote |
| `FOOTER_NOTICE` | `{0: [EN lines], 1: [KO lines]}` — may use `{refs}` and `{irb}`; `""` = blank line |

### Section 1 — what is the bleed
| Name | Shape |
|---|---|
| `GENERAL_WHAT` | `[(EN, KO), ...]` shown to every patient |
| `FIRST_SENTENCE` | `{CAT_ICH, CAT_SAH, "IVH_ONLY": (EN, KO)}` — subtype summary for the habit prompt (not shown) |
| `TBI_SENTENCE` | `{"EDH", "SDH", "EDH+SDH", "OTHER": [(EN, KO), ...]}` — same, trauma path |
| `FIRST_SENTENCE_EXTRA` | `{"also_in_brain", "also_fluid", "also_around": (EN, KO)}` |

### Section 2 — hospital stay (validator keywords in brackets; keep them in the sentence)
| Name | Shape |
|---|---|
| `LEVEL_OF_CARE` | `{"high", "medium", "low": (EN, KO)}` [EN `intensive care` or `ICU`; KO `중환자실`] |
| `NEURO_CHECK` | `{"default", "infant", CAT_SAH: (EN, KO)}` [EN `awake`; KO `의식`] |
| `HOSPITAL_FACTS` | `{category: [(EN, KO, keep), ...]}` — `keep=True` survives the sentence budget [ICH keep item: `blood pressure` / `혈압`] |
| `HOSPITAL_PROCEDURE` | `{"high", "medium", "low": (EN, KO)}` [`surgery` / `수술`] |
| `TYPE_EXTRAS_HOSPITAL` | `{"SAH": [2 items], "IVH": [1], "IVH_ONLY": [1]}` [`weak spot`, `narrow` / `약한 부분`, `좁아`; `tube` / `관`; `cause` / `원인`] |

### Section 3 — warning signs (nurse call button)
| Name | Shape |
|---|---|
| `SIGN_POOL` | `[(id, severity 1-3, condition(p) -> bool, EN, KO), ...]` — the engine keeps the signs whose condition holds, sorts by severity (ties keep list order) and takes 6 (7 on the trauma path). If fewer qualify, the remaining slots are filled by severity regardless of the condition. Of the first four signs, those with a picture folder (`SIGN_FOLDER` in `render_brochures.py`) get pictures; the others are shown as text only. |

### Section 4 — after leaving the hospital
| Name | Shape |
|---|---|
| `RECOVERY_LINE`, `SOME_LAST_LINE`, `FOLLOWUP_LINE`, `DRIVING_LINE` | `(EN, KO)` |
| `LOC_SPEC` | `{location group: {"remain": (EN, KO), "fn"?: (EN, KO), "extra"?: (EN, KO)}}` — one entry for every group in `LOCATION_MAP` plus `lobar_generic`. `remain` is used for the first two locations of a patient (ventricle excluded). `fn` is not used by the engine (kept for reference). `extra` is read only for `occipital`: when present it replaces `DRIVING_LINE` for adults with an occipital bleed. |
| `REHAB_LINE` | `{"loc", "general": (EN, KO)}` |
| `TYPE_EXTRAS_DISCHARGE` | `{"SAH": [(EN, KO)]}` |
| `EMERGENCY_LEAD` | `{"SDH", "ventricle", "default": (EN, KO)}` |
| `EMERGENCY_CALL` | `{"default", "extra": (EN, KO)}` — `{num}` = emergency number, `{sx}` = symptom list; the last sentence must contain the number and "right away" / "바로" |
| `EMERGENCY_SX` | `{"SDH", "ventricle": ([EN symptoms], [KO symptoms])}` |

### Section 5 — healthy habits
| Name | Shape |
|---|---|
| `HABIT_POOL` | `[(id, priority, age-band set, condition(p), EN, KO), ...]` — children and infants take the first four by priority among the items of their band whose condition holds; if fewer qualify, the band's remaining items fill the slots regardless of the condition |
| `_adult_habit_ids` | `function(p) -> [4 ids]` — adults: one topic per domain. For adults the age-band set and condition in `HABIT_POOL` are not used; the ids only look up the sentences |
| `HABIT_DOMAINS_EN` | 4 domain labels used in the adult prompt |
| `HABIT_BRIEF` | `{id: (what to do, why, words to keep)}` — notes for the LLM; topics without a note are given the fixed sentence |
| `HABIT_REQ` | `{id: [regex, ...]}` — words an LLM item must contain, otherwise the fixed sentence is used |
| `HABIT_MAXW` | `{id: max words}` (default 24) |
| `SKILL_HOOK`, `LOC_TOPICS` | optional link between a location and location-driven topics (`{}` and `set()` to switch off) |

### Section 6 — support
| Name | Shape |
|---|---|
| `select_support` | `function(p) -> {"en": [...], "ko": [...]}` — items starting with `**` are bullets, others are paragraphs |

## Pictures for new ids

If your pack adds warning-sign or habit ids, map them to picture folders or habit pictures without editing the
renderer:

```json
{
  "SIGN_FOLDER": {"my_sign": "confusion"},
  "HABIT_IMAGE_V4": {"my_habit": ["my_habit", "gentle_walk"]},
  "HABIT_NO_IMAGE_V4": ["my_text_only_habit"],
  "HABIT_IDS": ["my_habit"]
}
```

`HABIT_IMAGE_V4` lists, per habit id, the picture topics to try in order; a picture file for a new topic is named
`health_habits/{band}_{sex}_..._{topic}.png`. Ids in `HABIT_IMAGE_V4` are indexed automatically; `HABIT_IDS` adds
further topic names. New warning-sign folders go under `warning_signs/{eng|kor}/{folder}/`.

```bash
python render_brochures.py --cache ... --out ... --images ... --image-map map.json
```
