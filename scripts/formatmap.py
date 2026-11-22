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
    "upgrade_min_extra_hours": 1,
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
        plats = f.get("platforms")
        if plats is not None and (not isinstance(plats, list) or not all(isinstance(x, str) for x in plats)):
            fail(f"catalogue format {fid}: platforms must be a list of platform names")
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

def entry_label(e: dict) -> str:
    return str(e.get("format")) + (f" + {e['layout']}" if e.get("layout") else "")


def norm_platform(p: str) -> str:
    return str(p).strip().lower().replace(" ", "-").replace("_", "-")


def validate_scan(scan: dict, cat: dict) -> tuple[list, list]:
    """Return (errors, warnings). Errors stop a build. Both are for whoever fills in the scan,
    not for the creator, so they never appear in the HTML or markdown report."""
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
    thw = creator.get("test_hours_per_week")
    if thw is not None and (not isinstance(thw, (int, float)) or thw <= 0):
        errors.append("creator.test_hours_per_week must be a positive number (or leave it out)")
    me = creator.get("max_effort", 10)
    if not isinstance(me, (int, float)) or not 1 <= me <= 10:
        errors.append("creator.max_effort must be 1-10 (leave it out for no limit)")
    if not isinstance(creator.get("faceless", False), bool):
        errors.append("creator.faceless must be true or false")
    if not isinstance(creator.get("platforms", []) or [], list):
        errors.append("creator.platforms must be a list, e.g. [\"youtube-shorts\", \"tiktok\"]")
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
    shared_evidence = str(sample.get("evidence") or "").strip()
    entries = scan.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("'entries' must be a non-empty list")
        entries = []
    seen = set()
    counted = 0
    for e in entries:
        tag = entry_label(e)
        fid, lid = e.get("format"), e.get("layout")
        if fid not in cat["_formats"]:
            errors.append(f"{tag}: unknown format (run 'catalogue' for ids)")
            continue
        if lid is not None and lid not in cat["_layouts"]:
            errors.append(f"{tag}: unknown layout (run 'catalogue --layouts')")
        key = (fid, lid)
        if key in seen:
            errors.append(f"{tag}: listed twice")
        seen.add(key)
        app = e.get("applicable", True)
        if not isinstance(app, bool):
            errors.append(f"{tag}: applicable must be true or false")
        elif app is False:
            if not str(e.get("reason") or "").strip():
                warnings.append(f"{tag}: marked not applicable without a 'reason'")
            continue
        sat, cnt, adj = e.get("saturation"), e.get("count"), e.get("adjust", 0)
        if sat is not None and (not isinstance(sat, (int, float)) or not 0 <= sat <= 10):
            errors.append(f"{tag}: saturation must be 0-10 or null")
        if adj not in (-1, 0, 1):
            errors.append(f"{tag}: adjust must be -1, 0 or 1")
        elif adj and sat is None and cnt is None:
            errors.append(f"{tag}: adjust needs a count or a saturation to adjust")
        elif adj and not str(e.get("evidence") or "").strip():
            warnings.append(f"{tag}: adjusted by {adj:+} without saying why in 'evidence'")
        if cnt is not None:
            if not isinstance(cnt, int) or cnt < 0:
                errors.append(f"{tag}: count must be a whole number >= 0")
            elif size is None:
                errors.append(f"{tag}: has a count but sample.size is missing")
            elif cnt > size:
                errors.append(f"{tag}: count {cnt} is larger than sample.size {size}")
            else:
                counted += cnt
            if sat is not None:
                warnings.append(f"{tag}: both count and saturation given; the count wins (use 'adjust' to nudge it)")
        basis = e.get("basis")
        if (sat is not None or cnt is not None) and basis not in BASES:
            errors.append(f"{tag}: basis must be one of {', '.join(BASES)}")
        has_ev = str(e.get("evidence") or "").strip() or shared_evidence
        if basis in ("observed", "user") and not has_ev:
            errors.append(f"{tag}: basis '{basis}' needs evidence (in the entry or in sample.evidence)")
        if basis == "estimated" and sat is not None and not str(e.get("evidence") or "").strip():
            warnings.append(f"{tag}: estimated with no reason")
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


STATUS_RANK = {"open": 0, "upgrade": 1, "stretch": 2, "neutral": 3, "crowded": 4, "unknown": 5, "blocked": 6, "n/a": 7}


