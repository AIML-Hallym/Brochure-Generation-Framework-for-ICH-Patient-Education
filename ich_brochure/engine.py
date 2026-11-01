# -*- coding: utf-8 -*-
"""
ICH patient-education brochure engine (public release).

Design (see the paper):
  1. Python selects every fact.      PatientProfile -> ContentPlan: risk tier, hospital facts, warning signs,
                                      discharge facts, habits, support. The plan is deterministic and auditable.
  2. The LLM only words the facts.   write_prose (EN) turns the chosen facts into two short narrative sections and four
                                      habit items; translate_prose (KO) translates them.
  3. Validators guard the wording.   A section or item that fails its checks falls back to the fixed sentences,
                                      so a complete brochure is always produced.
  4. Headings, the warning-sign checklist, support items and footnotes are fixed EN/KO pairs and never pass through the
     LLM. Each habit item is checked on its own and replaced by its fixed EN/KO pair if it fails.

Clinical content (all sentence tables and the content-specific selection rules) lives in a separate *content pack*.
This repository ships a DEMO pack (ich_brochure/content_demo.py) with the same structure. Its sentences are
illustrative only and are NOT for clinical use. Point ICH_CONTENT at another module to use your own pack.

Configuration (environment variables):
  ICH_CONTENT      content pack module             (default: ich_brochure.content_demo)
  ICH_DRY_RUN      "1" = no LLM, fixed sentences   (default: "0")
  ICH_API_KEY      API key for an OpenAI-compatible endpoint (or OPENAI_API_KEY)
  ICH_BASE_URL     endpoint base URL               (default: the OpenAI default)
  ICH_MODEL        model name                      (default: the model used in the study)
  ICH_TEMPERATURE, ICH_SEED, ICH_RISK_MODE (rules | llm), ICH_EN_LOCALE, ICH_IRB_NO, ICH_OUT_DIR
"""
import os
import re
import json
import datetime
import importlib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .common import CAT_ICH, CAT_SAH, CAT_TBI, ADULT, WORK, MO, OLD, KIDS, INF, ANY, LOBAR, _fem, EN_LOCALE, KO_LOCALE

# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------
MODEL = os.environ.get("ICH_MODEL", "gpt-5.6-luna")          # model used in the study
TEMPERATURE = float(os.environ.get("ICH_TEMPERATURE", "0.2"))
SEED = int(os.environ.get("ICH_SEED", "42"))
DRY_RUN = os.environ.get("ICH_DRY_RUN", "0") == "1"
RISK_MODE = os.environ.get("ICH_RISK_MODE", "rules")          # rules (default) | llm
IRB_NO = os.environ.get("ICH_IRB_NO", "")
OUT_DIR = os.environ.get("ICH_OUT_DIR", "outputs")
TARGET_FKGL = 6.0           # Flesch-Kincaid grade target for the narrative text (one simpler rewrite above +0.5)
MAX_WORDS = 420             # word-count warning threshold
MAX_HOSPITAL_SENT = 4       # sentence budget of the hospital section
MAX_DISCHARGE_FACTS = 7     # fact budget of the discharge section (the emergency sentence is always kept)


def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


_client = None

def _get_client():
    """OpenAI-compatible client. The key is read from the environment only."""
    global _client
    if _client is None:
        key = os.environ.get("ICH_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Set ICH_API_KEY (or OPENAI_API_KEY), or run with ICH_DRY_RUN=1.")
        from openai import OpenAI
        _client = OpenAI(api_key=key, base_url=os.environ.get("ICH_BASE_URL") or None)
    return _client


# ------------------------------------------------------------
# Content pack: sentence tables and content-specific selection rules
# ------------------------------------------------------------
CONTENT_NAMES = (
    "CONTENT_NAME", "COVER_TITLE", "GUIDELINES", "FOOTER_NOTICE",
    "FIRST_SENTENCE", "TBI_SENTENCE", "FIRST_SENTENCE_EXTRA", "GENERAL_WHAT",
    "LEVEL_OF_CARE", "NEURO_CHECK", "HOSPITAL_FACTS", "HOSPITAL_PROCEDURE", "TYPE_EXTRAS_HOSPITAL",
    "RECOVERY_LINE", "SOME_LAST_LINE", "LOC_SPEC", "REHAB_LINE", "TYPE_EXTRAS_DISCHARGE", "FOLLOWUP_LINE", "DRIVING_LINE",
    "EMERGENCY_LEAD", "EMERGENCY_CALL", "EMERGENCY_SX",
    "SIGN_POOL",
    "HABIT_POOL", "HABIT_DOMAINS_EN", "HABIT_REQ", "HABIT_MAXW", "HABIT_BRIEF", "SKILL_HOOK", "LOC_TOPICS", "_adult_habit_ids",
    "select_support",
)

