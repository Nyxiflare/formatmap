#!/usr/bin/env python3
"""
formatmap.py - FormatMap's deterministic parts: scoring, the effort x premium grid, the HTML heat map,
the premium-upgrade checklists and a capacity-sized 2-week test plan.

The judgement (which formats a niche is full of, what each test piece says) is Claude's. This script
turns that judgement into exact, repeatable numbers. All ratings and thresholds live in
references/catalogue.json (or --catalogue FILE), never in this code.

Commands
  catalogue [--length short|long] [--layouts] [--json]   list formats (or layouts) with their ratings
  show ID [ID ...]                                       definition, examples and premium upgrades
  template --niche TEXT [--length short|long] [--faceless] [--hours N] [--max-effort N]
           [--current ID ...] [--out scan.json]          a scan file to fill in
  check SCAN.json                                        validate a scan file
  build SCAN.json [--out-dir DIR] [--top N]              score, map, recommend, plan; writes
                                                         DIR/formatmap.html and DIR/formatmap.md

Standard library only. No network requests: the HTML is fully self-contained.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import html
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = HERE.parent / "references" / "catalogue.json"
LENGTHS = ("short", "long")
FACE = ("required", "optional", "none")
BASES = ("observed", "user", "estimated")
STATUSES = ("open", "stretch", "upgrade", "crowded", "neutral", "unknown", "blocked", "n/a")
STATUS_LABEL = {
    "open": "Open",
    "stretch": "Open, over capacity",
    "upgrade": "Easy but crowded: upgrade it",
    "crowded": "Crowded",
    "neutral": "Neutral",
    "unknown": "Unknown saturation",
    "blocked": "Needs a face",
    "n/a": "Not this length",
}
SCORING_DEFAULTS = {
    "weights": {"premium": 0.45, "openness": 0.40, "ease": 0.15},
    "open": {"min_premium": 6, "max_saturation": 4},
    "crowded": {"min_saturation": 7},
    "upgrade": {"max_effort": 4, "min_saturation": 6},
    "saturation_bands": [{"max_share": 1.0, "saturation": 10}],
    "test_pieces_per_format": 2,
    "test_days": 14,
    "upgrade_hours_factor": 1.5,
    "layout_hours_per_effort": 0.25,
    "fill_min_premium": 4,
}


class FormatMapError(SystemExit):
    pass


def fail(msg: str):
    raise FormatMapError("error: " + msg)


def out(s: str = "") -> None:
    sys.stdout.write(s + "\n")


def clamp(v: float, lo: float = 1, hi: float = 10) -> float:
    return max(lo, min(hi, v))


def num(v) -> str:
    """Format a number without a trailing .0"""
    if v is None:
        return "?"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


# --------------------------------------------------------------------------- catalogue

def load_json(path: Path, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        fail(f"{what} is not valid JSON ({path}): line {e.lineno}: {e.msg}")


def load_catalogue(path=None) -> dict:
    cat = load_json(Path(path) if path else DEFAULT_CATALOGUE, "catalogue")
    validate_catalogue(cat)
    scoring = copy.deepcopy(SCORING_DEFAULTS)
    for k, v in (cat.get("scoring") or {}).items():
        if isinstance(v, dict) and isinstance(scoring.get(k), dict):
            scoring[k].update(v)
        else:
            scoring[k] = v
    cat["scoring"] = scoring
    cat["_formats"] = {f["id"]: f for f in cat["formats"]}
    cat["_layouts"] = {l["id"]: l for l in cat.get("layouts", [])}
    return cat


def validate_catalogue(cat: dict) -> None:
    if not isinstance(cat.get("formats"), list) or not cat["formats"]:
        fail("catalogue has no 'formats' list")
    seen = set()
    for f in cat["formats"]:
        fid = f.get("id")
        if not fid or fid in seen:
            fail(f"catalogue format id missing or duplicated: {fid!r}")
        seen.add(fid)
        for k in ("effort", "premium"):
            if not isinstance(f.get(k), (int, float)) or not 1 <= f[k] <= 10:
                fail(f"catalogue format {fid}: {k} must be a number from 1 to 10")
        if f.get("face") not in FACE:
            fail(f"catalogue format {fid}: face must be one of {', '.join(FACE)}")
        lengths = f.get("lengths") or []
        if not lengths or any(x not in LENGTHS for x in lengths):
            fail(f"catalogue format {fid}: lengths must be a non-empty list of short/long")
        for x in lengths:
            h = (f.get("hours") or {}).get(x)
            if not isinstance(h, (int, float)) or h <= 0:
                fail(f"catalogue format {fid}: hours.{x} must be a positive number")
    lseen = set()
    for l in cat.get("layouts", []):
        lid = l.get("id")
        if not lid or lid in lseen:
            fail(f"catalogue layout id missing or duplicated: {lid!r}")
        lseen.add(lid)
        for k in ("effort_add", "premium_add"):
            if not isinstance(l.get(k), (int, float)):
                fail(f"catalogue layout {lid}: {k} must be a number")
    bands = (cat.get("scoring") or {}).get("saturation_bands")
    if bands is not None:
        last = -1.0
        for b in bands:
            if b.get("max_share", -1) < last or not 0 <= b.get("saturation", -1) <= 10:
                fail("catalogue scoring.saturation_bands must be sorted by max_share with saturation 0-10")
            last = b["max_share"]
        if not bands or bands[-1]["max_share"] < 1.0:
            fail("catalogue scoring.saturation_bands must end with max_share 1.0")


def saturation_from_share(share: float, bands: list) -> int:
    for b in bands:
        if share <= b["max_share"] + 1e-9:
            return int(b["saturation"])
    return 10


# --------------------------------------------------------------------------- scan file

def validate_scan(scan: dict, cat: dict) -> tuple[list, list]:
    """Return (errors, warnings). Errors stop a build."""
    errors, warnings = [], []
    if not isinstance(scan, dict):
        return ["scan file must be a JSON object"], []
    if not str(scan.get("niche") or "").strip():
        errors.append("'niche' is required")
    creator = scan.get("creator")
    if not isinstance(creator, dict):
        errors.append("'creator' is required (faceless, length, hours_per_week)")
        creator = {}
    length = creator.get("length", "short")
    if length not in LENGTHS:
        errors.append(f"creator.length must be short or long, not {length!r}")
    hpw = creator.get("hours_per_week")
    if not isinstance(hpw, (int, float)) or hpw <= 0:
        errors.append("creator.hours_per_week must be a positive number")
    me = creator.get("max_effort", 10)
    if not isinstance(me, (int, float)) or not 1 <= me <= 10:
        errors.append("creator.max_effort must be 1-10 (leave it out for no limit)")
    if not isinstance(creator.get("faceless", False), bool):
        errors.append("creator.faceless must be true or false")
    for cid in creator.get("current_formats", []) or []:
        if cid not in cat["_formats"]:
            errors.append(f"creator.current_formats: unknown format {cid!r}")
    for fid, ov in (scan.get("overrides") or {}).items():
        if fid not in cat["_formats"]:
            errors.append(f"overrides: unknown format {fid!r}")
            continue
        for k in ("effort", "premium"):
            if k in ov and (not isinstance(ov[k], (int, float)) or not 1 <= ov[k] <= 10):
                errors.append(f"overrides.{fid}.{k} must be 1-10")
        if "premium" in ov:
            warnings.append(f"overrides.{fid} changes premium: only do this with a reason, never to make a favourite win")
        if not str(ov.get("reason") or "").strip():
            warnings.append(f"overrides.{fid} has no 'reason'")
    sample = scan.get("sample") or {}
    size = sample.get("size")
    if size is not None and (not isinstance(size, int) or size <= 0):
        errors.append("sample.size must be a positive whole number")
        size = None
    entries = scan.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("'entries' must be a non-empty list")
        entries = []
    seen = set()
    counted = 0
    for i, e in enumerate(entries, 1):
        tag = f"entries[{i}]"
        fid, lid = e.get("format"), e.get("layout")
        if fid not in cat["_formats"]:
            errors.append(f"{tag}: unknown format {fid!r} (run 'catalogue' for ids)")
            continue
        if lid is not None and lid not in cat["_layouts"]:
            errors.append(f"{tag}: unknown layout {lid!r} (run 'catalogue --layouts')")
        key = (fid, lid)
        if key in seen:
            errors.append(f"{tag}: duplicate entry for {fid}" + (f" + {lid}" if lid else ""))
        seen.add(key)
        sat, cnt = e.get("saturation"), e.get("count")
        if sat is not None and (not isinstance(sat, (int, float)) or not 0 <= sat <= 10):
            errors.append(f"{tag} {fid}: saturation must be 0-10 or null")
        if cnt is not None:
            if not isinstance(cnt, int) or cnt < 0:
                errors.append(f"{tag} {fid}: count must be a whole number >= 0")
            elif size is None:
                errors.append(f"{tag} {fid}: has a count but sample.size is missing")
            elif cnt > size:
                errors.append(f"{tag} {fid}: count {cnt} is larger than sample.size {size}")
            else:
                counted += cnt
            if sat is not None:
                warnings.append(f"{tag} {fid}: both count and saturation given; count wins")
        basis = e.get("basis")
        if (sat is not None or cnt is not None) and basis not in BASES:
            errors.append(f"{tag} {fid}: basis must be one of {', '.join(BASES)}")
        if basis in ("observed", "user") and not str(e.get("evidence") or "").strip():
            errors.append(f"{tag} {fid}: basis '{basis}' needs evidence (which queries/sample, and when)")
        if basis == "observed" and cnt is None and sat is not None:
            warnings.append(f"{tag} {fid}: observed but no count; give the tally so saturation is derived, not guessed")
        if basis == "estimated" and not str(e.get("evidence") or "").strip() and sat is not None:
            warnings.append(f"{tag} {fid}: estimated with no reason")
    if size and counted > size:
        warnings.append(f"counts add up to {counted}, more than sample.size {size} (fine only if items were counted in two formats)")
    return errors, warnings


def resolved_format(cat: dict, scan: dict, fid: str) -> dict:
    f = copy.deepcopy(cat["_formats"][fid])
    ov = (scan.get("overrides") or {}).get(fid) or {}
    for k in ("effort", "premium", "face"):
        if k in ov:
            f[k] = ov[k]
    if "hours" in ov:
        h = ov["hours"]
        if isinstance(h, (int, float)):
            h = {x: h for x in f["lengths"]}
        f["hours"] = {**f.get("hours", {}), **h}
    f["_overridden"] = bool(ov)
    return f


def evaluate(scan: dict, cat: dict) -> list[dict]:
    """Score every entry. Pure function of the scan + catalogue."""
    sc = cat["scoring"]
    creator = scan["creator"]
    length = creator.get("length", "short")
    hpw = float(creator["hours_per_week"])
    max_effort = creator.get("max_effort", 10)
    faceless = bool(creator.get("faceless", False))
    size = (scan.get("sample") or {}).get("size")
    current = set(creator.get("current_formats", []) or [])
    w = sc["weights"]
    rows = []
    for e in scan["entries"]:
        f = resolved_format(cat, scan, e["format"])
        lay = cat["_layouts"].get(e.get("layout")) if e.get("layout") else None
        ea = lay["effort_add"] if lay else 0
        pa = lay["premium_add"] if lay else 0
        effort = clamp(f["effort"] + ea)
        premium = clamp(f["premium"] + pa)
        base_hours = (f.get("hours") or {}).get(length)
        hours = None
        if base_hours is not None:
            hours = round(base_hours * (1 + sc["layout_hours_per_effort"] * max(ea, 0)), 2)
        if e.get("count") is not None and size:
            share = e["count"] / size
            sat = saturation_from_share(share, sc["saturation_bands"])
        else:
            share = None
            sat = e.get("saturation")
        within = hours is not None and effort <= max_effort and hours <= hpw
        if length not in f["lengths"]:
            status = "n/a"
        elif faceless and f["face"] == "required":
            status = "blocked"
        elif sat is None:
            status = "unknown"
        elif premium >= sc["open"]["min_premium"] and sat <= sc["open"]["max_saturation"]:
            status = "open" if within else "stretch"
        elif effort <= sc["upgrade"]["max_effort"] and sat >= sc["upgrade"]["min_saturation"]:
            status = "upgrade"
        elif sat >= sc["crowded"]["min_saturation"]:
            status = "crowded"
        else:
            status = "neutral"
        score = None
        if sat is not None:
            score = round(w["premium"] * premium + w["openness"] * (10 - sat) + w["ease"] * (10 - effort), 2)
        rows.append({
            "format": f["id"], "layout": lay["id"] if lay else None,
            "name": f["name"] + (f" + {lay['name']}" if lay else ""),
            "effort": effort, "premium": premium, "hours": hours,
            "saturation": sat, "share": share, "count": e.get("count"),
            "basis": e.get("basis") if sat is not None else None,
            "evidence": e.get("evidence", ""), "face": f["face"],
            "within_capacity": within, "status": status, "score": score,
            "current": f["id"] in current, "overridden": f["_overridden"],
        })
    rows.sort(key=lambda r: (-(r["score"] if r["score"] is not None else -1), r["name"]))
    return rows


def test_cost(r: dict, sc: dict, pieces: int) -> float:
    h = r["hours"] or 0
    if r["status"] == "upgrade":
        h = h * sc["upgrade_hours_factor"]
    return round(h * pieces, 2)


def recommend(rows: list[dict], top: int, budget: float | None = None, sc: dict | None = None) -> list[dict]:
    """Pick 3-5 formats to test, in priority order, so the whole test fits the time budget.

    Priority: the best open cells, then one easy-but-crowded format to upgrade, then the remaining
    open cells, then neutral formats that fit. A candidate is skipped when taking it would leave too
    few hours for the minimum of three formats."""
    top = max(3, min(5, top))
    sc = sc or SCORING_DEFAULTS
    per = int(sc["test_pieces_per_format"])
    key = lambda r: -r["score"]
    opens = sorted([r for r in rows if r["status"] == "open"], key=key)
    ups = sorted([r for r in rows if r["status"] == "upgrade"], key=lambda r: (not r["current"], -r["score"]))
    neutral = sorted([r for r in rows if r["status"] == "neutral" and r["within_capacity"]
                      and r["premium"] >= sc["fill_min_premium"]], key=key)
    why_open = "open: premium enough, not crowded, fits your time"
    why_up = "easy and crowded: wins only with premium execution"
    why_mid = "middle of the map: fits your time, worth one test"
    order = ([(r, why_open) for r in opens[: top - 1]] + [(r, why_up) for r in ups[:1]]
             + [(r, why_open) for r in opens] + [(r, why_mid) for r in neutral] + [(r, why_up) for r in ups])
    picked, used, spent = [], set(), 0.0

    def reserve(exclude: str) -> float:
        need = 3 - len(picked) - 1
        if need <= 0:
            return 0.0
        costs = {}
        for r, _ in order:
            if r["format"] not in used and r["format"] != exclude:
                c = test_cost(r, sc, per)
                costs[r["format"]] = min(c, costs.get(r["format"], c))
        return sum(sorted(costs.values())[:need])

    for r, why in order:
        if len(picked) >= top:
            break
        if r["format"] in used:
            continue
        cost = test_cost(r, sc, per)
        if budget is not None and spent + cost + reserve(r["format"]) > budget + 1e-9:
            continue
        used.add(r["format"])
        spent += cost
        picked.append({**r, "why": why})
    if len(picked) < 3:  # not even three fit: take the cheapest, the plan will shrink them and warn
        rest = sorted({r["format"]: (r, why) for r, why in reversed(order) if r["format"] not in used}.values(),
                      key=lambda x: test_cost(x[0], sc, per))
        for r, why in rest[: 3 - len(picked)]:
            used.add(r["format"])
            picked.append({**r, "why": why})
    return picked


def test_plan(recs: list[dict], scan: dict, cat: dict) -> dict:
    sc = cat["scoring"]
    days = int(sc["test_days"])
    per = int(sc["test_pieces_per_format"])
    budget = round(float(scan["creator"]["hours_per_week"]) * days / 7, 2)
    warnings = []
    items = []
    for r in recs:
        h = test_cost(r, sc, 1)
        items.append({"format": r["format"], "layout": r["layout"], "name": r["name"],
                      "hours_each": h, "pieces": per, "status": r["status"]})
    total = lambda: round(sum(i["hours_each"] * i["pieces"] for i in items), 2)
    while total() > budget and len(items) > 3:
        dropped = items.pop()
        warnings.append(f"dropped {dropped['name']} from the test: not enough hours for {len(items) + 1} formats")
    for i in sorted(items, key=lambda i: -i["hours_each"]):
        if total() <= budget:
            break
        if i["pieces"] > 1:
            i["pieces"] = 1
            warnings.append(f"{i['name']}: only 1 piece fits; treat its result as a hint, not a verdict")
    if total() > budget:
        weeks = math.ceil(total() / float(scan["creator"]["hours_per_week"]))
        warnings.append(f"the test needs {num(total())}h but you have {num(budget)}h in {days} days; "
                        f"run it over {weeks} weeks or swap in a lower-effort format")
    seq = []
    rnd = 0
    while any(i["pieces"] > rnd for i in items):
        for i in items:
            if i["pieces"] > rnd:
                seq.append(i)
        rnd += 1
    calendar = []
    n = len(seq)
    counts = {}
    for k, i in enumerate(seq):
        counts[i["name"]] = counts.get(i["name"], 0) + 1
        day = 1 + math.floor((k + 0.5) * days / n) if n else 1
        calendar.append({"day": min(day, days), "name": i["name"], "piece": counts[i["name"]],
                         "hours": i["hours_each"], "format": i["format"]})
    return {"days": days, "budget_hours": budget, "total_hours": total(),
            "spare_hours": round(budget - total(), 2), "items": items,
            "calendar": calendar, "warnings": warnings}


def upgrade_targets(rows: list[dict], recs: list[dict], cat: dict, scan: dict) -> list[str]:
    """Easy formats the creator makes now, plus recommended 'upgrade' formats."""
    easy = cat["scoring"]["upgrade"]["max_effort"]
    ids = []
    for fid in scan["creator"].get("current_formats", []) or []:
        if resolved_format(cat, scan, fid)["effort"] <= easy and fid not in ids:
            ids.append(fid)
    for r in recs:
        if r["status"] == "upgrade" and r["format"] not in ids:
            ids.append(r["format"])
    return ids


def build_result(scan: dict, cat: dict, top: int = 4) -> dict:
    errors, warnings = validate_scan(scan, cat)
    if errors:
        fail("scan file has problems:\n  - " + "\n  - ".join(errors))
    rows = evaluate(scan, cat)
    sc = cat["scoring"]
    budget = float(scan["creator"]["hours_per_week"]) * int(sc["test_days"]) / 7
    recs = recommend(rows, top, budget, sc)
    plan = test_plan(recs, scan, cat)
    kept = {(i["format"], i["layout"]) for i in plan["items"]}
    recs = [r for r in recs if (r["format"], r["layout"]) in kept]
    bases = {b: sum(1 for r in rows if r["basis"] == b) for b in BASES}
    bases["unknown"] = sum(1 for r in rows if r["saturation"] is None and r["status"] != "n/a")
    if len(recs) < 3:
        warnings.append(f"only {len(recs)} format(s) qualify; fill in more saturation values or relax max_effort")
    known = sum(bases[b] for b in BASES)
    if known and bases["estimated"] / known > 0.5:
        warnings.append("most saturation values are estimated, not observed: treat the map as a hypothesis "
                        "and check it against a real sample of the niche")
    return {"niche": scan["niche"], "date": scan.get("date") or dt.date.today().isoformat(),
            "creator": scan["creator"], "sample": scan.get("sample") or {},
            "rows": rows, "recommendations": recs, "plan": plan,
            "upgrades": [{"id": fid, "name": cat["_formats"][fid]["name"],
                          "checklist": cat["_formats"][fid].get("upgrades", {})}
                         for fid in upgrade_targets(rows, recs, cat, scan)],
            "bases": bases, "warnings": warnings}


# --------------------------------------------------------------------------- grid

def bucket(v: float) -> int:
    """1-10 -> 0..4 (1-2, 3-4, 5-6, 7-8, 9-10)."""
    return int(min(4, max(0, (math.ceil(v) - 1) // 2)))


BUCKET_LABEL = ["1-2", "3-4", "5-6", "7-8", "9-10"]


def grid(rows: list[dict]) -> list[list[list[dict]]]:
    """grid[premium_bucket][effort_bucket] -> rows (premium 0 = lowest)."""
    g = [[[] for _ in range(5)] for _ in range(5)]
    for r in rows:
        if r["status"] == "n/a":
            continue
        g[bucket(r["premium"])][bucket(r["effort"])].append(r)
    return g


def heat_colour(sat) -> str:
    """Saturation 0-10 -> background colour, green (open) to red (saturated)."""
    if sat is None:
        return "var(--empty)"
    t = max(0.0, min(1.0, sat / 10))
    hue = round(140 - 140 * t)
    return f"hsl({hue} 70% var(--heat-l))"


# --------------------------------------------------------------------------- markdown

def checklist_md(up: dict) -> list[str]:
    lines = [f"**{up['name']}**"]
    for k in ("polish", "insight", "novelty", "detail"):
        for item in up["checklist"].get(k, []):
            lines.append(f"- [ ] *{k.capitalize()}:* {item}")
    return lines


def render_md(res: dict) -> str:
    c = res["creator"]
    L = [f"# Format map: {res['niche']}", ""]
    L.append(f"{res['date']} · {c.get('length', 'short')}-form · "
             f"{'faceless' if c.get('faceless') else 'on camera OK'} · {num(c['hours_per_week'])}h/week"
             + (f" · max effort {num(c['max_effort'])}" if c.get("max_effort") else ""))
    b = res["bases"]
    L.append(f"Saturation basis: {b['observed']} observed, {b['user']} from you, {b['estimated']} estimated, "
             f"{b['unknown']} unknown" + (f" · sample of {res['sample']['size']}" if res["sample"].get("size") else ""))
    L.append("")
    L += ["| # | Format | Effort | Premium | Saturation | Basis | Hours | Score | Status |",
          "|---|---|---|---|---|---|---|---|---|"]
    rec_keys = {(r["format"], r["layout"]) for r in res["recommendations"]}
    for i, r in enumerate([r for r in res["rows"] if r["status"] != "n/a"], 1):
        star = " ★" if (r["format"], r["layout"]) in rec_keys else ""
        sat = num(r["saturation"]) + (f" ({r['count']}/{res['sample'].get('size')})" if r["count"] is not None else "")
        L.append(f"| {i} | {r['name']}{star} | {num(r['effort'])} | {num(r['premium'])} | {sat} | "
                 f"{r['basis'] or '-'} | {num(r['hours'])} | {num(r['score'])} | {STATUS_LABEL[r['status']]} |")
    L += ["", "★ = recommended to test. Open = premium ≥ threshold, low saturation, within your time.", ""]
    L += ["## Test next", ""]
    for i, r in enumerate(res["recommendations"], 1):
        L.append(f"{i}. **{r['name']}** · effort {num(r['effort'])}, premium {num(r['premium'])}, "
                 f"saturation {num(r['saturation'])} · {r['why']}")
    p = res["plan"]
    L += ["", f"## 2-week test plan ({num(p['total_hours'])}h of {num(p['budget_hours'])}h available)", "",
          "| Day | Piece | Hours |", "|---|---|---|"]
    for k in p["calendar"]:
        L.append(f"| {k['day']} | {k['name']} #{k['piece']} | {num(k['hours'])} |")
    if res["upgrades"]:
        L += ["", "## Premium upgrades for your easy formats", ""]
        for up in res["upgrades"]:
            L += checklist_md(up) + [""]
    notes = res["warnings"] + p["warnings"]
    if notes:
        L += ["", "## Notes", ""] + [f"- {w}" for w in notes]
    return "\n".join(L).rstrip() + "\n"


# --------------------------------------------------------------------------- html

CSS = """
:root{--bg:#f7f6f2;--fg:#1d1d1f;--muted:#6b6b70;--card:#ffffff;--line:#dcdad3;--empty:#eeece6;--heat-l:82%;
--open:#0a7d3c;--stretch:#2a5fb0;--upgrade:#b06a00;--crowded:#b3261e;--neutral:#6b6b70;--unknown:#8a8a8a;--blocked:#9a9a9a}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--fg:#ececf0;--muted:#a0a0a8;--card:#1c1c20;--line:#33333a;
--empty:#1f1f24;--heat-l:26%;--open:#4ad07f;--stretch:#7aa8ff;--upgrade:#ffb547;--crowded:#ff7a70;--neutral:#a0a0a8;--unknown:#8a8a8a;--blocked:#6a6a70}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px}
.meta{color:var(--muted);margin:0 0 4px}.map{display:grid;grid-template-columns:34px repeat(5,minmax(0,1fr));gap:4px;margin-top:16px}
.cell{min-height:96px;border-radius:8px;padding:6px;display:flex;flex-wrap:wrap;align-content:flex-start;gap:4px;border:1px solid var(--line)}
.ax{color:var(--muted);font-size:12px;display:flex;align-items:center;justify-content:center;text-align:center}
.ylab{writing-mode:vertical-rl;transform:rotate(180deg)}
.chip{font-size:12px;line-height:1.25;background:var(--card);border-radius:6px;padding:3px 6px;border:2px solid var(--neutral);max-width:100%}
.chip small{display:block;color:var(--muted);font-size:10.5px}
.chip.open{border-color:var(--open);font-weight:600}.chip.stretch{border-color:var(--stretch);border-style:dashed}
.chip.upgrade{border-color:var(--upgrade)}.chip.crowded{border-color:var(--crowded)}
.chip.unknown{border-color:var(--unknown);border-style:dotted}.chip.blocked{border-color:var(--blocked);opacity:.55;text-decoration:line-through}
.chip.rec{box-shadow:0 0 0 2px var(--fg)}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;font-size:13px}.legend .chip{font-weight:400}
.scale{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}.scale span{display:inline-block;width:18px;height:12px;border-radius:3px}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13.5px;background:var(--card)}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{font-size:12px;color:var(--muted);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}.st{font-weight:600;white-space:nowrap}
.st.open{color:var(--open)}.st.stretch{color:var(--stretch)}.st.upgrade{color:var(--upgrade)}.st.crowded{color:var(--crowded)}.st.unknown,.st.blocked,.st.neutral{color:var(--muted)}
.ev{color:var(--muted);font-size:12px}ol li,ul li{margin:4px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.card h3{margin:0 0 6px;font-size:15px}
.card ul{list-style:none;padding:0;margin:0}.card li{font-size:13.5px}.card li b{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-right:4px}
.note{background:var(--card);border-left:3px solid var(--upgrade);padding:8px 12px;margin:6px 0;font-size:13.5px}
@media (max-width:640px){.map{grid-template-columns:22px repeat(5,minmax(0,1fr));gap:2px}.cell{min-height:70px;padding:3px}.chip{font-size:10.5px;padding:2px 4px}.chip small{display:none}h1{font-size:22px}}
"""


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def render_html(res: dict) -> str:
    c = res["creator"]
    rec_keys = {(r["format"], r["layout"]) for r in res["recommendations"]}
    g = grid(res["rows"])
    parts = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
             f"<title>Format map: {esc(res['niche'])}</title><style>{CSS}</style></head><body><main>"]
    parts.append(f"<h1>Format map: {esc(res['niche'])}</h1>")
    parts.append(f"<p class=\"meta\">{esc(res['date'])} · {esc(c.get('length', 'short'))}-form · "
                 f"{'faceless' if c.get('faceless') else 'on camera OK'} · {esc(num(c['hours_per_week']))}h/week"
                 + (f" · max effort {esc(num(c['max_effort']))}" if c.get("max_effort") else "") + "</p>")
    b = res["bases"]
    parts.append(f"<p class=\"meta\">Saturation basis: {b['observed']} observed · {b['user']} from you · "
                 f"{b['estimated']} estimated · {b['unknown']} unknown"
                 + (f" · sample of {esc(res['sample']['size'])} results" if res["sample"].get("size") else "") + "</p>")
    for w in res["warnings"]:
        parts.append(f"<div class=\"note\">{esc(w)}</div>")
    # legend
    parts.append("<div class=\"legend\">")
    for st in ("open", "stretch", "upgrade", "crowded", "neutral", "unknown", "blocked"):
        parts.append(f"<span class=\"chip {st}\">{esc(STATUS_LABEL[st])}</span>")
    parts.append("<span class=\"chip rec\">★ Recommended</span></div>")
    parts.append("<div class=\"scale\">Cell colour = the most saturated format in it: "
                 + "".join(f"<span style=\"background:{heat_colour(s)}\"></span>" for s in (0, 2, 4, 6, 8, 10))
                 + " 0 (open) → 10 (saturated)</div>")
    # map: rows from high premium to low
    parts.append("<div class=\"map\" role=\"table\" aria-label=\"Effort by premium map\">")
    for pb in range(4, -1, -1):
        parts.append(f"<div class=\"ax\">{BUCKET_LABEL[pb]}</div>")
        for eb in range(5):
            cell = g[pb][eb]
            sats = [r["saturation"] for r in cell if r["saturation"] is not None]
            top_sat = max(sats) if sats else None
            title = f"Premium {BUCKET_LABEL[pb]}, effort {BUCKET_LABEL[eb]}" + (
                f", highest saturation {num(top_sat)}" if top_sat is not None else "")
            parts.append(f"<div class=\"cell\" role=\"cell\" title=\"{esc(title)}\" style=\"background:{heat_colour(top_sat)}\">")
            for r in sorted(cell, key=lambda r: (STATUSES.index(r["status"]), r["name"])):
                rec = (r["format"], r["layout"]) in rec_keys
                sat = "?" if r["saturation"] is None else num(r["saturation"])
                basis = {"observed": "obs", "user": "you", "estimated": "est"}.get(r["basis"], "")
                parts.append(f"<span class=\"chip {r['status']}{' rec' if rec else ''}\" title=\"{esc(STATUS_LABEL[r['status']])}\">"
                             f"{'★ ' if rec else ''}{esc(r['name'])}<small>sat {esc(sat)} {basis}</small></span>")
            parts.append("</div>")
    parts.append("<div></div>" + "".join(f"<div class=\"ax\">{l}</div>" for l in BUCKET_LABEL))
    parts.append("</div><p class=\"meta\" style=\"text-align:center\">Effort (production cost) →</p>")
    parts.append("<p class=\"meta\">↑ Perceived premium. The upper rows break out most easily; green cells there are the openings.</p>")
    # recommendations
    parts.append("<h2>Test next</h2><ol>")
    for r in res["recommendations"]:
        parts.append(f"<li><b>{esc(r['name'])}</b> · effort {esc(num(r['effort']))}, premium {esc(num(r['premium']))}, "
                     f"saturation {esc(num(r['saturation']))} · {esc(r['why'])}</li>")
    parts.append("</ol>")
    p = res["plan"]
    parts.append(f"<h2>2-week test plan</h2><p class=\"meta\">{esc(num(p['total_hours']))}h planned of "
                 f"{esc(num(p['budget_hours']))}h available · {esc(num(p['spare_hours']))}h spare</p>")
    parts.append("<div class=\"tablewrap\"><table><tr><th>Day</th><th>Piece</th><th>Hours</th></tr>")
    for k in p["calendar"]:
        parts.append(f"<tr><td class=\"n\">{k['day']}</td><td>{esc(k['name'])} #{k['piece']}</td><td class=\"n\">{esc(num(k['hours']))}</td></tr>")
    parts.append("</table></div>")
    for w in p["warnings"]:
        parts.append(f"<div class=\"note\">{esc(w)}</div>")
    if res["upgrades"]:
        parts.append("<h2>Premium upgrades for your easy formats</h2><div class=\"cards\">")
        for up in res["upgrades"]:
            parts.append(f"<div class=\"card\"><h3>{esc(up['name'])}</h3><ul>")
            for k in ("polish", "insight", "novelty", "detail"):
                for item in up["checklist"].get(k, []):
                    parts.append(f"<li><b>{k}</b>☐ {esc(item)}</li>")
            parts.append("</ul></div>")
        parts.append("</div>")
    # table
    parts.append("<h2>All formats</h2><div class=\"tablewrap\"><table><tr><th>Format</th><th>Effort</th><th>Premium</th>"
                 "<th>Saturation</th><th>Basis</th><th>Hours</th><th>Score</th><th>Status</th></tr>")
    for r in res["rows"]:
        if r["status"] == "n/a":
            continue
        rec = (r["format"], r["layout"]) in rec_keys
        ev = f"<div class=\"ev\">{esc(r['evidence'])}</div>" if r["evidence"] else ""
        parts.append(f"<tr><td>{'★ ' if rec else ''}{esc(r['name'])}{ev}</td><td class=\"n\">{esc(num(r['effort']))}</td>"
                     f"<td class=\"n\">{esc(num(r['premium']))}</td><td class=\"n\">{esc(num(r['saturation']))}</td>"
                     f"<td>{esc(r['basis'] or '-')}</td><td class=\"n\">{esc(num(r['hours']))}</td>"
                     f"<td class=\"n\">{esc(num(r['score']))}</td><td class=\"st {r['status']}\">{esc(STATUS_LABEL[r['status']])}</td></tr>")
    parts.append("</table></div>")
    parts.append("<p class=\"meta\" style=\"margin-top:24px\">Made with FormatMap. Effort and premium are editable starting "
                 "ratings; saturation is only as good as the sample behind it.</p>")
    parts.append("</main></body></html>")
    return "".join(parts)


# --------------------------------------------------------------------------- commands

def cmd_catalogue(a, cat):
    if a.layouts:
        items = cat.get("layouts", [])
        if a.json:
            out(json.dumps(items, indent=2, ensure_ascii=False))
            return
        out("| Layout id | Name | Effort + | Premium + | What it is |\n|---|---|---|---|---|")
        for l in items:
            out(f"| {l['id']} | {l['name']} | {l['effort_add']:+} | {l['premium_add']:+} | {l.get('definition', '')} |")
        return
    items = [f for f in cat["formats"] if not a.length or a.length in f["lengths"]]
    if a.json:
        out(json.dumps(items, indent=2, ensure_ascii=False))
        return
    out("| Format id | Name | Effort | Premium | Face | Hours (short/long) |\n|---|---|---|---|---|---|")
    for f in sorted(items, key=lambda f: (f["effort"], -f["premium"])):
        h = "/".join(num(f["hours"].get(x)) if x in f["lengths"] else "-" for x in LENGTHS)
        out(f"| {f['id']} | {f['name']} | {num(f['effort'])} | {num(f['premium'])} | {f['face']} | {h} |")


def cmd_show(a, cat):
    for fid in a.ids:
        f = cat["_formats"].get(fid) or cat["_layouts"].get(fid)
        if not f:
            fail(f"unknown format or layout {fid!r}")
        out(f"## {f['name']} ({fid})")
        if "effort" in f:
            out(f"Effort {num(f['effort'])} · premium {num(f['premium'])} · face {f['face']} · "
                f"lengths {', '.join(f['lengths'])} · hours " + ", ".join(f"{k} {num(v)}" for k, v in f["hours"].items()))
        else:
            out(f"Layout · effort {f['effort_add']:+} · premium {f['premium_add']:+}")
        out(f.get("definition", ""))
        for ex in f.get("examples", []):
            out(f"- e.g. {ex}")
        if f.get("upgrades"):
            out("\nPremium upgrade checklist:")
            for line in checklist_md({"name": f["name"], "checklist": f["upgrades"]})[1:]:
                out(line)
        out()


def cmd_template(a, cat):
    creator = {"faceless": bool(a.faceless), "length": a.length, "hours_per_week": a.hours,
               "current_formats": a.current or [], "platforms": a.platforms or []}
    if a.max_effort:
        creator["max_effort"] = a.max_effort
    for cid in creator["current_formats"]:
        if cid not in cat["_formats"]:
            fail(f"--current: unknown format {cid!r}")
    scan = {
        "niche": a.niche,
        "date": dt.date.today().isoformat(),
        "sample": {"size": None, "queries": [], "platforms": a.platforms or [], "note": ""},
        "creator": creator,
        "overrides": {},
        "entries": [{"format": f["id"], "layout": None, "count": None, "saturation": None,
                     "basis": None, "evidence": ""}
                    for f in cat["formats"] if a.length in f["lengths"]],
    }
    text = json.dumps(scan, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        out(f"wrote {a.out} with {len(scan['entries'])} entries. Fill in count (with sample.size) or saturation + basis + evidence.")
    else:
        out(text)


def cmd_check(a, cat):
    scan = load_json(Path(a.scan), "scan file")
    errors, warnings = validate_scan(scan, cat)
    for e in errors:
        out(f"ERROR   {e}")
    for w in warnings:
        out(f"warning {w}")
    if errors:
        raise FormatMapError(f"{len(errors)} error(s)")
    out(f"ok: {len(scan['entries'])} entries" + (f", {len(warnings)} warning(s)" if warnings else ""))


def cmd_build(a, cat):
    scan = load_json(Path(a.scan), "scan file")
    res = build_result(scan, cat, a.top)
    d = Path(a.out_dir)
    d.mkdir(parents=True, exist_ok=True)
    md = render_md(res)
    (d / "formatmap.md").write_text(md, encoding="utf-8")
    (d / "formatmap.html").write_text(render_html(res), encoding="utf-8")
    if a.json:
        (d / "formatmap.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    out(md)
    out(f"wrote {d / 'formatmap.html'} and {d / 'formatmap.md'}")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(prog="formatmap.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--catalogue", help="ratings file (default: references/catalogue.json)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("catalogue")
    s.add_argument("--length", choices=LENGTHS)
    s.add_argument("--layouts", action="store_true")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("ids", nargs="+")
    s = sub.add_parser("template")
    s.add_argument("--niche", required=True)
    s.add_argument("--length", choices=LENGTHS, default="short")
    s.add_argument("--faceless", action="store_true")
    s.add_argument("--hours", type=float, default=6, help="hours per week for content")
    s.add_argument("--max-effort", type=float)
    s.add_argument("--current", nargs="*", help="format ids the creator makes now")
    s.add_argument("--platforms", nargs="*")
    s.add_argument("--out")
    s = sub.add_parser("check")
    s.add_argument("scan")
    s = sub.add_parser("build")
    s.add_argument("scan")
    s.add_argument("--out-dir", default="formatmap-out")
    s.add_argument("--top", type=int, default=4, help="formats to recommend (3-5)")
    s.add_argument("--json", action="store_true", help="also write formatmap.json")
    a = p.parse_args(argv)
    cat = load_catalogue(a.catalogue)
    {"catalogue": cmd_catalogue, "show": cmd_show, "template": cmd_template,
     "check": cmd_check, "build": cmd_build}[a.cmd](a, cat)


if __name__ == "__main__":
    main()
