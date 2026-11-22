# Niche scan: how to estimate saturation honestly

Saturation is the only number in FormatMap that is about *this* niche. Effort and premium come from
`catalogue.json`. Get saturation from what you can actually see, and label every number with where
it came from.

## 1. Define the niche in search terms

Write 3–5 queries the audience would type or that the platform would group together, e.g. for
"personal finance for students": `student budgeting`, `how to save money in college`,
`student loan explained`, `first credit card`. Use the creator's own titles and the words in their
bio as a starting point.

## 2. Sample what the audience is shown

**One map per platform** when the creator's platforms differ a lot (TikTok vs YouTube long-form).
For Shorts + TikTok + Reels one map is fine, but say which platforms you actually sampled. A
platform you couldn't observe is a gap to name, not something to fill from memory.

Try these, and say in `sample.evidence` which ones worked:

1. **The creator's own links.** Their channel/profile and recent titles tell you their
   `current_formats`, not saturation. A new or private channel may return nothing; say so.
2. **YouTube search results.** In tests, plain web search often **ignores `site:` filters**, and a
   page-fetch tool usually gets only the footer of a YouTube results page because the page is built
   by JavaScript. What works when you have a shell with network access: download the public,
   logged-out results page (`https://www.youtube.com/results?search_query=...`) and read the
   `ytInitialData` JSON embedded in it for titles, channel names and thumbnail URLs. Shorts appear
   as `shortsLockupViewModel` / `reelItemRenderer` objects; regular videos as `videoRenderer`. Thumbnails (`https://i.ytimg.com/vi/<id>/hqdefault.jpg`) can be downloaded and
   viewed to classify the format. Public pages only, a handful of requests, no logins.
3. **TikTok / Instagram.** Fetching usually fails (refused or login wall). Use search snippets if
   they appear; otherwise ask the user.
4. **Competitor channels** the user names: their last ~10 uploads.
5. **What the user pastes.** Ask for 10–20 titles or links (or screenshots) from their own
   search / For You page for one query. That is real observation (`basis: "user"`) and beats memory.

Aim for the **top ~20 results per query**, 40–100 unique items in total (drop duplicates across
queries).

## 3. Classify each item into one format

Pick the format that **carries the content**, using title + thumbnail at minimum:

| If… | Format |
|---|---|
| Steps shown in order so the viewer can do it | `tutorial` (or `screen-recording` on a screen) |
| Hands making/fixing something, little or no explanation, the sound/visual is the point | `process-asmr` |
| A caption or one line of text is the whole message, footage is mood or generic | `text-on-broll` |
| Judging, comparing or recommending products/options | `review-comparison` |
| Numbered items ("5 tools…") | `listicle`, even if each item is filmed as a tutorial |
| Someone talking to camera is the main thing | `talking-head` (over a background image: `green-screen`) |
| Telling what happened, personal or true | `storytime` |
| Before and after of the same thing | `before-after` |

Captions on top of a tutorial don't make it `text-on-broll`; note "caption-heavy" as a layout if it
matters. Items that fit no format: keep them in `sample.size`, leave them unassigned, and say how many
in `sample.note`. Title + thumbnail is enough for `observed`; say if you watched any.

## 4. Turn the tally into saturation

Give the script the tally and it derives saturation from the share of the sample: set
`sample.size` (the number of unique items) once and `count` per entry. The bands live in
`catalogue.json → scoring.saturation_bands`:

| Share of sample | Saturation |
|---|---|
| 0% | 0 |
| up to 3% | 1 |
| up to 6% | 2 |
| up to 10% | 3 |
| up to 15% | 4 |
| up to 20% | 5 |
| up to 27% | 6 |
| up to 35% | 7 |
| up to 45% | 8 |
| up to 60% | 9 |
| over 60% | 10 |

To nudge a tally-based number, add `"adjust": 1` (items in that format all look the same) or
`"adjust": -1` (they're all poor quality), and say why in `evidence`. Never more than ±1.

When you have no tally, set `"saturation"` directly (0–10) with `"basis": "estimated"` and a one-line
reason.

## 5. Mark formats that don't belong in this niche

A count of 0 means "nobody does this here", which is only an opening if the format *could* work for
this audience. Before building, go through the zero-count formats and mark the ones that can't fit
(a clean software-UI demo for an espresso channel, street interviews for a private-medical niche):

```json
{"format": "product-ui-demo", "applicable": false, "reason": "no software in this niche"}
```

They are left out of the map and listed under "Left out". Also be cautious with zero counts for
long-production formats (mini-doc, Vox collage, cinematic essay) in short-form search: they rarely
surface there even when they exist. Leave them in, but say so when you recommend one.

## 6. Label the basis on every entry

| `basis` | Use when | Required |
|---|---|---|
| `observed` | You counted it in a sample you actually looked at in this session | evidence: which queries, platform, how many results, date. Put it once in `sample.evidence`; add per-entry `evidence` only for something specific (an `adjust` reason) |
| `user` | The user told you, or pasted the sample | evidence saying so (shared or per entry) |
| `estimated` | General knowledge of the niche, no sample | a one-line reason |
| *(no saturation)* | You genuinely can't tell | leave `saturation` null: the map shows it as unknown and never marks it open |

The script refuses `observed` or `user` entries without evidence.

## Honesty rules

- **Never invent view counts, follower counts, upload frequencies or engagement rates.** Only quote a
  number you read on a page in this session, and say where. Usually you won't need any: the
  tally of formats is the evidence.
- Say in the report how many entries are observed vs. estimated (the script prints this). If most
  are estimated, say plainly that the map is a hypothesis to check against the user's own feed.
- Search results are personalised and change daily. Date the sample.
- A format being rare does not prove demand. "Open" means *nobody is filling it well*. The 2-week
  test is what proves whether the audience wants it.
- Don't scrape behind logins, and don't ask the user for passwords to platforms.

## Per-creator overrides

Effort and premium in the catalogue assume a typical solo creator. If this creator is unusually fast
at something (a motion designer, a trained editor) or has a ready setup (a studio, a template
library), lower that format's `effort`/`hours` in the scan file's `overrides`, and say why. Don't
raise `premium` to make a favourite format win.
