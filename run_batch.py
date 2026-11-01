# -*- coding: utf-8 -*-
"""
Batch generation: one brochure (English + Korean) per row of an input CSV -> cache JSON (input of render_brochures.py).

  python run_batch.py --inputs examples/demo_inputs.csv --out outputs/demo --dry   # no LLM: fixed sentences only
  python run_batch.py --inputs examples/demo_inputs.csv --out outputs/demo         # LLM wording (needs ICH_API_KEY)

Input columns
  case_id    integer case number (printed on the cover as "Case 001")
  age        years (decimals allowed), sex: M | F
  subtypes   IPH, IVH, SAH, EDH, SDH (comma- or plus-separated)
  location   free text, e.g. "left basal ganglia", "right frontal convexity", "cistern"
  volume_ml  total volume in mL (empty = not measured)
  traumatic  optional, 1 = bleed after a head injury (TBI path)
  dataset    optional label printed on the cover next to the case number
Output
  <out>/cache/{case_id:03d}.json   plan, prose, rendered EN/KO markdown, readability, validator log
  <out>/metrics.csv                FKGL and word count per case, number of fallbacks
A case is skipped when its cache was made from the same input row and the same settings (content pack, generator,
English locale, model, temperature, seed, dry run, risk mode), so an interrupted run can be resumed; any change
regenerates the case.
"""
import os
import sys
import csv
import json
import time
import argparse
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
GENERATOR = "v4-public"            # the renderer uses the v4 layout for any generator name starting with "v4"

_tl = threading.local()

def _log(level, msg):
    buf = getattr(_tl, "buf", None)
    if buf is not None: buf.append(f"[{level}] {msg}")


