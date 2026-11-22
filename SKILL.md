---
name: formatmap
description: Helps creators decide which content formats to make next in their niche. It maps short- and long-form formats (talking head, green screen, text on B-roll, carousel, POV, tutorial, storytime, faceless explainer, Vox-style collage, screen recording, skit, mini-doc, data visual and more) by production effort and how premium they feel, scans the niche to estimate how saturated each format is, and builds a heat map (HTML + table) that highlights the open cells. It gives premium-upgrade checklists for easy formats and recommends 3-5 formats to test with a 2-week plan sized to the creator's time, including faceless options. Use this whenever someone asks "what content should I make", "what format should I use", "my reels/shorts/TikToks aren't working", "my views dropped", "content strategy for my niche", "what's oversaturated", "how do I stand out", "faceless content ideas", or wants low-effort content to feel more premium, even if they never say "format".
---

# FormatMap

Easy, copy-paste formats flooded every feed, and saturation is making them stop working. The
formats that break out next are the ones that *feel premium* and that *nobody in the niche is filling
well yet*. FormatMap finds those cells for one specific creator: their niche, their time, whether
they show their face.

Four numbers per format:
- **Effort** (1–10, production cost) and **premium** (1–10, how premium it feels to a viewer) come
  from `references/catalogue.json`. They are editable starting ratings, not measurements.
- **Saturation** (0–10, supply) is about this niche and comes from your scan. It's the number to be
  most honest about.
- **Demand** (0–10, optional) is evidence that viewers respond to the format. A gap with no demand
  may be empty for a reason. Unchecked demand is scored as neutral and labelled "not checked".

The judgement (what the niche is full of, what each piece says) is yours. Scoring, the grid, the HTML
heat map, the upgrade checklists and the test-plan sizing go through `scripts/formatmap.py`, so they
are exact and repeatable.

**Running the script:** call it by its full path inside this skill's folder, e.g.
`python "C:/Users/me/.claude/skills/formatmap/scripts/formatmap.py" build scan.json`, from the
user's working folder (outputs go to `./formatmap-out/`). Below, `FM` stands for that command.

| Command | Use it to |
|---|---|
| `FM catalogue [--length short\|long]` / `FM catalogue --layouts` | See format and layout ids with their ratings |
| `FM show ID [ID ...]` | Definition, examples and the premium-upgrade checklist for a format |
| `FM template --niche "..." [--length short] [--faceless] --hours 8 [--max-effort 7] --current ID ... --out scan.json` | Start a scan file with every format for that length |
| `FM check scan.json` | Validate the scan before building |
| `FM build scan.json [--top 4] [--out-dir formatmap-out]` | Score, map, recommend, plan → `formatmap.html` + `formatmap.md` |
| `FM analyse results.json [--scan scan.json --scan-out next.json]` | After the test: judge each format against the creator's own baseline, and learn measured hours into a new scan |
| `FM compare old-scan.json new-scan.json` | What changed in the niche between two scans |

## Steps

### 1. Profile the creator (ask only what you can't see)

You need: the niche (in the audience's words), **short or long form** (if both, run one map each),
platforms (ids like `youtube-shorts`, `tiktok`, `instagram-reels`, `youtube`, `linkedin`: formats
not native to any of them are left out), **hours per week** for content (if their usual posts
already use most of it, set `creator.test_hours_per_week` to what's left for new formats), **face or faceless**, what they make now (map it to format
ids for `--current`), any special skill or setup (a motion designer, a studio, a template library),
and links to their channel or profile if they have one. Read the links if you can: titles and
thumbnails tell you their current formats. Ask at most one short message of questions; default to
6 h/week and "on camera OK" only if they won't say, and state the default.

**"My views dropped"** is often a format problem, but not always. Say in one line that a format map
can't diagnose a drop on its own (platform changes, a change in topic or posting rhythm, one outlier
video), and suggest checking their analytics for where it started (or a channel audit / retention
review skill if one is installed). Then make the map.

If they describe a house style (e.g. "faceless, Paper → Glass: Vox collage for the problem, clean
Apple-like UI for the solution"), add matching **format + layout** entries to the scan (e.g.
`vox-collage` + `paper-to-glass`, `faceless-explainer` + `paper-to-glass`, `product-ui-demo` +
`glass-ui`) so their style is scored like everything else, not assumed to win.

### 2. Scan the niche for saturation

Follow `references/niche-scan.md`. In short: 3–5 audience queries, the top ~20 results per query on
the creator's platform, tally formats, give the script the tally (`sample.size` + `count` per entry)
so saturation is derived, not guessed. Classify each item by the rules in niche-scan.md §3. Use the
tools this session actually has (web search, page fetch, a shell, a YouTube tool, the user's pasted
feed) and say which worked; niche-scan.md lists the routes that tend to fail and one that works.
Put the shared evidence once in `sample.evidence`.

**Before building, mark formats that can't fit this niche** with `"applicable": false` and a
`reason` (niche-scan.md §5). Otherwise every format nobody makes looks "open", including ones that
make no sense here.

Honesty rules, non-negotiable:
- Label every saturation with `basis`: `observed` (you counted it in this session, with evidence),
  `user` (they told you or pasted it), or `estimated` (your general knowledge, with a reason). The
  script rejects observed/user entries without evidence.
