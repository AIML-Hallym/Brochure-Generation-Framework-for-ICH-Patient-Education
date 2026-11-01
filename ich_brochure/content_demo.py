# -*- coding: utf-8 -*-
"""
DEMO content pack — NOT FOR CLINICAL USE.

Same structure as the clinician-reviewed content pack used in the study, with short illustrative sentences, so the
whole pipeline (plan -> wording -> validation -> layout) runs end to end. The reviewed pack (sentence tables,
age/location/laterality branches and content-specific selection rules) is not part of this repository.

Every sentence is an (English, Korean) pair. Rules of the format are in docs/content_pack.md:
  - each fact is one complete sentence that the LLM may reword but must keep;
  - hedges ("may", "can", "some") are kept by the validators;
  - the keywords the validators look for (ICU, awake, tube, surgery, ...) must stay in the matching sentences.
"""
from ich_brochure.common import CAT_ICH, CAT_SAH, CAT_TBI, ADULT, WORK, KIDS, INF, EN_LOCALE   # absolute: copy-safe

CONTENT_NAME = "demo"

COVER_TITLE = {
    CAT_ICH: ("DEMO Brain Bleeding Guide (not for clinical use)", "데모 뇌출혈 안내문 (진료용 아님)"),
    CAT_SAH: ("DEMO Guide to Bleeding Around the Brain (not for clinical use)", "데모 지주막하출혈 안내문 (진료용 아님)"),
    CAT_TBI: ("DEMO Guide to Bleeding After a Head Injury (not for clinical use)", "데모 머리 외상 출혈 안내문 (진료용 아님)"),
}

GUIDELINES = {   # footnote sources: (English edition, Korean edition). Replace with the guidelines your pack follows.
    CAT_ICH: (["Demo source list A"], ["데모 근거 목록 A"]),
    CAT_SAH: (["Demo source list B"], ["데모 근거 목록 B"]),
    CAT_TBI: (["Demo source list C"], ["데모 근거 목록 C"]),
}

FOOTER_NOTICE = {   # {refs}: footnote sources, {irb}: IRB number (the renderer can fill "IRB No. ____")
    0: ["This demo handout was assembled from illustrative sentences ({refs}).", "",
        "**Important:** Demo output of an AI-assisted brochure framework (IRB No. {irb}). It is not medical advice."],
    1: ["이 데모 안내문은 예시 문장({refs})으로 만들었습니다.", "",
        "**중요:** AI 기반 안내문 프레임워크의 데모 출력입니다(IRB No. {irb}). 의료 조언이 아닙니다."],
}

# ------------------------------------------------------------ section 1: what is the bleed
GENERAL_WHAT = [
    ("A brain bleed means blood has escaped inside the head.", "뇌출혈은 머릿속에서 피가 새어 나온 것입니다."),
    ("The blood can press on nearby brain tissue.", "고인 피는 주변 뇌를 누를 수 있습니다."),
    ("What happens next depends on the size and place of the bleed.", "앞으로의 경과는 출혈의 크기와 위치에 따라 다릅니다."),
]
# Subtype sentences: not shown on the page; they give the habit-writing prompt a short patient summary.
FIRST_SENTENCE = {
    CAT_ICH: ("Blood has leaked into the brain.", "뇌 안으로 피가 새어 나왔습니다."),
    CAT_SAH: ("Blood has leaked into the space around the brain.", "뇌 주변 공간으로 피가 새어 나왔습니다."),
    "IVH_ONLY": ("Blood has leaked into the fluid spaces inside the brain.", "뇌 속 물길(뇌실)로 피가 새어 나왔습니다."),
}
TBI_SENTENCE = {
    "EDH": [("Blood has collected just under the skull.", "두개골 바로 아래에 피가 고였습니다.")],
    "SDH": [("Blood has collected under the brain's covering.", "뇌를 싸는 막 아래에 피가 고였습니다.")],
    "EDH+SDH": [("Blood has collected above and below the brain's covering.", "뇌를 싸는 막의 위와 아래에 피가 고였습니다.")],
    "OTHER": [("Blood has collected inside the head after an injury.", "다친 뒤 머릿속에 피가 고였습니다.")],
}
FIRST_SENTENCE_EXTRA = {
    "also_in_brain": ("Some blood is in the brain itself.", "뇌 안에도 피가 조금 있습니다."),
    "also_fluid": ("Some blood is in the fluid spaces.", "뇌실에도 피가 조금 있습니다."),
    "also_around": ("Some blood is around the brain.", "뇌 주변에도 피가 조금 있습니다."),
}