def age_group_label(age):
    if age < 10: return "under10"
    if age >= 80: return "80plus"
    lo = int(age // 10) * 10
    return f"{lo}-{lo + 9}"


def load_inputs(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            n = int(r["case_id"]); age = float(r["age"])
            sex = r["sex"].strip().upper()[:1]
            if sex not in ("M", "F"): raise ValueError(f"case {n}: sex '{r['sex']}'")
            subtypes = ",".join(t.strip().upper() for t in r["subtypes"].replace("+", ",").split(",") if t.strip())
            if not subtypes: raise ValueError(f"case {n}: no hemorrhage subtype")
            vol = (r.get("volume_ml") or "").strip()
            rows.append(dict(no=n, patient_id=f"{n:03d}", dataset=(r.get("dataset") or "").strip() or "demo",
                             subtypes=subtypes, loc=r["location"].strip(), vol=float(vol) if vol else None,
                             traumatic=(r.get("traumatic") or "").strip() in ("1", "yes", "true"), sex=sex,
                             age=int(age), age_group=age_group_label(age)))
    return sorted(rows, key=lambda x: x["no"])


def signature(g, row):
    """Everything that changes the output of a case: the input row and the generation settings."""
    return dict(row=row, generator=GENERATOR, content_pack=g.CONTENT_NAME, en_locale=g.EN_LOCALE,
                llm=dict(model=g.MODEL, temperature=g.TEMPERATURE, seed=g.SEED, dry_run=g.DRY_RUN, risk_mode=g.RISK_MODE))


def run_one(g, row):
    _tl.buf = []
    t0 = time.time()
    age = row["age"]
    htype = ("traumatic " if row["traumatic"] else "") + row["subtypes"].replace(",", ", ")
    vol = f"{row['vol']} mL" if row["vol"] is not None else "not measured"
    p = g.build_profile(htype, row["loc"], vol, row["sex"], age, "Korea", (age, age))
    plan = g.build_plan(p)
    prose = g.write_prose(plan)
    en = g.render(plan, prose, 0); fk = g.fkgl_narrative(en)
    if fk is not None and fk > g.TARGET_FKGL + 0.5 and not g.DRY_RUN:          # one simpler rewrite
        prose2 = g.write_prose(plan, simpler=True); en2 = g.render(plan, prose2, 0); fk2 = g.fkgl_narrative(en2)
        _log("INFO", f"readability rewrite: {fk} -> {fk2}")
        if fk2 is not None and fk2 < fk: prose, en, fk = prose2, en2, fk2
    prose_ko = g.translate_prose(plan, prose)
    ko = g.render(plan, prose_ko, 1)
    logs = list(_tl.buf)
    return dict(no=row["no"], patient_id=row["patient_id"], dataset=row["dataset"], subtypes=row["subtypes"],
                htype_input=htype, location_raw=row["loc"], volume_ml=row["vol"], sex=row["sex"], age=age,
                age_group=row["age_group"], age_used=age, age_band=p.age_band,
                category=p.category, locs=p.locs, loc_fallback=p.loc_fallback, risk=p.risk, risk_reason=p.risk_reason,
                hospital_facts=[e for e, _ in plan.hospital_facts], discharge_facts=[e for e, _ in plan.discharge_facts],
                signs=[s[0] for s in plan.signs], habits=[h[0] for h in plan.habits], support=plan.support,
                emergency_number=list(plan.emergency_number), trimmed=plan.trimmed,
                prose_en=prose, prose_ko=prose_ko, en_md=en, ko_md=ko, fkgl_narrative=fk, word_count=g.count_words(en),
                fallback_used=sum("WARN" in l and "→" in l for l in logs), logs=logs,
                generator=GENERATOR, content_pack=g.CONTENT_NAME, en_locale=g.EN_LOCALE, signature=signature(g, row),
                llm=dict(model=g.MODEL, temperature=g.TEMPERATURE, seed=g.SEED, dry_run=g.DRY_RUN, risk_mode=g.RISK_MODE),
                seconds=round(time.time() - t0, 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "outputs", "run"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--dry", action="store_true", help="no LLM: use the fixed sentences of the content pack")
    a = ap.parse_args()
    if a.dry: os.environ["ICH_DRY_RUN"] = "1"
    from ich_brochure import engine as g                       # reads the environment at import
    g.log = _log
    cache = os.path.join(a.out, "cache"); os.makedirs(cache, exist_ok=True)
    rows = load_inputs(a.inputs)
    if a.only: rows = [r for r in rows if r["no"] in {int(x) for x in a.only.split(",")}]

    def fresh(r):
        try: o = json.load(open(os.path.join(cache, f"{r['no']:03d}.json"), encoding="utf-8"))
        except (OSError, ValueError): return False
        return o.get("signature") == json.loads(json.dumps(signature(g, r)))     # same row and settings
    todo = [r for r in rows if not fresh(r)]
    print(f"inputs {len(rows)}, cached {len(rows) - len(todo)}, to generate {len(todo)} "
          f"(content pack: {g.CONTENT_NAME}, dry run: {g.DRY_RUN})", flush=True)
    if todo and not g.DRY_RUN: g._get_client()
    t0, done, errs = time.time(), 0, 0

    def job(r):
        o = run_one(g, r)
        with open(os.path.join(cache, f"{r['no']:03d}.json"), "w", encoding="utf-8") as fh:
            json.dump(o, fh, ensure_ascii=False, indent=1)
        return o

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(job, r): r for r in todo}
        for f in as_completed(futs):
            r = futs[f]; done += 1
            try:
                o = f.result()
                print(f"[{done}/{len(todo)}] case {r['no']:03d} {o['category']:<4} risk {o['risk']:<6} "
                      f"FKGL {o['fkgl_narrative']} words {o['word_count']}  {round(time.time() - t0)}s", flush=True)
            except Exception as e:
                errs += 1; print(f"[{done}/{len(todo)}] case {r['no']:03d} ERROR {e}", flush=True); traceback.print_exc()

    out_rows = []
    for f in sorted(x for x in os.listdir(cache) if x.endswith(".json")):
        o = json.load(open(os.path.join(cache, f), encoding="utf-8"))
        out_rows.append(dict(case=o["no"], subtypes=o["subtypes"], category=o["category"], risk=o["risk"],
                             locs="|".join(o["locs"]), age_band=o["age_band"], fkgl=o["fkgl_narrative"],
                             words=o["word_count"], fallbacks=o["fallback_used"], dry_run=o["llm"]["dry_run"]))
    if out_rows:
        with open(os.path.join(a.out, "metrics.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys())); w.writeheader(); w.writerows(out_rows)
    print(f"done: {done - errs} generated, {errs} errors -> {cache}", flush=True)


if __name__ == "__main__":
    main()