- **Never invent view counts, follower counts or engagement numbers.** You don't need them: the
  format tally is the evidence. Quote a number only if you read it on a page in this session.
- If you can't browse, say so, estimate, and ask the user to paste 10–20 titles from their own
  search/For You page for one query to firm it up. Leave a format's saturation null when you
  genuinely can't tell; the map shows it as unknown and never calls it open.
- To nudge a counted saturation, use `"adjust": 1` or `-1` with the reason in `evidence`.
- Record `channels` per entry (distinct channels behind the count) so one prolific channel can't
  make a format look crowded, `confidence: "low"` where classification was hard, and
  `sample.channels` / `sample.unclassified` for the whole sample.
- **Check demand for the formats you're likely to recommend** (niche-scan.md §7): the creator's own
  past posts, outliers in the sample, audience requests, or a close niche. Don't check all 29;
  check the top open cells. Never turn view counts into invented numbers.
- Use `overrides` (with a `reason`) to adjust effort/hours for this creator's real skills. Don't
  raise premium to make a favourite format win.

Then `FM check scan.json` and fix any errors. Warnings from `check` and `build` are for you, not
the creator; they never appear in the report.

### 3. Build the map

`FM build scan.json`. Each entry gets a status:

| Status | Meaning |
|---|---|
| **Open** | Premium ≥ 6, saturation ≤ 4, within the creator's hours and max effort. The targets. |
| **Open, over capacity** | Same, but too slow for their time right now (a later goal, or lower effort via a template) |
| **Easy but crowded: upgrade it** | Effort ≤ 4, saturation ≥ 6. Only works with premium execution |
| **Gap, but no sign viewers want it** | Would be open, but demand evidence is 0–3. Not recommended |
| **Crowded** | Saturation ≥ 7 and not easy |
| **Neutral** | Middle of the map |
| **Unknown** | No saturation data. Never recommended as open |
| **Needs a face** | Creator is faceless and the format requires a face |
| *Left out* | Marked not applicable, not this length, or not native to the creator's platforms |

The table lists actionable rows first (open, then upgrade, then over capacity...), observed before
estimated. In the HTML, each chip is coloured by its own saturation; the shaded top rows (premium
7–10) are the breakout zone, and the greyed bottom rows stay low-premium however empty they are.

Thresholds and weights are in `catalogue.json → scoring`. The HTML is self-contained (no external
requests) and works offline; send the user the `formatmap.html` path and show the markdown table in
chat.

### 4. Premium upgrades for the easy formats

The build includes the upgrade checklist (polish, insight, novelty, detail) for the easy formats the
creator already makes and any "upgrade" format it recommends. Don't just paste it: pick the **two
upgrades that fit this creator's niche best** and make each concrete for them ("show the actual
invoice template on screen" beats "add proof"). Test one upgrade at a time.

### 5. Recommend 3–5 formats and the 2-week test

The script picks the formats and lays out a 2-week calendar. How it picks:
- **First, one easy-but-crowded format to upgrade**, preferring one the creator already makes. An
  upgraded piece replaces a usual post, so it only costs the *extra* hours. If there's no such
  format in the niche, say so: the creator's easy formats aren't crowded yet.
- **Then open cells**, observed before estimated, then by score, as long as one piece of each still
  fits. Formats that fit a full test (2 pieces) come first.
- **Neutral formats only to reach three**, never to pad.
- If fewer formats fit than `--top` asked for, the plan says so; a low-hour creator may get three
  formats with some single pieces (flagged as hints, not verdicts).
 Read `references/test-plan.md`, then for each recommended
format write:
- why it's open in *this* niche (cite the scan evidence),
- the first piece's brief: hook, the one idea, format + layout, 3–5 visual beats, time budget,
- for faceless creators, how it works without a face.

If a strong open format didn't fit the hours, name it as the next step ("with 2 more hours a week,
add data visuals"). If a piece got only one slot, say so plainly. If the user
disagrees with a pick, change the scan (or an override) and rebuild rather than overruling the map in
prose.

### 6. After the test

When the creator comes back with results, follow `references/test-plan.md` → "After 14 days": a
results file with their own baseline, `FM analyse`, then a re-scan and `FM compare`. Never judge a
format on raw views, and say when a piece had too few views to count.

## Output format

```
## Format map: [niche]
[the markdown table from the build, or its top ~12 rows if long]
**Basis:** 14 observed (YouTube Shorts search, 3 queries, 60 results, 22 Nov) · 8 estimated · 4 unknown
Map: formatmap-out/formatmap.html

### Test next
1. **[format + layout]** — why it's open here (evidence). First piece: [brief]
...
### Premium upgrades for your easy formats
- [for each easy format: the 2 upgrades that fit this niche best, made concrete; merge formats whose upgrades overlap]
### 2-week plan
[calendar from the build] · [hours] of [budget] h
### How to judge it
Compare each format with your own last-10-post median: retention and shares+saves per 1,000 views.
```

## Boundaries

- Effort and premium are opinions encoded as data. Say so if the user challenges one, and offer to
  edit it in their scan's `overrides` or a copy of the catalogue (`--catalogue FILE`).
- "Open" means nobody is filling it well yet, not that the audience wants it. The test decides.
- No guarantees of views or growth. No scraping behind logins; never ask for platform passwords.
- The script makes no network requests. Your research uses whatever tools the session provides.