# ------------------------------------------------------------ section 2: hospital stay
LEVEL_OF_CARE = {   # validator keyword: "intensive care|ICU" / "중환자실"
    "high": ("Treatment may happen in the intensive care unit (ICU).", "중환자실(ICU)에서 치료할 수 있습니다."),
    "medium": ("Treatment starts on a closely watched ward, and some people move to the ICU.",
               "가까이 지켜보는 병동에서 치료를 시작하며, 중환자실(ICU)로 옮기는 분도 있습니다."),
    "low": ("The team chooses the ward, and some people need the ICU.", "병동은 의료진이 정하며, 중환자실(ICU)이 필요한 분도 있습니다."),
}
NEURO_CHECK = {   # validator keyword: "awake" / "의식"
    "default": ("Nurses check often how awake the patient is and how the arms and legs move.",
                "간호사가 의식과 팔다리 움직임을 자주 확인합니다."),
    "infant": ("Nurses check often how awake the baby is and how the baby feeds.",
               "간호사가 아기의 의식과 먹는 모습을 자주 확인합니다."),
    CAT_SAH: ("Nurses check often how awake the patient is and how the headache feels.",
              "간호사가 의식과 두통을 자주 확인합니다."),
}
HOSPITAL_FACTS = {   # (EN, KO, keep): keep=True survives the sentence budget. ICH keep item keyword: "blood pressure" / "혈압"
    CAT_ICH: [("Keeping blood pressure in range can help stop more bleeding.", "혈압을 알맞게 유지하면 출혈이 더 생기는 것을 막는 데 도움이 됩니다.", True)],
    CAT_SAH: [("The team also watches for fluid building up.", "의료진은 머릿속에 물이 차는지도 살핍니다.", False)],
    CAT_TBI: [],
}
HOSPITAL_PROCEDURE = {k: ("Some people need surgery to relieve pressure.", "압력을 낮추는 수술이 필요한 분도 있습니다.")
                      for k in ("high", "medium", "low")}   # validator keyword: "surgery" / "수술"
TYPE_EXTRAS_HOSPITAL = {   # validator keywords: "weak spot", "narrow", "tube", "cause"
    "SAH": [("Scans may look for a weak spot in a blood vessel.", "검사로 혈관의 약한 부분을 찾을 수 있습니다."),
            ("Blood vessels can narrow for a while, so the team watches closely.", "혈관이 한동안 좁아질 수 있어 의료진이 지켜봅니다.")],
    "IVH": [("A thin tube may drain extra fluid.", "가는 관으로 남는 물을 뺄 수 있습니다.")],
    "IVH_ONLY": [("Tests may look for the cause of the bleed.", "출혈 원인을 찾는 검사를 할 수 있습니다.")],
}