def _load_content(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    missing = [n for n in CONTENT_NAMES if not hasattr(mod, n)]
    if missing:
        raise ImportError(f"content pack {module_name} is missing: {missing}")
    globals().update({n: getattr(mod, n) for n in CONTENT_NAMES})

_load_content(os.environ.get("ICH_CONTENT", "ich_brochure.content_demo"))


SECTION_TITLES = [
    # key, EN, KO
    ("what",      "What is Brain Bleeding?",           "뇌출혈이란 무엇인가요?"),
    ("hospital",  "Hospital Stay",                     "입원 중 치료"),
    ("callbtn",   "When to Use the Nurse Call Button", "간호사 호출 버튼은 언제 누르나요?"),
    ("discharge", "What to Expect After Leaving the Hospital", "퇴원 후에는 어떻게 되나요?"),
    ("habits",    "Healthy Habits",                    "건강한 생활 습관"),
    ("support",   "Support and Resources in {country}", "도움받을 수 있는 곳"),
]

EMERGENCY_NUMBERS = {
    "South Korea": "119", "United States": "911", "Japan": "119", "China": "120",
    "United Kingdom": "999", "Germany": "112", "France": "15", "Vietnam": "115",
    "Thailand": "1669", "Philippines": "911", "Indonesia": "118", "India": "112",
}

def footer_refs(category: str) -> List[str]:
    """영문판 각주 근거 (카테고리별, 결정론적)."""
    return list(GUIDELINES[category][0])

def footer_refs_ko(category: str) -> List[str]:
    """국문판 각주 근거 (한국 지침 포함)."""
    return list(GUIDELINES[category][1])

# ------------------------------------------------------------
# PatientProfile — 입력 파싱
# ------------------------------------------------------------
TYPE_TOKENS = [
    ("EDH", ["edh", "epidural", "extradural"]),
    ("SDH", ["sdh", "subdural"]),
    ("SAH", ["sah", "subarachnoid"]),
    ("IVH", ["ivh", "intraventricular"]),
    ("IPH", ["iph", "ich", "intraparenchymal", "intracerebral", "parenchymal"]),
]

LOCATION_MAP = [
    ("brainstem",     ["brainstem", "brain stem", "pons", "pontine", "midbrain", "medulla"]),
    ("ventricle",     ["ventric", "ivh"]),
    ("basal_ganglia", ["basal ganglia", "putamen", "putaminal", "caudate", "globus pallidus",
                       "lentiform", "internal capsule", "thalam"]),
    ("cerebellum",    ["cerebell", "vermis", "posterior fossa"]),
    ("frontal",       ["frontal"]),
    ("temporal",      ["temporal", "sylvian"]),
    ("parietal",      ["parietal"]),
    ("occipital",     ["occipital"]),
    ("insula",        ["insula"]),
    ("deep_white",    ["corona radiata", "centrum semiovale", "subcortical", "white matter",
                       "periventricular"]),
    # SAH 분포 어휘
    ("cisternal",     ["cistern", "perimesencephalic", "prepontine", "suprasellar",
                       "interpeduncular", "ambient", "diffuse"]),
    # SDH/EDH/SAH 표면 어휘
    ("convexity",     ["convexity", "cortical", "surface", "hemispheric"]),
    ("midline",       ["falx", "interhemispheric", "tentori", "parasagittal"]),
]

@dataclass
class PatientProfile:
    htype_raw: str
    loc_raw: str
    vol_raw: str
    sex: Optional[str]          # "M" | "F" | None
    age: Optional[float]
    country: str
    # derived
    types: List[str] = field(default_factory=list)
    traumatic_flag: bool = False
    category: str = CAT_ICH
    locs: List[str] = field(default_factory=list)
    loc_fallback: bool = False
    vol_ml: Optional[float] = None
    age_band: str = "unknown"
    risk: str = "medium"
    risk_reason: str = ""
    age_lo: Optional[float] = None   # 연령 그룹 입력일 때 하한/상한 (지원 제도의 65세 조건 판단용)
    age_hi: Optional[float] = None

def parse_types(raw: str) -> Tuple[List[str], bool]:
    s = (raw or "").lower()
    found = []
    for canon, keys in TYPE_TOKENS:
        if any(k in s for k in keys) and canon not in found:
            found.append(canon)
    if "IPH" in found and not re.search(r"\b(iph|ich|intraparenchymal|intracerebral|parenchymal)\b", s):
        found.remove("IPH")
    traumatic = any(k in s for k in ["trauma", "tsah", "t-sah", "traumatic"])
    return found, traumatic

def classify_category(types: List[str], traumatic: bool) -> str:
    if traumatic or "EDH" in types or "SDH" in types:
        return CAT_TBI
    if "SAH" in types:
        return CAT_SAH
    return CAT_ICH

def classify_locations(raw: str) -> Tuple[List[str], bool]:
    s = (raw or "").lower()
    found = []
    for name, keys in LOCATION_MAP:
        if any(k in s for k in keys) and name not in found:
            found.append(name)
    if not found:
        log("WARN", f"위치 '{raw}' 를 사전에서 찾지 못해 lobar_generic 으로 폴백합니다. LOCATION_MAP 보강 필요.")
        return ["lobar_generic"], True
    return found, False

def parse_volume(raw: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)", raw or "")
    return float(m.group(1)) if m else None

def age_band_of(age: Optional[float]) -> str:
    if age is None: return "unknown"
    if age <= 2:  return "infant"
    if age <= 12: return "child"
    if age <= 18: return "teen"
    if age <= 39: return "young"
    if age <= 64: return "middle"
    return "older"

def normalize_country(nationality: Optional[str]) -> str:
    if not nationality: return "South Korea"
    n = nationality.strip().lower()
    if any(k in n for k in ["korea", "한국", "대한민국"]): return "South Korea"
    if n in ["usa", "us", "united states", "united states of america", "america"]: return "United States"
    if any(k in n for k in ["japan", "일본"]): return "Japan"
    if any(k in n for k in ["china", "중국"]): return "China"
    return nationality.strip()

# ------------------------------------------------------------
# 위험도 — 규칙 기반 (기본) / LLM (옵션)
# The tier only selects which level-of-care and procedure sentences are shown. The thresholds are a content-selection
# heuristic, not a validated clinical risk or triage score, and must not be used for clinical decisions.
# ICH_RISK_MODE=llm is experimental: the LLM, not Python, then chooses the tier.
# 임계값은 임상의 검토용으로 한 곳에 모아둠.
#   floor 규칙: 최소 등급을 보장 (medium 이상 등) — 누적되지 않음
#   bump  규칙: 한 단계 상향 — 누적 가능
# ------------------------------------------------------------
RISK_RULES = {
    # type: (low_upper, high_lower)  →  v < low_upper: low, v >= high_lower: high, else medium
    "IPH": (10.0, 30.0),
    "IVH": (5.0, 15.0),
    "EDH": (15.0, 30.0),
    "SDH": (10.0, 30.0),
    "floors": {
        "brainstem": "high",
        "deep_iph_ge10": "medium",          # 기저핵/시상 IPH ≥10 mL
        "cerebellum": "medium",             # 소뇌: 최소 medium, >15 mL 이면 high
        "temporal_edh_ge10": "medium",      # 측두 EDH ≥10 mL
        "sah_cisternal_or_unknown": "high",
        "sah_perimesencephalic": "medium",  # 양성 패턴이지만 혈관 검사 전까지 medium
    },
    "bumps": {
        "iph_with_ivh": True,               # IVH 확장 → +1
        "three_or_more_types": True,        # 3구획 이상 → +1
    },
}
_LEVELS = ["low", "medium", "high"]

def _tier(v: Optional[float], lo: float, hi: float) -> int:
    if v is None: return 1
    return 0 if v < lo else (2 if v >= hi else 1)

def classify_risk_rules(p: PatientProfile) -> Tuple[str, str]:
    v, T, L = p.vol_ml, set(p.types), set(p.locs)
    F, B = RISK_RULES["floors"], RISK_RULES["bumps"]
    raw_loc = p.loc_raw.lower()
    reasons, tiers = [], []
    for t in ("IPH", "EDH", "SDH"):
        if t in T:
            tiers.append(_tier(v, *RISK_RULES[t])); reasons.append(f"{t}:{v}mL")
    if "IVH" in T and "IPH" not in T:
        tiers.append(_tier(v, *RISK_RULES["IVH"])); reasons.append(f"IVH:{v}mL")
    if "SAH" in T:
        if "perimesencephalic" in raw_loc:
            tiers.append(_LEVELS.index(F["sah_perimesencephalic"])); reasons.append("SAH perimesencephalic")
        elif "cisternal" in L or p.loc_fallback:
            tiers.append(_LEVELS.index(F["sah_cisternal_or_unknown"])); reasons.append("SAH cisternal/unknown")
        else:
            tiers.append(1); reasons.append("SAH localized")
    score = max(tiers) if tiers else 1

    def floor(level, tag):
        nonlocal score
        i = _LEVELS.index(level)
        if score < i: score = i; reasons.append(f"floor:{tag}")
    if "brainstem" in L: floor(F["brainstem"], "brainstem")
    if "basal_ganglia" in L and "IPH" in T and (v or 0) >= 10: floor(F["deep_iph_ge10"], "deep")
    if "cerebellum" in L:
        floor(F["cerebellum"], "cerebellum")
        if v and v > 15: floor("high", "cerebellum>15")
    if "EDH" in T and "temporal" in L and (v or 0) >= 10: floor(F["temporal_edh_ge10"], "temporal-EDH")

    def bump(tag):
        nonlocal score
        if score < 2: score += 1; reasons.append(f"+{tag}")
    if B["iph_with_ivh"] and "IPH" in T and "IVH" in T: bump("IVH-ext")
    if B["three_or_more_types"] and len(T) >= 3: bump("multi")
    return _LEVELS[min(score, 2)], "; ".join(reasons)

def classify_risk_llm(p: PatientProfile) -> Tuple[str, str]:
    prompt = (
        "You are a neurocritical care expert. Classify overall clinical risk.\n"
        f"- Types: {', '.join(p.types) or p.htype_raw}\n- Location: {p.loc_raw}\n- Volume: {p.vol_raw}\n"
        "Rules of thumb: brainstem = high; deep (basal ganglia/thalamus) IPH >=10 mL = medium-high; "
        "IPH >=30 mL = high; IVH extension raises risk; EDH/SDH surgical threshold ~30 mL; "
        "cisternal SAH = high.\n"
        'Reply with JSON only: {"risk": "low|medium|high", "reason": "<10 words>"}'
    )
    raw = call_llm([{"role": "user", "content": prompt}], max_tokens=80)
    d = _parse_json(raw) or {}
    r = re.sub(r"[^a-z]", "", str(d.get("risk", "")).lower())
    if r not in _LEVELS:
        log("WARN", f"LLM 위험도 응답 해석 실패({raw!r}) → medium"); r = "medium"
    return r, "LLM: " + str(d.get("reason", ""))

def build_profile(htype, hloc, hvol, sex, age, nationality, age_range=None) -> PatientProfile:
    p = PatientProfile(htype, hloc, hvol, (sex or "").strip().upper()[:1] or None, age, normalize_country(nationality))
    p.age_lo, p.age_hi = age_range if age_range else (age, age)
    p.types, p.traumatic_flag = parse_types(htype)
    p.category = classify_category(p.types, p.traumatic_flag)
    p.locs, p.loc_fallback = classify_locations(hloc)
    p.vol_ml = parse_volume(hvol)
    p.age_band = age_band_of(age)
    if RISK_MODE == "llm" and not DRY_RUN:
        p.risk, p.risk_reason = classify_risk_llm(p)
    else:
        p.risk, p.risk_reason = classify_risk_rules(p)
    log("INFO", f"types={p.types} category={p.category} locs={p.locs} vol={p.vol_ml} "
                f"age_band={p.age_band} sex={p.sex} risk={p.risk} ({p.risk_reason})")
    return p

def select_signs(p: PatientProfile, n: int = 6) -> List[Tuple[str, str, str]]:
    cands = [(sid, sev, en, ko) for sid, sev, when, en, ko in SIGN_POOL if when(p)]
    cands.sort(key=lambda x: x[1])
    picked = cands[:n]
    if len(picked) < n:
        for sid, sev, when, en, ko in sorted(SIGN_POOL, key=lambda x: x[1]):
            if len(picked) == n: break
            if all(sid != q[0] for q in picked):
                picked.append((sid, sev, en, ko))
    return [(sid, en, ko) for sid, sev, en, ko in picked]

def _habit_hooks(plan) -> List[Optional[Tuple[str, str]]]:
    """병변 위치에서 나온 주제에만 '영향받을 수 있는 기능'을 연결 (억지 연결 방지). 나머지 항목은 연결 없음."""
    p = plan.profile
    skill = next((SKILL_HOOK[l] for l in p.locs if l in SKILL_HOOK), None)
    return [skill if (skill and hid in LOC_TOPICS and p.age_band in ADULT) else None for hid, _, _ in plan.habits]

def _habit_brief(hid: str, fixed_en: str) -> str:
    if hid not in HABIT_BRIEF:
        return fixed_en                                         # 소아·영아 주제는 검토 문장 그대로
    do, why, keep = HABIT_BRIEF[hid]
    return f"do: {do} | why: {why}" + (f" | must keep the words: {keep}" if keep else "")

def select_habits(p: PatientProfile, n: int = 4) -> List[Tuple[str, str, str]]:
    band = p.age_band
    if band in ADULT:
        by_id = {hid: (en, ko) for hid, pr, ages, when, en, ko in HABIT_POOL}
        return [(hid, *by_id[hid]) for hid in _adult_habit_ids(p)][:n]
    pool = sorted([h for h in HABIT_POOL if band in h[2]], key=lambda h: h[1])
    picked = [(hid, en, ko) for hid, pr, ages, when, en, ko in pool if when(p)][:n]
    if len(picked) < n:
        log("WARN", f"습관 후보 {len(picked)}개 < {n}. 같은 연령대 안에서 조건을 완화해 채웁니다.")
        for hid, pr, ages, when, en, ko in pool:
            if len(picked) == n: break
            if all(hid != q[0] for q in picked):
                picked.append((hid, en, ko))
    return picked

# ------------------------------------------------------------
# ContentPlan — 파이썬이 확정하는 선택 결과
# ------------------------------------------------------------
@dataclass
class ContentPlan:
    profile: PatientProfile
    cover_title: Tuple[str, str]
    what: List[Tuple[str, str]]
    hospital_facts: List[Tuple[str, str]]
    signs: List[Tuple[str, str, str]]
    discharge_facts: List[Tuple[str, str]]
    habits: List[Tuple[str, str, str]]
    support: Dict[str, List[str]]
    emergency_number: Tuple[str, str]      # (영문, 국문)
    refs: List[str]
    trimmed: List[str] = field(default_factory=list)
    bleed_detail: List[Tuple[str, str]] = field(default_factory=list)   # v4: 아형별 위치 문장 (LLM 환자 요약용, 화면에는 안 나옴)
    discharge_groups: List[int] = field(default_factory=list)          # v4: 퇴원 사실별 문단 번호 (0 회복, 1 추적·운전, 2 응급)
    refs_ko: List[str] = field(default_factory=list)                    # v4: 국문판 각주 근거

def _join_en(xs: List[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + (", or " if len(xs) > 2 else " or ") + xs[-1]

def _join_ko(xs: List[str]) -> str:
    s = ", ".join(xs); ch = s[-1]
    has_final = "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0
    return s + ("이" if has_final else "가")

def build_plan(p: PatientProfile) -> ContentPlan:
    num_en = EMERGENCY_NUMBERS.get(EN_LOCALE, "the emergency number")
    num_ko = EMERGENCY_NUMBERS[KO_LOCALE]
    T = set(p.types)
    trimmed = []

    # 1) What — v4: 화면에는 일반 설명(GENERAL_WHAT) 3문장만.
    #    아래의 아형별 위치 문장(v3 §1)은 bleed_detail 로만 남겨 생활습관 LLM 의 환자 요약에 쓴다.
    extra_keys = []
    if p.category == CAT_TBI:
        sub = "EDH+SDH" if {"EDH", "SDH"} <= T else "EDH" if "EDH" in T else "SDH" if "SDH" in T else "OTHER"
        what = list(TBI_SENTENCE[sub])
        if "IPH" in T: extra_keys.append("also_in_brain")
        if "IVH" in T: extra_keys.append("also_fluid")
        if "SAH" in T: extra_keys.append("also_around")          # 외상성 SAH: 위치만 설명 (동맥류 문장 없음)
    elif p.category == CAT_ICH and T == {"IVH"}:
        what = [FIRST_SENTENCE["IVH_ONLY"]]
    else:
        what = [FIRST_SENTENCE[p.category]]
        if p.category == CAT_SAH and "IPH" in T: extra_keys.append("also_in_brain")
        if "IVH" in T: extra_keys.append("also_fluid")
    what += [FIRST_SENTENCE_EXTRA[k] for k in extra_keys[:2]]
    bleed_detail = what
    what = list(GENERAL_WHAT)                                   # v4: 공통 문장(관찰·혈압·재활)은 §1 에서 뺌

    # 2) Hospital — [필수: 입원 수준, 유형 문장, 신경 관찰, 카테고리 필수] + [선택: 카테고리 일반, 수술]
    must = [LEVEL_OF_CARE[p.risk]]
    if p.category == CAT_SAH: must += TYPE_EXTRAS_HOSPITAL["SAH"]        # 동맥류 관련 문장은 SAH 카테고리에만
    if "IVH" in T: must += TYPE_EXTRAS_HOSPITAL["IVH"]
    if T == {"IVH"} and p.category != CAT_TBI: must += TYPE_EXTRAS_HOSPITAL["IVH_ONLY"]   # 2026-10-27: 외상성 IVH 단독에는 혈관 원인 검사 문장을 넣지 않음
    must.append(NEURO_CHECK["infant"] if p.age_band == "infant" else NEURO_CHECK.get(p.category, NEURO_CHECK["default"]))
    optional = []
    for en, ko, keep in HOSPITAL_FACTS[p.category]:
        (must if keep else optional).append((en, ko))
    if p.category != CAT_SAH:
        optional.insert(0, HOSPITAL_PROCEDURE[p.risk])          # v4: 선택 문장 중 수술 가능성을 먼저
    hosp, n = list(must), sum(len(_sentences(e)) for e, _ in must)
    for item in optional:                                       # 문장 수 상한까지 선택 문장을 채움
        k = len(_sentences(item[0]))
        if n + k <= MAX_HOSPITAL_SENT: hosp.append(item); n += k
        else: trimmed.append("hospital: " + item[0][:50])

    # 3) Signs — 외상은 7개 (코·귀 맑은 액체 + 편측 약화 모두 유지)
    signs = select_signs(p, 7 if p.category == CAT_TBI else 6)

    # 4) Discharge — 회복 / 위치별 문제(≤2, 단정 없음) / 재활 / 추적·운전 / 응급(아형별 앞 문장 + 응급번호 1회)
    dis = [RECOVERY_LINE]
    loc_lines = [LOC_SPEC[l]["remain"] for l in p.locs[:2] if l != "ventricle"]
    dis += (loc_lines + [REHAB_LINE["loc"]]) if loc_lines else [SOME_LAST_LINE, REHAB_LINE["general"]]
    if p.category == CAT_SAH: dis += TYPE_EXTRAS_DISCHARGE["SAH"]
    else: dis.append(FOLLOWUP_LINE)                             # v4: ICH 와 외상(TBI) 모두 외래 추적 안내
    if p.age_band in ADULT:
        dis.append(LOC_SPEC.get("occipital", {}).get("extra", DRIVING_LINE) if "occipital" in p.locs else DRIVING_LINE)
    lead_keys = [k for k, ok in (("SDH", "SDH" in T), ("ventricle", "ventricle" in p.locs)) if ok]
    lead = EMERGENCY_LEAD[lead_keys[0] if lead_keys else "default"]
    if lead_keys:
        sx_en, sx_ko = [], []
        for k in lead_keys:
            for e, kk in zip(*EMERGENCY_SX[k]):
                if e not in sx_en: sx_en.append(e); sx_ko.append(kk)
        call = (EMERGENCY_CALL["extra"][0].format(num=num_en, sx=_join_en(sx_en)),
                EMERGENCY_CALL["extra"][1].format(num=num_ko, sx=_join_ko(sx_ko)))
    else:
        call = (EMERGENCY_CALL["default"][0].format(num=num_en), EMERGENCY_CALL["default"][1].format(num=num_ko))
    n_rec = 1 + (len(loc_lines) + 1 if loc_lines else 2)       # v4: 문단 1 = 회복·위치별 문제·재활
    if len(dis) > MAX_DISCHARGE_FACTS - 1:                      # 응급 문장은 항상 남김
        trimmed += ["discharge: " + e[:50] for e, _ in dis[MAX_DISCHARGE_FACTS - 1:]]
        dis = dis[:MAX_DISCHARGE_FACTS - 1]
    dis.append((lead[0] + " " + call[0], lead[1] + " " + call[1]))
    dis_groups = [0 if i < n_rec else 1 for i in range(len(dis) - 1)] + [2]   # 문단 2 = 추적·운전, 문단 3 = 응급

    if trimmed:
        log("INFO", f"분량 상한으로 제외된 문장 {len(trimmed)}개: {trimmed}")

    return ContentPlan(
        profile=p, cover_title=COVER_TITLE[p.category], what=what, hospital_facts=hosp,
        signs=signs, discharge_facts=dis, habits=select_habits(p, 4),
        support=select_support(p), emergency_number=(num_en, num_ko), refs=footer_refs(p.category), refs_ko=footer_refs_ko(p.category),
        trimmed=trimmed, bleed_detail=bleed_detail, discharge_groups=dis_groups,
    )

# ------------------------------------------------------------
# LLM — 문장화 전용
# ------------------------------------------------------------
def call_llm(messages, max_tokens: Optional[int] = None) -> str:
    import time
    kw = {"model": MODEL, "messages": messages, "temperature": TEMPERATURE, "seed": SEED}
    if max_tokens: kw["max_tokens"] = max_tokens
    for attempt in range(3):
        try:
            r = _get_client().chat.completions.create(**kw)
            return r.choices[0].message.content.strip()
        except Exception as e:
            log("WARN", f"call_llm {attempt+1}/3 실패: {e}")
            if attempt < 2: time.sleep(5)
            else: raise

def _parse_json(raw: str) -> Optional[dict]:
    if not raw: return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    m = re.search(r"\{.*\}", s, re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None

def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]

_YOU = re.compile(r"\b(you|your|yours|yourself)\b", re.I)
_HEDGE = re.compile(r"\b(may|might|can|could|some|often)\b", re.I)
def _hedges(text: str) -> int: return len(_HEDGE.findall(text))

PLAIN_TERMS = (
    "Allowed plain phrases (use these instead of jargon): 'a weak spot on a blood vessel' (aneurysm), "
    "'a thin tube to drain fluid' (EVD), 'a procedure to relieve pressure' (surgery), "
    "'the brain's covering' (dura), 'shaking spells' (seizure), 'part of the vision is missing' (field cut).\n"
    "Never use: neglect, deficit, impairment, lesion, aphasia, dysarthria, hemiplegia, paresis, "
    "hydrocephalus, vasospasm, craniotomy, coiling, clipping, or drug names."
)

def _habit_context(plan: ContentPlan) -> str:
    """습관 문장을 환자에 맞게 쓰도록 LLM 에 주는 쉬운 말 요약 (새 의학 정보는 넣지 않음)."""
    p = plan.profile
    if p.age_lo is not None and p.age_hi is not None and p.age_lo != p.age_hi:
        age = f"{int(p.age_lo)}+" if p.age_hi >= 100 else f"{int(p.age_lo)}-{int(p.age_hi)}"
    else:
        age = f"{int(p.age)}" if p.age is not None else "unknown"
    stage = {"older": "older adult", "young": "working-age adult", "middle": "working-age adult",
             "teen": "teenager", "child": "child", "infant": "baby"}.get(p.age_band, "adult")
    sex = {"F": "woman", "M": "man"}.get(p.sex or "", "not given")
    skills = " ".join(LOC_SPEC[l]["remain"][0] for l in p.locs[:2] if l in LOC_SPEC) or "none listed"
    cause = "after a head injury" if p.category == CAT_TBI else "not from an injury"
    return (f"- Bleed: {' '.join(e for e, _ in plan.bleed_detail)} ({cause})\n"
            f"- Skills that may be affected: {skills}\n"
            f"- Age group: {age} ({stage}), {sex}\n"
            f"- Severity estimate: {p.risk}")

def _check_habits(plan: ContentPlan, items, lang: int) -> Tuple[List[str], int]:
    """항목별 검증. 실패한 항목만 검토된 고정 문장으로 대체. (문장 목록, 대체 개수)"""
    fixed = [(en, ko)[lang] for _, en, ko in plan.habits]
    if not isinstance(items, list) or len(items) != len(fixed):
        return fixed, len(fixed)
    out, n_fb = [], 0
    for (hid, _, _), fx, h in zip(plan.habits, fixed, items):
        h = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", str(h)).strip()
        if lang == 0:                                           # 세미콜론은 문장으로 나눔 (FKGL), 빗금은 실패 처리
            h = re.sub(r";\s*(\w)", lambda m: ". " + m.group(1).upper(), h)
            ok = (8 <= len(h.split()) <= HABIT_MAXW.get(hid, 24) and not _YOU.search(h) and not re.search(r"\d|/", h)
                  and not re.search(r"\b(older|elderly|senior|man|woman|men|women|male|female)\b", h, re.I)
                  and not re.search(r"\b(check|take|use|watch|do) it\b", h, re.I)
                  and all(re.search(rx, h, re.I) for rx in HABIT_REQ.get(hid, [])))
        else:
            ok = 22 <= len(h) <= 100 and not re.search(r"당신|귀하|\d|어르신|고령자|노인|남성|여성", h)
        if ok and h[-1] not in ".!?": h += "."
        if not ok: log("WARN", f"생활습관 검증 실패 [{hid}] {('EN', 'KO')[lang]}: {h[:100]}")
        out.append(h if ok else fx); n_fb += (not ok)
    return out, n_fb

DIS_PARA_LABEL = ("recovery", "check-ups and daily life", "warning signs and emergency")
# 퇴원 산문에 새로 생기면 안 되는 시간 표현 (사실 문장에 있는 횟수보다 많으면 실패)
_TIME_WORDS = (r"\bduring\b", r"\bperiod\b", r"\bfor a while\b", r"\bdays?\b", r"\bweeks?\b", r"\bmonths?\b",
               r"\byears?\b", r"\bsoon\b", r"\blong time\b", r"\bforever\b", r"\bpermanent")

def _hosp_keys(plan) -> List[Tuple[str, str]]:
    """v4: 입원 섹션의 필수 사실마다 LLM 산문에 남아 있어야 하는 핵심어 (없으면 그 산문은 쓰지 않음)."""
    keys = {}
    for k in LEVEL_OF_CARE: keys[LEVEL_OF_CARE[k][0]] = r"intensive care|ICU"
    for k in NEURO_CHECK: keys[NEURO_CHECK[k][0]] = r"awake"
    sah = TYPE_EXTRAS_HOSPITAL["SAH"]
    keys[sah[0][0]] = r"weak spot"; keys[sah[1][0]] = r"narrow"
    keys[TYPE_EXTRAS_HOSPITAL["IVH"][0][0]] = r"tube"
    keys[TYPE_EXTRAS_HOSPITAL["IVH_ONLY"][0][0]] = r"\bcause\b"
    for e, _, keep in HOSPITAL_FACTS[CAT_ICH]:
        if keep: keys[e] = r"blood pressure"
    for k in HOSPITAL_PROCEDURE: keys[HOSPITAL_PROCEDURE[k][0]] = r"surgery"
    return [(e, keys[e]) for e, _ in plan.hospital_facts if e in keys]

def _hosp_keys_ko(plan) -> List[str]:
    """v4: 국문 입원 산문에 남아 있어야 하는 사실별 핵심어 (영문 _hosp_keys 와 같은 사실)."""
    keys = {}
    for k in LEVEL_OF_CARE: keys[LEVEL_OF_CARE[k][1]] = r"중환자실"
    for k in NEURO_CHECK: keys[NEURO_CHECK[k][1]] = r"의식"
    sah = TYPE_EXTRAS_HOSPITAL["SAH"]
    keys[sah[0][1]] = r"약한 부분|약해진 부분|약한 곳"; keys[sah[1][1]] = r"좁아"
    keys[TYPE_EXTRAS_HOSPITAL["IVH"][0][1]] = r"관을|관이|관으로|튜브|배액"
    keys[TYPE_EXTRAS_HOSPITAL["IVH_ONLY"][0][1]] = r"뇌혈관|원인"
    for _, ko, keep in HOSPITAL_FACTS[CAT_ICH]:
        if keep: keys[ko] = r"혈압"
    for k in HOSPITAL_PROCEDURE: keys[HOSPITAL_PROCEDURE[k][1]] = r"수술"
    return [keys[ko] for _, ko in plan.hospital_facts if ko in keys]

def _dis_groups(plan) -> List[Tuple[int, List[int]]]:
    """v4: 퇴원 사실을 문단별로 묶은 (문단 번호, 사실 인덱스) 목록. 비어 있는 문단은 없음."""
    g = plan.discharge_groups or [0] * (len(plan.discharge_facts) - 1) + [2]
    return [(k, [i for i, x in enumerate(g) if x == k]) for k in (0, 1, 2) if k in g]

def _dis_paragraphs(plan, lang: int) -> List[str]:
    return [" ".join(plan.discharge_facts[i][lang] for i in idxs) for _, idxs in _dis_groups(plan)]

def write_prose(plan: ContentPlan, simpler: bool = False) -> Dict[str, object]:
    """입원/퇴원 두 섹션 산문화 + 생활습관 문장화(주제는 계획이 정함). 검증 실패 시 해당 부분만 스켈레톤."""
    hosp_sk = [en for en, _ in plan.hospital_facts]
    dis_sk  = [en for en, _ in plan.discharge_facts]
    hab_sk  = [en for _, en, _ in plan.habits]
    dis_grp = _dis_groups(plan)
    fallback = {"hospital": " ".join(hosp_sk), "discharge": _dis_paragraphs(plan, 0), "habits": list(hab_sk)}
    if DRY_RUN:
        return fallback
    num = plan.emergency_number[0]
    n_hosp = sum(len(_sentences(s)) for s in hosp_sk)
    n_dis = sum(len(_sentences(s)) for s in dis_sk)
    labels = HABIT_DOMAINS_EN if plan.profile.age_band in ADULT else None
    hooks = _habit_hooks(plan)
    sys_p = (
        "You write patient handouts at U.S. grade 5-6 reading level. Calm, warm, honest.\n"
        "Never use 'you' or 'your'. Write about 'the patient', or give direct instructions (for example, 'Do not drive ...').\n"
        "Nurses reviewed these facts. Keep their meaning and their careful words: keep every 'may', 'can', 'some', and "
        "'often'; never turn a possibility into a promise; never add facts, numbers, time frames, or advice.\n"
        "Prefer common one- or two-syllable words. Keep connecting words (because, so, when) — do not chop ideas into fragments.\n"
        + PLAIN_TERMS + "\n"
        + ("EXTRA: use even shorter, more common words; keep every fact.\n" if simpler else "")
        + 'Return JSON only: {"hospital": "<paragraph>", "discharge": ["<paragraph>", ...], "habits": ["<item>", ...]}'
    )
    user_p = (
        "[Hospital Stay — facts, keep ALL, keep sentence 1 exactly as given, write as ONE short paragraph of about "
        f"{n_hosp} sentences, at most {max(65, len(' '.join(hosp_sk).split()))} words total]\n"
        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(hosp_sk))
        + f"\n\n[What to Expect After Leaving the Hospital — facts, keep ALL, in THIS order, written as EXACTLY {len(dis_grp)} "
          f"short paragraphs grouped as shown (about {n_dis} sentences in total, 6-20 words each); the LAST paragraph must keep "
          f"the phone number {num} and 'right away']\n"
        + "\n".join(f"Paragraph {j+1} ({DIS_PARA_LABEL[k]}):\n" + "\n".join(f"{i+1}. {dis_sk[i]}" for i in idxs)
                    for j, (k, idxs) in enumerate(dis_grp))
        + f"\n\n[Healthy Habits — write EXACTLY {len(hab_sk)} items, in THIS order, one per idea below. These ideas are notes, "
          "not finished sentences: write each item in plain words for THIS patient. Each item: one sentence "
          "(or two short ones), 12-20 words in total, the action first and then the reason. Write complete, natural sentences "
          "with all the small words (the, a, to); do not shorten phrases (write 'high blood pressure', not 'high pressure'). "
          "Keep 'can' and 'may' wherever the idea has them. Do not write 'check it' or 'take it' "
          "(write 'check blood pressure'); 'they' and 'these' are fine. Keep words like 'for', 'when', and 'while'. When an idea says 'link to this patient', "
          "mention that detail briefly and naturally; otherwise do not add links. Never describe the patient by age or sex "
          "(no 'older adult', 'man', 'woman'). Do not repeat the same phrase in two items. Keep any 'must keep' words. Add no new "
          "medical facts, numbers, or drug names. Do not use slashes or semicolons.]\n"
        + "Patient:\n" + _habit_context(plan) + "\nIdeas:\n"
        + "\n".join(f"{i+1}. " + (f"({labels[i]}) " if labels else "") + _habit_brief(h[0], h[1])
                    + (f" | link to this patient: {hooks[i][0]}" if hooks[i] else "") for i, h in enumerate(plan.habits))
    )
    try:
        raw = call_llm([{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}])
        d = _parse_json(raw) or {}
        dl = d.get("discharge")
        dl = [str(x).strip() for x in dl] if isinstance(dl, list) else []
        dis = " ".join(dl)
        ds = _sentences(dis)
        last = _sentences(dl[-1]) if dl else []
        ok = (len(dl) == len(dis_grp) and all(dl) and ds and abs(len(ds) - n_dis) <= 1 and last
              and num in last[-1] and "right away" in last[-1] and dis.count(num) == 1
              and not _YOU.search(dis) and _hedges(dis) >= _hedges(" ".join(dis_sk)) - 1)
        added = [w for w in _TIME_WORDS if len(re.findall(w, dis, re.I)) > len(re.findall(w, " ".join(dis_sk), re.I))]
        if not ok or added:
            log("WARN", f"퇴원 섹션 검증 실패(문단 {len(dl)}/{len(dis_grp)}, 문장 {len(ds)}/{n_dis}, 추가된 시간 표현 {added}, "
                        "응급번호·인칭·완곡어 확인) → 스켈레톤 사용")
            dl = fallback["discharge"]
        hosp = str(d.get("hospital", "")).strip()
        miss = [k for _, k in _hosp_keys(plan) if not re.search(k, hosp, re.I)]
        max_w = max(80, len(" ".join(hosp_sk).split()) + 10)
        if (not hosp.startswith(hosp_sk[0][:25]) or not (22 <= len(hosp.split()) <= max_w) or _YOU.search(hosp)
                or _hedges(hosp) < _hedges(" ".join(hosp_sk)) - 1 or miss or len(_sentences(hosp)) > n_hosp + 1):
            log("WARN", f"입원 섹션 검증 실패(빠진 필수 사실 {miss}, 문장 {len(_sentences(hosp))}/{n_hosp}) → 스켈레톤 사용")
            hosp = fallback["hospital"]
        habits, n_fb = _check_habits(plan, d.get("habits"), 0)
        if n_fb:
            log("WARN", f"생활습관 {n_fb}/{len(hab_sk)}개 검증 실패 → 해당 항목만 고정 문장 사용")
        want = [(h, hk) for h, hk in zip(habits, hooks) if hk]
        hit = sum(bool(re.search(hk[1], h, re.I)) for h, hk in want)
        log("INFO", f"생활습관 환자 연결 {hit}/{len(want)}개")
        return {"hospital": hosp, "discharge": dl, "habits": habits}
    except Exception as e:
        log("WARN", f"write_prose 실패({e}) → 스켈레톤 사용")
        return fallback

def translate_prose(plan: ContentPlan, prose_en: Dict[str, object]) -> Dict[str, object]:
    """입원/퇴원 산문 + 생활습관 번역. KO 스켈레톤을 '반드시 담을 내용'으로 첨부. 실패 시 해당 부분만 KO 스켈레톤."""
    hosp_ko = [ko for _, ko in plan.hospital_facts]
    dis_ko  = [ko for _, ko in plan.discharge_facts]
    hab_ko  = [ko for _, _, ko in plan.habits]
    dis_en = prose_en["discharge"] if isinstance(prose_en["discharge"], list) else [prose_en["discharge"]]
    grp = _dis_groups(plan)
    ko_paras = _dis_paragraphs(plan, 1) if len(dis_en) == len(grp) else [" ".join(dis_ko)]
    fallback = {"hospital": " ".join(hosp_ko), "discharge": ko_paras, "habits": list(hab_ko)}
    if DRY_RUN:
        return fallback
    num_en, num_ko = plan.emergency_number
    n_dis = sum(len(re.findall(r"[.!?]", s)) for s in dis_ko)
    hab_en = prose_en.get("habits") or [en for _, en, _ in plan.habits]
    sys_p = (
        "당신은 환자 안내문 번역 전문가입니다. 초등학교 6학년이 이해할 수 있는 자연스러운 한국어로 옮기세요.\n"
        "합쇼체(~합니다, ~하세요)로 통일합니다. '그/그녀', '당신', '귀하' 금지, '환자분' 또는 생략.\n"
        "직역하지 말고 뜻을 옮기되, [반드시 담을 내용]의 모든 사실이 빠짐없이 들어가야 합니다. "
        "'~할 수 있습니다', '일부', '~한 분도 있습니다' 같은 조심스러운 표현은 그대로 살립니다.\n"
        f"퇴원 섹션은 영어 원문과 같은 수의 문단으로 나누고, [반드시 담을 내용]의 순서를 따르며, 마지막 문단은 {num_ko} 안내 문장으로 끝냅니다.\n"
        f"영어 원문의 응급번호 {num_en}은 한국어 안내문에서는 반드시 {num_ko}로 씁니다. ICU 와 다른 숫자는 그대로 둡니다.\n"
        "생활 습관은 영어 원문과 같은 개수·순서로 한 항목씩, 영어 원문의 표현(환자에 맞춘 내용 포함)을 자연스럽게 옮기되, 각 항목에 행동과 그 이유를 모두 담아 80자 안팎으로 씁니다. "
        "[확인용 핵심]은 빠진 내용이 없는지 확인하는 용도이며 그대로 베끼지 않습니다.\n"
        "설명이나 머리말 없이 JSON만 출력합니다:\n"
        '{"hospital": "<문단>", "discharge": ["<문단>", ...], "habits": ["<항목>", ...]}'
    )
    user_p = (
        "[입원 중 치료 — 영어 원문]\n" + prose_en["hospital"] +
        "\n[반드시 담을 내용]\n" + "\n".join(f"- {s}" for s in hosp_ko) +
        f"\n\n[퇴원 후 — 영어 원문 {len(dis_en)}개 문단, 문장 약 {n_dis}개]\n"
        + "\n".join(f"(문단 {j+1}) {t}" for j, t in enumerate(dis_en)) +
        "\n[반드시 담을 내용]\n" + "\n".join(f"(문단 {j+1}) {t}" for j, t in enumerate(ko_paras)) +
        f"\n\n[생활 습관 — 영어 원문 {len(hab_en)}개]\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(hab_en)) +
        "\n[확인용 핵심 — 베끼지 말 것]\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(hab_ko))
    )
    try:
        raw = call_llm([{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}])
        d = _parse_json(raw) or {}
        dl = d.get("discharge")
        dl = [str(x).strip() for x in dl] if isinstance(dl, list) else []
        dis = " ".join(dl)
        hosp = str(d.get("hospital", "")).strip()
        n_hk = sum(len(re.findall(r"[.!?]", s)) for s in hosp_ko)
        miss_ko = [k for k in _hosp_keys_ko(plan) if not re.search(k, hosp)]
        if not hosp or abs(len(re.findall(r"[.!?]", hosp)) - n_hk) > 1 or miss_ko:
            if hosp: log("WARN", f"국문 입원 섹션 검증 실패(문장 {len(re.findall(r'[.!?]', hosp))}/{n_hk}, 빠진 사실 {miss_ko}) → KO 스켈레톤 사용")
            hosp = fallback["hospital"]
        if (len(dl) != len(dis_en) or not all(dl) or num_ko not in dl[-1] or "바로" not in dl[-1]
                or len(re.findall(rf"(?<!\d){num_ko}(?!\d)", dis)) != 1 or (num_en != num_ko and num_en in dis + hosp)
                or abs(len(re.findall(r"[.!?]", dis)) - n_dis) > 1):
            log("WARN", "국문 퇴원 섹션 검증 실패 → KO 스켈레톤 사용"); dl = fallback["discharge"]
        habits, n_fb = _check_habits(plan, d.get("habits"), 1)
        if n_fb:
            log("WARN", f"국문 생활습관 {n_fb}/{len(hab_ko)}개 검증 실패 → 해당 항목만 KO 고정 문장")
        return {"hospital": hosp, "discharge": dl, "habits": habits}
    except Exception as e:
        log("WARN", f"translate_prose 실패({e}) → KO 스켈레톤 사용")
        return fallback

# ------------------------------------------------------------
# 렌더링
# ------------------------------------------------------------
def _title(key: str, lang: int, country: str) -> str:
    name = "the United States" if country == "United States" else country
    for k, en, ko in SECTION_TITLES:
        if k == key:
            return "**" + (en, ko)[lang].format(country=name) + "**"
    return ""

def render(plan: ContentPlan, prose: Dict[str, str], lang: int) -> str:
    """lang 0=EN, 1=KO. 제목·고정문·리스트는 파이썬이 조립."""
    p = plan.profile
    ctry = EN_LOCALE if lang == 0 else KO_LOCALE
    L = []
    L.append("**" + plan.cover_title[lang] + "**")
    L.append(("Patient: ________    Date: ________    Ward phone: ________",
              "환자 이름: ________    작성일: ________    병동 전화: ________")[lang])
    L.append("")
    L.append(_title("what", lang, ctry))
    L.append(" ".join(s[lang] for s in plan.what))
    L.append("")
    L.append(_title("hospital", lang, ctry))
    L.append(prose["hospital"])
    L.append("")
    L.append(_title("callbtn", lang, ctry))
    L.append(("Press the bed call button right away for any of these signs:",
              "다음 증상이 보이면 침대 호출 버튼을 바로 누르세요:")[lang])
    for sid, en, ko in plan.signs:
        L.append("☐ " + (en, ko)[lang])
    L.append(("If unsure, press the call button anyway.",
              "확실하지 않아도 일단 호출 버튼을 누르세요.")[lang])
    L.append("")
    L.append(_title("discharge", lang, ctry))
    dpar = prose["discharge"]                                   # v4: 문단 목록 (이전 캐시는 문자열 하나)
    L.extend(dpar if isinstance(dpar, list) else [dpar])
    L.append("")
    L.append(_title("habits", lang, ctry))
    hab = prose.get("habits") if isinstance(prose, dict) else None    # LLM 문장 (없거나 개수가 다르면 고정 문장)
    for i, (hid, en, ko) in enumerate(plan.habits):
        L.append("- " + (hab[i] if hab and len(hab) == len(plan.habits) else (en, ko)[lang]))
    L.append("")
    L.append(_title("support", lang, ctry))
    for item in plan.support[("en", "ko")[lang]]:
        L.append(("- " if item.startswith("**") else "") + item)
    L.append("")
    L.append("---")
    refs = "; ".join(plan.refs_ko if (lang == 1 and plan.refs_ko) else plan.refs)
    irb = IRB_NO or "____"
    for line in FOOTER_NOTICE[lang]:                            # 연구 기관 고지문 (콘텐츠 팩)
        L.append(line.format(refs=refs, irb=irb))
    return "\n".join(L) + "\n"

# ------------------------------------------------------------
# 가독성 (영문). 본문 = 지원·각주·기입란 제외.
# ------------------------------------------------------------
def count_words(text: str, include_support: bool = True) -> int:
    body = text.split("\n---")[0]
    if not include_support:
        body = body.split("**Support and Resources")[0]
    body = re.sub(r"\*\*[^*\n]+\*\*", "", body)
    body = re.sub(r"Patient:.*|_{3,}", "", body)
    return len(re.findall(r"\b\w+\b", body))

def fkgl_narrative(text_en: str) -> Optional[float]:
    try:
        import textstat
    except ImportError:
        return None
    body = text_en.split("**Support and Resources")[0]
    body = re.sub(r"\*\*[^*\n]+\*\*", "", body)
    body = re.sub(r"^\s*[☐\-]\s*", "", body, flags=re.M)
    body = re.sub(r"Patient:.*|_{3,}", "", body)
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    lines = [l if l[-1] in ".?!:" else l + "." for l in lines]
    return round(textstat.flesch_kincaid_grade(" ".join(lines)), 1)

# ------------------------------------------------------------
# 파이프라인
# ------------------------------------------------------------
def generate(htype, hloc, hvol, sex=None, age=None, nationality=None) -> Tuple[str, Optional[str], "ContentPlan"]:
    p = build_profile(htype, hloc, hvol, sex, age, nationality)
    plan = build_plan(p)

    log("INFO", "LLM 1/3: 입원·퇴원 산문 작성")
    prose = write_prose(plan)
    en = render(plan, prose, 0)

    g = fkgl_narrative(en)
    if g is not None:
        log("INFO", f"본문 FKGL = {g} (목표 ≤ {TARGET_FKGL})")
        if g > TARGET_FKGL + 0.5 and not DRY_RUN:
            log("INFO", "LLM 2/3: 가독성 재작성 1회")
            prose2 = write_prose(plan, simpler=True)
            en2 = render(plan, prose2, 0); g2 = fkgl_narrative(en2)
            log("INFO", f"재작성 후 FKGL = {g2}")
            if g2 is not None and g2 < g: prose, en = prose2, en2
    wc, wc_body = count_words(en), count_words(en, include_support=False)
    log("INFO", f"단어 수: 전체 {wc} / 지원 제도 제외 {wc_body} (한도 {MAX_WORDS})")
    if wc > MAX_WORDS:
        log("WARN", f"단어 수 초과 {wc} > {MAX_WORDS}")

    ko = None
    if True:                                   # v3: 국문은 항상 생성 (한국 기준: 119, 한국 제도)
        log("INFO", "LLM 3/3: 국문 번역 (산문 2개 섹션과 생활습관)")
        prose_ko = translate_prose(plan, prose)
        ko = render(plan, prose_ko, 1)

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "_".join(p.types) or "NONE"
    with open(os.path.join(OUT_DIR, f"explainer_{tag}_EN_{ts}.md"), "w", encoding="utf-8") as f: f.write(en)
    if ko:
        with open(os.path.join(OUT_DIR, f"explainer_{tag}_KO_{ts}.md"), "w", encoding="utf-8") as f: f.write(ko)
    with open(os.path.join(OUT_DIR, f"explainer_{tag}_plan_{ts}.json"), "w", encoding="utf-8") as f:
        json.dump(plan_to_dict(plan, prose, g, wc, wc_body), f, ensure_ascii=False, indent=2)
    log("DONE", f"saved to {OUT_DIR}")
    return en, ko, plan

def plan_to_dict(plan: ContentPlan, prose: Dict[str, str], fkgl, wc, wc_body) -> dict:
    d = asdict(plan.profile)
    d.update({
        "cover_title": plan.cover_title[0],
        "what": [s[0] for s in plan.what],
        "hospital_facts": [s[0] for s in plan.hospital_facts],
        "signs": [s[0] for s in plan.signs],
        "discharge_facts": [s[0] for s in plan.discharge_facts],
        "habits": [s[0] for s in plan.habits],
        "support": {k: [s[:40] for s in v] for k, v in plan.support.items()},
        "trimmed_for_budget": plan.trimmed,
        "refs": plan.refs, "emergency_number": plan.emergency_number,
        "prose_en": prose, "fkgl_narrative": fkgl, "word_count": wc, "word_count_no_support": wc_body,
        "llm": {"model": MODEL, "temperature": TEMPERATURE, "seed": SEED, "dry_run": DRY_RUN, "risk_mode": RISK_MODE},
    })
    return d
