# -*- coding: utf-8 -*-
"""Constants shared by the engine and content packs."""
import os

CAT_ICH, CAT_SAH, CAT_TBI = "ICH", "SAH", "TBI"     # spontaneous ICH / subarachnoid / traumatic

EN_LOCALE = os.environ.get("ICH_EN_LOCALE", "United States")   # English edition: emergency number and support programs
KO_LOCALE = "South Korea"                                      # Korean edition

# Age bands used to filter habits (explicit sets: a fallback never leaves the band)
ADULT = {"young", "middle", "older", "unknown"}
WORK = {"young", "middle"}
MO = {"middle", "older"}
OLD = {"older"}
KIDS = {"child", "teen"}
INF = {"infant"}
ANY = ADULT | KIDS | INF

LOBAR = {"frontal", "parietal", "temporal", "insula", "occipital", "lobar_generic"}


def _fem(p, lo, hi):
    """Female patient aged lo..hi (used by pregnancy-related items)."""
    return p.sex == "F" and p.age is not None and lo <= p.age <= hi
