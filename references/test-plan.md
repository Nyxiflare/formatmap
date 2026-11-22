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

## After 14 days: feed the results back

Have the creator fill in a results file from their own analytics (see
`examples/ai-tools-faceless/results.json`): a `baseline` (median retention % and shares+saves per
1,000 views over their last ~10 posts on that platform) and one entry per test piece with `format`,
`layout`, `hours`, `views`, `retention`, `shares`, `saves`. Then:

```
FM analyse results.json --scan scan.json --scan-out scan-next.json
```

It judges each format against the baseline, never on raw views:

| Verdict | Rule |
|---|---|
| Keep | ≥2 pieces, every judged piece beat the baseline on retention *and* shares+saves per 1,000 |
| Promising | Only one judged piece, and it beat both: make one more |
| Iterate | Beat the baseline on one signal: try the next premium upgrade from its checklist |
| Drop | Lost on both |
| Too few views | Under 200 views (`scoring.min_views_to_judge`): not judged |

It also shows **shares+saves per production hour**, the return on effort. With `--scan`, it writes a
*new* scan where measured hours become `overrides` and kept formats join `current_formats`. Re-scan
the niche (saturation moves too), build again, and use `FM compare old.json new.json` to see what
changed. Before calling a winner, check it didn't win on its topic alone.

## Piece briefs

For each planned piece in the script's calendar, write a short brief:

- **Hook (first line / first frame)**
- **The one idea**
- **Format + layout** (and for easy formats, which upgrade from the checklist is being tested)
- **Visual plan in 3–5 beats**
- **Time budget** (from the plan)

Faceless creators: every brief must be makeable without showing a face. Use voiceover, hands, screen,
collage, UI, data or text.