def sort_rows(rows: list[dict]) -> list[dict]:
    """Actionable first (open, upgrade, stretch...). Within a status, observed evidence before
    estimates, then by score."""
    return sorted(rows, key=lambda r: (STATUS_RANK[r["status"]], r["basis"] == "estimated",
                                       -(r["score"] if r["score"] is not None else -1), r["name"]))


def evaluate(scan: dict, cat: dict) -> list[dict]:
    """Score every entry. Pure function of the scan + catalogue."""
    sc = cat["scoring"]
    creator = scan["creator"]
    length = creator.get("length", "short")
    hpw = float(creator["hours_per_week"])
    max_effort = creator.get("max_effort", 10)
    faceless = bool(creator.get("faceless", False))
    sample = scan.get("sample") or {}
    size = sample.get("size")
    shared_evidence = str(sample.get("evidence") or "").strip()
    current = set(creator.get("current_formats", []) or [])
    platforms = [norm_platform(p) for p in creator.get("platforms", []) or []]
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
        if sat is not None and e.get("adjust"):
            sat = clamp(sat + e["adjust"], 0, 10)
        native = platforms
        if platforms and f.get("platforms"):
            native = [p for p in platforms if any(p.startswith(norm_platform(fp)) for fp in f["platforms"])]
        within = hours is not None and effort <= max_effort and hours <= hpw
        reason = ""
        if e.get("applicable", True) is False:
            status, reason = "n/a", str(e.get("reason") or "not relevant to this niche")
        elif length not in f["lengths"]:
            status, reason = "n/a", f"not a {length}-form format"
        elif platforms and not native:
            status, reason = "n/a", "not native to " + ", ".join(platforms)
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
        if sat is not None and status != "n/a":
            score = round(w["premium"] * premium + w["openness"] * (10 - sat) + w["ease"] * (10 - effort), 2)
        platform_note = ""
        if platforms and native and len(native) < len(platforms):
            platform_note = "only on " + ", ".join(native)
        evidence = str(e.get("evidence") or "").strip()
        rows.append({
            "format": f["id"], "layout": lay["id"] if lay else None,
            "name": f["name"] + (f" + {lay['name']}" if lay else ""),
            "effort": effort, "premium": premium, "hours": hours,
            "saturation": sat, "share": share, "count": e.get("count"), "adjust": e.get("adjust", 0),
            "basis": e.get("basis") if sat is not None and status != "n/a" else None,
            "evidence": evidence, "shared_evidence": not evidence and e.get("basis") in ("observed", "user") and bool(shared_evidence),
            "face": f["face"], "within_capacity": within, "status": status, "reason": reason,
            "platform_note": platform_note, "score": score,
            "current": f["id"] in current, "overridden": f["_overridden"],
        })
    return sort_rows(rows)


def test_cost(r: dict, sc: dict, pieces: int) -> float:
    """Hours the test adds. Upgrading a format the creator already posts only costs the extra time,
    because the upgraded piece replaces a post they would have made anyway."""
    h = r["hours"] or 0
    if r["status"] == "upgrade":
        f = sc["upgrade_hours_factor"]
        h = max(h * (f - 1), sc["upgrade_min_extra_hours"]) if r.get("current") else h * f
    return round(h * pieces, 2)


WHY = {
    "open": "open: premium enough, not crowded, fits your time",
    "upgrade": "easy and crowded: wins only with premium execution",
    "upgrade-current": "you already make it and it's crowded: test one premium upgrade in place of a usual post",
    "neutral": "middle of the map: added only to reach three formats within your hours",
}


