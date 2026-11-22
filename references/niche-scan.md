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

Use whatever tools this session has, in this order:

1. **The creator's own links.** Read their channel/profile pages and recent titles. This tells you
   which formats they already make (their `current_formats`) — not saturation.
2. **YouTube search** (web search with `site:youtube.com`, a fetch of the results page, or a
   YouTube tool if one is connected). Shorts and long-form separately if the creator does both.
3. **Web search** for TikTok/Instagram results (`site:tiktok.com <query>`, `site:instagram.com/reel <query>`).
   These platforms often block fetching; use what search snippets show and say so.
4. **Competitor channels** the user names: their last ~10 uploads.
5. **What the user pastes.** If you can't browse, ask the user to paste 10–20 titles or links from
   their For You / search page for one query. That is real observation and better than your memory.

Look at the **top ~20 results per query**, 40–100 items in total. For each item, decide the format
(and layout if it's clear) from the title, thumbnail description, snippet or the video itself.
Tally them.

## 3. Turn the tally into saturation

Give the script the tally and it derives saturation from the share of the sample: in the scan file,
set `"sample_size"` once and `"count"` per entry. The bands live in `catalogue.json → scoring.saturation_bands`:

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

When you have no tally, set `"saturation"` directly (0–10) with `"basis": "estimated"` and one line
of reasoning. Adjust a tally-based number by at most 1 when the items in that format all look the
same (raise it) or are all poor quality (lower it), and say why in `evidence`.

## 4. Label the basis on every entry

| `basis` | Use when | Required |
|---|---|---|
| `observed` | You counted it in a sample you actually looked at in this session | `evidence` naming the queries and sample, e.g. "9 of 40 top results for 'student budgeting' + 'save money college' (YouTube Shorts, 22 Nov 2026)" |
| `user` | The user told you, or pasted the sample | `evidence` saying so |
| `estimated` | General knowledge of the niche, no sample | a one-line reason |
| *(no saturation)* | You genuinely can't tell | leave `saturation` null: the map shows it as unknown and never marks it open |

The script refuses `observed` or `user` entries without evidence.

## Honesty rules

- **Never invent view counts, follower counts, upload frequencies or engagement rates.** Only quote a
  number you read on a page in this session, and say where. Most of the time you won't need any:
  the tally of formats is the evidence.
- Say in the report how many entries are observed vs. estimated (the script prints this). If most
  are estimated, say plainly that the map is a hypothesis to check against the user's own feed.
- Search results are personalised and change daily. Date the sample.
- A format being rare does not prove demand. "Open" means *nobody is filling it well* — the 2-week
  test is what proves whether the audience wants it.
- Don't scrape behind logins, and don't ask the user for passwords to platforms.

## Per-creator overrides

Effort and premium in the catalogue assume a typical solo creator. If this creator is unusually fast
at something (a motion designer, a trained editor) or has a ready setup (a studio, a template
library), lower that format's `effort`/`hours` in the scan file's `overrides`, and say why. Don't
raise `premium` to make a favourite format win.
