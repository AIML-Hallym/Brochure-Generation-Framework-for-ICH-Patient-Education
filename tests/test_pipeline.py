# -*- coding: utf-8 -*-
"""Smoke tests without an LLM: plan selection, Markdown sections, validator fallback.  Run: python -m pytest tests"""
import os
import sys

os.environ["ICH_DRY_RUN"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ich_brochure import engine as g  # noqa: E402

CASES = [("IPH", "left basal ganglia", "18 mL", "M", 67), ("SAH", "cistern", "not measured", "F", 52),
         ("traumatic SDH", "right frontal convexity", "22 mL", "F", 74), ("traumatic EDH", "left temporal", "12 mL", "M", 9)]


def _plan(htype, loc, vol, sex, age):
    return g.build_plan(g.build_profile(htype, loc, vol, sex, age, "Korea", (age, age)))


def test_plan_is_complete():
    for case in CASES:
        plan = _plan(*case)
        assert plan.hospital_facts and plan.discharge_facts and plan.habits and plan.signs
        assert len(plan.signs) == (7 if plan.profile.category == g.CAT_TBI else 6)
        assert plan.discharge_groups[-1] == 2                       # the emergency sentence is always last
        assert any(n in plan.discharge_facts[-1][0] for n in ("911", "119"))


def test_markdown_sections_en_ko():
    plan = _plan(*CASES[0])
    prose = g.write_prose(plan)                                     # dry run: fixed sentences
    en, ko = g.render(plan, prose, 0), g.render(plan, g.translate_prose(plan, prose), 1)
    for key, t_en, t_ko in g.SECTION_TITLES:
        assert t_en.split("{")[0] in en and t_ko in ko
    assert "119" in ko


def test_habit_validator_falls_back():
    plan = _plan(*CASES[0])
    out, n_fb = g._check_habits(plan, ["too short"] * len(plan.habits), 0)
    assert n_fb == len(plan.habits)
    assert out == [en for _, en, _ in plan.habits]