def recommend(rows: list[dict], top: int, budget: float | None = None, sc: dict | None = None) -> list[dict]:
    """Pick 3-5 formats to test so that at least one piece of each fits the time budget.

    Formats that fit a full test (2 pieces) are taken first, then single pieces of the next best.
    Priority: one easy-but-crowded format to upgrade (the creator's own first: it costs only the
    extra hours), then open cells (observed before estimated, then by score). Neutral formats are
    used only to reach the minimum of three. A candidate is skipped when taking it would leave too
    few hours for one piece of each of the three."""
    top = max(3, min(5, top))
    sc = sc or SCORING_DEFAULTS
    ups = sorted([r for r in rows if r["status"] == "upgrade"], key=lambda r: (not r["current"], -r["score"]))
    opens = [r for r in rows if r["status"] == "open"]  # rows are already in priority order
    neutral = sorted([r for r in rows if r["status"] == "neutral" and r["within_capacity"]
                      and r["premium"] >= sc["fill_min_premium"]], key=lambda r: -r["score"])
    main = [(r, "upgrade-current" if r["current"] else "upgrade") for r in ups[:1]] + [(r, "open") for r in opens]
    fill = main + [(r, "neutral") for r in neutral]
    picked, used = [], set()
    spent = [0.0]

    def reserve(pool, exclude: str, pieces: int) -> float:
        need = 3 - len(picked) - 1
        if need <= 0:
            return 0.0
        costs = {}
        for r, _ in pool:
            if r["format"] not in used and r["format"] != exclude:
                c = test_cost(r, sc, pieces)
                costs[r["format"]] = min(c, costs.get(r["format"], c))
        return sum(sorted(costs.values())[:need])

    def run(pool, limit, pieces=1):
        for r, why in pool:
            if len(picked) >= limit:
                return
            if r["format"] in used:
                continue
            cost = test_cost(r, sc, pieces)
            if budget is not None and spent[0] + cost + reserve(pool, r["format"], pieces) > budget + 1e-9:
                continue
            used.add(r["format"])
            spent[0] += cost
            picked.append({**r, "why": WHY[why]})

    per = int(sc["test_pieces_per_format"])
    run(main, top, per)  # first: formats that get a full test
    run(main, top, 1)  # then: one piece of the next best, if hours remain
    if len(picked) < 3:
        run(fill, 3)
    if len(picked) < 3:  # not even three fit: take the cheapest; the plan will warn
        rest = {}
        for r, why in fill:
            if r["format"] not in used and r["format"] not in rest:
                rest[r["format"]] = (r, why)
        for r, why in sorted(rest.values(), key=lambda x: test_cost(x[0], sc, 1))[: 3 - len(picked)]:
            used.add(r["format"])
            picked.append({**r, "why": WHY[why]})
    return picked


def test_budget(scan: dict, sc: dict) -> float:
    c = scan["creator"]
    return round(float(c.get("test_hours_per_week") or c["hours_per_week"]) * int(sc["test_days"]) / 7, 2)