# ------------------------------------------------------------ section 4: after leaving the hospital
RECOVERY_LINE = ("Recovery is different for everyone.", "회복 속도는 사람마다 다릅니다.")
SOME_LAST_LINE = ("Some problems may last.", "일부 문제는 오래갈 수 있습니다.")
# Location groups (see LOCATION_MAP in engine.py): "fn" = functions the nurses watch, "remain" = a problem that may
# remain after discharge (the plan uses the first two locations), "extra" = optional extra discharge sentence.
_DEMO_LOC = {
    "brainstem": ("swallowing, breathing", "삼킴, 호흡", "Some people need help with swallowing.", "삼키기에 도움이 필요한 분도 있습니다."),
    "ventricle": ("alertness", "의식", "Fluid can build up and cause headaches.", "물이 차서 두통이 생길 수 있습니다."),
    "basal_ganglia": ("strength", "근력", "Some people have weakness on one side.", "몸 한쪽에 힘이 약한 분도 있습니다."),
    "cerebellum": ("balance", "균형", "Some people feel unsteady when walking.", "걸을 때 불안정한 분도 있습니다."),
    "frontal": ("mood, planning", "기분, 계획", "Some people notice mood changes.", "기분이 달라지는 분도 있습니다."),
    "temporal": ("memory", "기억력", "Some people forget things more easily.", "잘 잊어버리는 분도 있습니다."),
    "parietal": ("feeling", "감각", "Some people feel less on one side.", "한쪽 감각이 둔한 분도 있습니다."),
    "occipital": ("vision", "시력", "Some people see less on one side.", "한쪽이 잘 안 보이는 분도 있습니다."),
    "insula": ("speech", "말하기", "Some people find talking harder.", "말하기가 어려운 분도 있습니다."),
    "deep_white": ("strength", "근력", "Some people feel weak on one side.", "한쪽 힘이 약한 분도 있습니다."),
    "cisternal": ("alertness", "의식", "Some people feel tired at first.", "처음에는 쉽게 피곤한 분도 있습니다."),
    "convexity": ("alertness", "의식", "Some people have headaches at first.", "처음에는 두통이 있는 분도 있습니다."),
    "midline": ("leg strength", "다리 힘", "Some people have weak legs.", "다리 힘이 약한 분도 있습니다."),
    "lobar_generic": ("movement, speech", "움직임, 말하기", "Some people feel tired at first.", "처음에는 쉽게 피곤한 분도 있습니다."),
}
LOC_SPEC = {k: {"fn": (fe, fk), "remain": (re_, rk)} for k, (fe, fk, re_, rk) in _DEMO_LOC.items()}
LOC_SPEC["occipital"]["extra"] = ("Ask the doctor before driving.", "운전하기 전에 의사에게 물어보세요.")
REHAB_LINE = {"loc": ("Rehab may help.", "재활이 도움이 될 수 있습니다."),
              "general": ("Rehab may help with daily life.", "재활은 일상생활에 도움이 될 수 있습니다.")}
TYPE_EXTRAS_DISCHARGE = {"SAH": [("Keep every planned check-up and scan.", "예정된 진료와 검사를 빠짐없이 받으세요.")]}
FOLLOWUP_LINE = ("Keep every planned check-up.", "예정된 진료를 빠짐없이 받으세요.")
DRIVING_LINE = ("Ask the doctor before driving again.", "다시 운전하기 전에 의사에게 물어보세요.")
EMERGENCY_LEAD = {
    "SDH": ("Problems can also start later.", "문제가 나중에 생길 수도 있습니다."),
    "ventricle": ("Fluid can build up and raise pressure.", "물이 차서 압력이 올라갈 수 있습니다."),
    "default": ("A brain bleed can change quickly.", "뇌출혈은 빨리 나빠질 수 있습니다."),
}
EMERGENCY_CALL = {   # {num}: emergency number of the edition. The last sentence must keep the number and "right away" / "바로".
    "default": ("Call {num} right away for any warning sign.", "위험 증상이 있으면 바로 {num}에 전화하세요."),
    "extra": ("Call {num} right away for any warning sign or a new {sx}.", "위험 증상이 있거나 {sx} 새로 생기면 바로 {num}에 전화하세요."),
}
EMERGENCY_SX = {"SDH": (["headache"], ["두통"]), "ventricle": (["headache"], ["두통"])}

