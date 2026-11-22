# Running the 2-week format test

The script sizes the test (how many pieces of each format fit the creator's hours, and on which days).
Your job is the content of each piece and how the creator reads the results.

## Rules for a fair test

1. **Same topic family, different formats.** Keep the subject close across formats so the format is
   what changes. Best: the same core idea made in two formats.
2. **At least 2 pieces per format.** One post is noise. The script plans 2 by default
   (`scoring.test_pieces_per_format`) and warns when the hours don't allow it.
3. **One premium upgrade at a time** on the easy formats, so the creator learns which upgrade moved
   the numbers.
4. **Same posting times and platform** across the test.
5. **Compare against the creator's own baseline**, never against other creators' numbers: the median
   of their last 10 posts on the same platform.

## What to measure (the creator reads these in their own analytics)

| Signal | Why it matters for format |
|---|---|
| Average % viewed / retention | Does the format hold attention? |
| Swipe-away / "viewed vs swiped" (Shorts), first-3-second hold (Reels/TikTok) | Does the opening of this format stop the scroll? |
| Shares and saves per 1,000 views | Premium content gets saved and sent |
| Follows per 1,000 views | Does the format make people want more? |
| Hours spent per piece | The real effort cost for this creator |

Don't judge by raw views on 2 posts. A format "wins" when it beats the baseline on retention *and* on
shares/saves per 1,000 views in both pieces.

## After 14 days

- Keep the 1–2 formats that beat the baseline and cost a sustainable number of hours.
- Drop formats that lost on both signals.
- For a format that was close, try the next premium upgrade from its checklist before dropping it.
- Update the scan file (`current_formats`, `overrides.hours` with real hours) and re-run `build`:
  the map gets more accurate each cycle.

## Piece briefs

For each planned piece in the script's calendar, write a short brief:

- **Hook (first line / first frame)**
- **The one idea**
- **Format + layout** (and for easy formats, which upgrade from the checklist is being tested)
- **Visual plan in 3–5 beats**
- **Time budget** (from the plan)

Faceless creators: every brief must be makeable without showing a face. Use voiceover, hands, screen,
collage, UI, data or text.