def test_plan(recs: list[dict], scan: dict, cat: dict) -> dict:
    """One piece of each format first, then second pieces in priority order while hours allow."""
    sc = cat["scoring"]
    days = int(sc["test_days"])
    per = int(sc["test_pieces_per_format"])
    budget = test_budget(scan, sc)
    warnings = []
    items = [{"format": r["format"], "layout": r["layout"], "name": r["name"],
              "hours_each": test_cost(r, sc, 1), "pieces": 1, "status": r["status"],
              "upgrade_of_current": r["status"] == "upgrade" and bool(r.get("current"))} for r in recs]
    total = lambda: round(sum(i["hours_each"] * i["pieces"] for i in items), 2)
    for _ in range(per - 1):
        for i in items:
            if total() + i["hours_each"] <= budget + 1e-9:
                i["pieces"] += 1
    for i in items:
        if i["pieces"] < per:
            warnings.append(f"{i['name']}: only {i['pieces']} piece fits your hours; treat its result as a hint, not a verdict")
    if total() > budget:
        hpw = float(scan["creator"].get("test_hours_per_week") or scan["creator"]["hours_per_week"])
        weeks = math.ceil(total() / hpw)
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
                         "hours": i["hours_each"], "format": i["format"],
                         "replaces_usual_post": i["upgrade_of_current"]})
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
    errors, check_warnings = validate_scan(scan, cat)
    if errors:
        fail("scan file has problems:\n  - " + "\n  - ".join(errors))
    rows = evaluate(scan, cat)
    sc = cat["scoring"]
    recs = recommend(rows, top, test_budget(scan, sc), sc)
    plan = test_plan(recs, scan, cat)
    warnings = []
    live = [r for r in rows if r["status"] != "n/a"]
    bases = {b: sum(1 for r in live if r["basis"] == b) for b in BASES}
    bases["unknown"] = sum(1 for r in live if r["saturation"] is None)
    picked = {r["format"] for r in recs}
    if len(recs) < 3:
        warnings.append(f"only {len(recs)} format(s) qualify; fill in more saturation values or relax max_effort")
    elif len(recs) < max(3, min(5, top)) and any(r["status"] == "open" and r["format"] not in picked for r in rows):
        warnings.append(f"{len(recs)} formats fit your test hours; the other open formats on the map are for when you have more time")
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
            "bases": bases, "warnings": warnings, "check_warnings": check_warnings}


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
    if res["sample"].get("evidence"):
        L.append(f"Sample: {res['sample']['evidence']}")
    L.append("")
    L += ["| # | Format | Effort | Premium | Saturation | Basis | Hours | Score | Status |",
          "|---|---|---|---|---|---|---|---|---|"]
    rec_keys = {(r["format"], r["layout"]) for r in res["recommendations"]}
    for i, r in enumerate([r for r in res["rows"] if r["status"] != "n/a"], 1):
        star = " ★" if (r["format"], r["layout"]) in rec_keys else ""
        sat = num(r["saturation"]) + (f" ({r['count']}/{res['sample'].get('size')})" if r["count"] is not None else "")
        if r.get("adjust"):
            sat += f" {r['adjust']:+}"
        note = f" ({r['platform_note']})" if r.get("platform_note") else ""
        L.append(f"| {i} | {r['name']}{star} | {num(r['effort'])} | {num(r['premium'])} | {sat} | "
                 f"{r['basis'] or '-'} | {num(r['hours'])} | {num(r['score'])} | {STATUS_LABEL[r['status']]}{note} |")
    L += ["", "★ = recommended to test. Open = premium ≥ threshold, low saturation, within your time."]
    left = [r for r in res["rows"] if r["status"] == "n/a"]
    if left:
        L.append("Left out: " + "; ".join(f"{r['name']} ({r['reason']})" for r in left) + ".")
    L.append("")
    L += ["## Test next", ""]
    for i, r in enumerate(res["recommendations"], 1):
        L.append(f"{i}. **{r['name']}** · effort {num(r['effort'])}, premium {num(r['premium'])}, "
                 f"saturation {num(r['saturation'])} · {r['why']}")
    p = res["plan"]
    L += ["", f"## 2-week test plan ({num(p['total_hours'])}h of {num(p['budget_hours'])}h available)", "",
          "| Day | Piece | Hours |", "|---|---|---|"]
    for k in p["calendar"]:
        extra = " (replaces a usual post; extra hours only)" if k.get("replaces_usual_post") else ""
        L.append(f"| {k['day']} | {k['name']} #{k['piece']}{extra} | {num(k['hours'])} |")
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
--zone:#fbf8ee;--zone-line:#d9c98f;--open:#0a7d3c;--stretch:#2a5fb0;--upgrade:#b06a00;--crowded:#b3261e;--neutral:#6b6b70;--unknown:#8a8a8a;--blocked:#9a9a9a}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--fg:#ececf0;--muted:#a0a0a8;--card:#1c1c20;--line:#33333a;
--empty:#18181b;--zone:#22211b;--zone-line:#5a5236;--heat-l:26%;--open:#4ad07f;--stretch:#7aa8ff;--upgrade:#ffb547;--crowded:#ff7a70;--neutral:#a0a0a8;--unknown:#8a8a8a;--blocked:#6a6a70}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px}
.meta{color:var(--muted);margin:0 0 4px}.map{display:grid;grid-template-columns:34px repeat(5,minmax(0,1fr));gap:4px;margin-top:16px}
.cell{min-height:96px;border-radius:8px;padding:6px;display:flex;flex-wrap:wrap;align-content:flex-start;gap:4px;border:1px solid var(--line);background:var(--card)}
.cell.hi{background:var(--zone);border-color:var(--zone-line)}.cell.lo{background:var(--empty)}.cell.lo .chip{opacity:.72}
.ax{color:var(--muted);font-size:12px;display:flex;align-items:center;justify-content:center;text-align:center}
.ylab{writing-mode:vertical-rl;transform:rotate(180deg)}
.chip{font-size:12px;line-height:1.25;background:var(--card);border-radius:6px;padding:3px 6px;border:2px solid var(--neutral);max-width:100%}
.chip small{display:block;color:var(--muted);font-size:10.5px}
.chip.open{border-color:var(--open);font-weight:600}.chip.stretch{border-color:var(--stretch);border-style:double;border-width:3px}
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
    if res["sample"].get("evidence"):
        parts.append(f"<p class=\"meta\">Sample: {esc(res['sample']['evidence'])}</p>")
    for w in res["warnings"]:
        parts.append(f"<div class=\"note\">{esc(w)}</div>")
    # legend
    parts.append("<div class=\"legend\">")
    for st in ("open", "stretch", "upgrade", "crowded", "neutral", "unknown", "blocked"):
        parts.append(f"<span class=\"chip {st}\">{esc(STATUS_LABEL[st])}</span>")
    parts.append("<span class=\"chip rec\">★ Recommended</span></div>")
    parts.append("<div class=\"scale\">Chip colour = saturation of that format: "
                 + "".join(f"<span style=\"background:{heat_colour(s)}\"></span>" for s in (0, 2, 4, 6, 8, 10))
                 + " 0 (open) → 10 (saturated)</div>")
    # map: rows from high premium to low
    parts.append("<div class=\"map\" role=\"table\" aria-label=\"Effort by premium map\">")
    for pb in range(4, -1, -1):
        parts.append(f"<div class=\"ax\">{BUCKET_LABEL[pb]}</div>")
        for eb in range(5):
            cell = g[pb][eb]
            zone = " hi" if pb >= 3 else (" lo" if pb <= 1 else "")
            title = f"Premium {BUCKET_LABEL[pb]}, effort {BUCKET_LABEL[eb]}"
            parts.append(f"<div class=\"cell{zone}\" role=\"cell\" title=\"{esc(title)}\">")
            for r in sorted(cell, key=lambda r: (STATUSES.index(r["status"]), r["name"])):
                rec = (r["format"], r["layout"]) in rec_keys
                sat = "?" if r["saturation"] is None else num(r["saturation"])
                basis = {"observed": "obs", "user": "you", "estimated": "est"}.get(r["basis"], "")
                tip = STATUS_LABEL[r["status"]] + f"; saturation {sat}"
                if r["count"] is not None:
                    tip += f" ({r['count']} of {res['sample'].get('size')})"
                if r["basis"]:
                    tip += f", {r['basis']}"
                if r.get("platform_note"):
                    tip += f"; {r['platform_note']}"
                if r["evidence"]:
                    tip += f". {r['evidence'][:240]}"
                parts.append(f"<span class=\"chip {r['status']}{' rec' if rec else ''}\" title=\"{esc(tip)}\" "
                             f"style=\"background:{heat_colour(r['saturation'])}\">"
                             f"{'★ ' if rec else ''}{esc(r['name'])}<small>sat {esc(sat)} {basis}</small></span>")
            parts.append("</div>")
    parts.append("<div></div>" + "".join(f"<div class=\"ax\">{l}</div>" for l in BUCKET_LABEL))
    parts.append("</div><p class=\"meta\" style=\"text-align:center\">Effort (production cost) →</p>")
    parts.append("<p class=\"meta\">↑ Perceived premium. The shaded top rows (premium 7-10) break out most easily: green chips there "
                 "are the openings. The greyed bottom rows feel low-effort to viewers however empty they look.</p>")
    left = [r for r in res["rows"] if r["status"] == "n/a"]
    if left:
        parts.append("<p class=\"meta\">Left out: " + "; ".join(f"{esc(r['name'])} ({esc(r['reason'])})" for r in left) + ".</p>")
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
        extra = " <span class=\"ev\">replaces a usual post; extra hours only</span>" if k.get("replaces_usual_post") else ""
        parts.append(f"<tr><td class=\"n\">{k['day']}</td><td>{esc(k['name'])} #{k['piece']}{extra}</td><td class=\"n\">{esc(num(k['hours']))}</td></tr>")
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
    if a.test_hours:
        creator["test_hours_per_week"] = a.test_hours
    for cid in creator["current_formats"]:
        if cid not in cat["_formats"]:
            fail(f"--current: unknown format {cid!r}")
    scan = {
        "niche": a.niche,
        "date": dt.date.today().isoformat(),
        "sample": {"size": None, "queries": [], "platforms": a.platforms or [], "evidence": "", "note": ""},
        "creator": creator,
        "overrides": {},
        "entries": [{"format": f["id"], "layout": None, "count": None, "saturation": None,
                     "basis": None, "evidence": "", "applicable": True}
                    for f in cat["formats"] if a.length in f["lengths"]],
    }
    text = json.dumps(scan, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
        out(f"wrote {a.out} with {len(scan['entries'])} entries. Fill in sample.size + count per entry (or saturation), "
            "basis, and sample.evidence; set applicable false (with a reason) for formats that can't fit this niche.")
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
    for w in res["check_warnings"]:
        out(f"scan warning (not shown to the creator): {w}")
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
    s.add_argument("--test-hours", type=float, help="hours per week free for new formats (default: --hours)")
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