# ------------------------------------------------------------ section 3: warning signs (nurse call button)
# (id, severity 1-3, condition(profile), EN, KO). Of the first four signs, ids listed in SIGN_FOLDER (render_brochures.py)
# get a picture; others (here: fontanelle) are shown as text only.
SIGN_POOL = [
    ("cannot_wake", 1, lambda p: True, "Very hard to wake up", "깨우기가 매우 어렵습니다."),
    ("confusion", 1, lambda p: p.age_band not in ("infant", "child"), "New confusion", "새로 혼란스러워합니다."),
    ("seizure", 1, lambda p: True, "A new seizure", "새로 경련을 합니다."),
    ("fontanelle", 1, lambda p: p.age_band == "infant", "A swollen soft spot on the head", "머리 숨구멍이 부풀어 오릅니다."),
    ("headache", 2, lambda p: p.age_band != "infant", "A headache that keeps getting worse", "두통이 계속 심해집니다."),
    ("vomiting", 2, lambda p: True, "Vomiting again and again", "구토를 반복합니다."),
    ("weakness", 2, lambda p: True, "New weakness on one side", "몸 한쪽에 새로 힘이 빠집니다."),
    ("csf_leak", 2, lambda p: p.category == CAT_TBI, "Clear fluid from the nose or ears", "코나 귀에서 맑은 물이 나옵니다."),
    ("speech", 3, lambda p: p.age_band != "infant", "New trouble talking", "말하기가 새로 어려워집니다."),
    ("vision", 3, lambda p: True, "Sudden change in vision", "갑자기 잘 안 보입니다."),
]

# ------------------------------------------------------------ section 5: healthy habits
# (id, priority, age bands, condition(profile), EN, KO)
HABIT_POOL = [
    ("meds_daily", 1, ADULT, lambda p: True, "Take blood pressure medicine as prescribed, because high blood pressure can cause bleeding.",
     "혈압약은 처방대로 드세요. 혈압이 높으면 출혈이 생길 수 있습니다."),
    ("meds_ask", 1, ADULT, lambda p: True, "Ask the doctor before any new medicine, because some medicines affect bleeding.",
     "새 약은 먹기 전에 의사와 상의하세요. 일부 약은 출혈에 영향을 줍니다."),
    ("smoke", 2, ADULT, lambda p: True, "Stop smoking, because smoking damages blood vessels.", "담배를 끊으세요. 담배는 혈관을 상하게 합니다."),
    ("alcohol", 2, ADULT, lambda p: True, "Avoid alcohol until the doctor says it is fine, because it can hide warning signs.",
     "의사가 괜찮다고 할 때까지 술을 피하세요. 술은 위험 증상을 가릴 수 있습니다."),
    ("gentle_walk", 3, ADULT, lambda p: True, "Take short, easy walks and rest when tired, so the body can recover.",
     "짧고 편하게 걷고 피곤하면 쉬세요. 몸이 회복하는 데 도움이 됩니다."),
    ("pace_tbi", 3, ADULT, lambda p: True, "Add activity a little at a time and rest when tired, so the brain can heal.",
     "활동을 조금씩 늘리고 피곤하면 쉬세요. 뇌가 회복하는 데 도움이 됩니다."),
    ("home_falls", 4, ADULT, lambda p: True, "Clear clutter from walkways, because a fall can injure the head.",
     "다니는 길의 물건을 치우세요. 넘어지면 머리를 다칠 수 있습니다."),
    ("helmet", 4, WORK, lambda p: True, "Wear a helmet when riding a bike, because a new blow can cause bleeding.",
     "자전거를 탈 때는 헬멧을 쓰세요. 다시 부딪히면 출혈이 생길 수 있습니다."),
    ("child_helmet", 1, KIDS, lambda p: True, "Wear a helmet for bikes and scooters, to protect the head.",
     "자전거와 킥보드를 탈 때는 헬멧을 쓰세요. 머리를 보호합니다."),
    ("child_sports", 1, KIDS, lambda p: True, "Skip rough games until the doctor says it is fine, so the head can heal.",
     "의사가 괜찮다고 할 때까지 거친 놀이는 쉬세요. 머리가 나을 시간이 필요합니다."),
    ("child_rest", 2, KIDS, lambda p: True, "Get plenty of rest and limit screens for a while, so the brain can heal.",
     "한동안 푹 쉬고 화면 보는 시간을 줄이세요. 뇌가 회복하는 데 도움이 됩니다."),
    ("child_sleep", 3, KIDS, lambda p: True, "Keep a regular bedtime, because sleep helps healing.", "정해진 시간에 자세요. 잠은 회복을 돕습니다."),
    ("infant_carseat", 1, INF, lambda p: True, "Use a car seat on every trip, to protect the baby's head.",
     "차를 탈 때는 늘 카시트를 쓰세요. 아기 머리를 보호합니다."),
    ("infant_watch", 2, INF, lambda p: True, "Keep a simple diary of feeding and sleep, so changes are easy to notice.",
     "먹는 양과 잠을 간단히 적어 두세요. 변화를 알아채기 쉽습니다."),
    ("infant_sleep", 3, INF, lambda p: True, "Put the baby to sleep on the back in a bare crib.", "아기는 아무것도 없는 아기침대에 등을 대고 재우세요."),
    ("infant_visits", 4, INF, lambda p: True, "Keep every check-up, so the doctor can follow growth.", "정기 검진을 빠짐없이 받으세요. 성장을 확인합니다."),
]
HABIT_DOMAINS_EN = ("Medicines", "Food, drink, and smoking", "Exercise and activity", "Safety")   # labels for the adult prompt
HABIT_REQ = {   # keywords an LLM-written item must keep; otherwise the fixed sentence above is used
    "meds_daily": [r"blood pressure", r"medicine"], "meds_ask": [r"medicine", r"ask|doctor"], "smoke": [r"smok"],
    "alcohol": [r"alcohol|drink"], "gentle_walk": [r"walk"], "pace_tbi": [r"rest"], "home_falls": [r"fall|clutter|walkway"],
    "helmet": [r"helmet"],
}
HABIT_MAXW = {}   # per-topic word limits (default 24)
HABIT_BRIEF = {   # topic notes for the LLM: (what to do, why, words to keep). Topics without a note use the fixed sentence.
    "meds_daily": ("take blood pressure medicine as prescribed", "high blood pressure can cause bleeding", "as prescribed"),
    "meds_ask": ("ask the doctor before any new medicine", "some medicines affect bleeding", ""),
    "smoke": ("stop smoking", "smoking damages blood vessels", ""),
    "alcohol": ("avoid alcohol until the doctor says it is fine", "alcohol can hide warning signs", ""),
    "gentle_walk": ("take short, easy walks and rest when tired", "this helps the body recover", ""),
    "pace_tbi": ("add activity a little at a time and rest when tired", "healing takes time", ""),
    "home_falls": ("clear clutter from walkways at home", "a fall can injure the head", ""),
    "helmet": ("wear a helmet when riding a bike", "a new blow to the head can cause bleeding", ""),
}
SKILL_HOOK = {}      # location -> (phrase, regex): links a location-driven habit topic to the patient (unused in the demo)
LOC_TOPICS = set()   # habit topics that receive that link


def _adult_habit_ids(p):
    """Adults: one topic in each of four domains (medicine / food-drink-smoking / activity / safety).
    The study's pack chooses each topic from bleed type, location and age; the demo uses a minimal rule."""
    tbi = p.category == CAT_TBI
    return ["meds_ask" if tbi else "meds_daily",
            "alcohol" if tbi else "smoke",
            "pace_tbi" if tbi else "gentle_walk",
            "helmet" if (tbi and p.age_band in WORK) else "home_falls"]


# ------------------------------------------------------------ section 6: support (items starting with ** are bullets)
KR_SUPPORT_KO = {
    "social": "**병원 사회복지팀:** 비용과 퇴원 후 돌봄 계획을 상의할 수 있습니다.",
    "more": "더 많은 도움이 필요하면 의료진에게 문의하세요.",
}
US_SUPPORT_EN = {
    "social": "**Hospital social worker:** can help with costs and plans for care at home.",
    "more": "For more help: ask the care team about local services.",
}
GENERIC_SUPPORT_EN = ["Ask the hospital social work team about local programs.", "For more help: ask the care team."]


def select_support(p):
    """{'en': [...], 'ko': [...]}. The study's pack selects national programs by age, category and locale."""
    en = [US_SUPPORT_EN["social"], US_SUPPORT_EN["more"]] if EN_LOCALE == "United States" else list(GENERIC_SUPPORT_EN)
    return {"en": en, "ko": [KR_SUPPORT_KO["social"], KR_SUPPORT_KO["more"]]}
