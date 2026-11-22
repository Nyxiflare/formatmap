# FormatMap: a Claude skill that finds the open content formats in your niche

The lazy, copy-paste formats flooded the feed, and they're starting to stop working. The formats that break out next feel **premium** and **nobody in your niche is filling them well yet**.

FormatMap maps every content format by **effort** (what it costs to make) and **premium** (how premium it feels to a viewer), scans **your niche** to see which formats are already saturated, and shows you the open cells you can fill, within the hours you actually have.

> "I run a faceless channel about AI tools for small business owners. 10 hours a week, Shorts and Reels. I do text-on-B-roll and stock explainers. What should I make next?"

Result for the [illustrative example](examples/ai-tools-faceless/) (made-up tally, to show the output):

| Format | Effort | Premium | Saturation | Status |
|---|---|---|---|---|
| ★ Data visual / animated chart | 6 | 8 | 0 | 🟢 Open |
| ★ Faceless explainer + Paper → Glass | 6 | 7 | 0 | 🟢 Open |
| Vox-style collage explainer | 8 | 9 | 0 | 🟢 Open (10h a piece) |
| Mini-documentary | 9 | 9 | 0 | 🔵 Open, over capacity |
| ★ Text on B-roll | 1 | 2 | 6 | 🟠 Easy but crowded: upgrade it |
| AI image slideshow | 1 | 1 | 5 | ⚪ Neutral |
| Talking head | 2 | 3 | 4 | ⛔ Needs a face |

…plus a **self-contained HTML heat map** (effort × premium, coloured by saturation), a **premium-upgrade checklist** for text-on-B-roll and stock explainers (polish, insight, novelty, detail), and a **2-week test plan** that fits in 18.5 of the 20 hours available.

## What it does

- **Catalogue of 28 formats and 12 visual layouts** (talking head, green screen, text on B-roll, carousel, POV, tutorial, listicle, storytime, faceless explainer, Vox-style collage, screen recording, skit, street interview, mini-doc, data visual, clean UI demo, whiteboard, case study…), each with effort, premium, typical hours, a definition, examples and an upgrade checklist.
- **Format + layout combinations:** e.g. a faceless explainer in a *Paper → Glass* layout (problem in paper collage, solution in clean glass UI) is scored as its own cell.
- **Niche scan:** Claude samples what your audience is shown (search results, competitor channels, your pasted feed), tallies formats, and the script turns the tally into a 0–10 saturation score.
- **Honest about evidence:** every saturation is labelled *observed*, *from you* or *estimated*; observed values need evidence; unknown formats are never called open; and **it never invents view counts**.
- **Sized to you:** hours per week, max effort, faceless or not, short or long form. Face-only formats are blocked for faceless creators.
- **Premium upgrades:** for the easy formats you already make, a concrete polish / insight / novelty / detail checklist, so easy formats keep working.
- **3–5 formats to test** and a 2-week calendar that fits your hours, with honest warnings when it doesn't.
- **Editable ratings:** every rating, threshold and weight lives in [`references/catalogue.json`](references/catalogue.json). Change a number, rebuild the map. Per-creator `overrides` for your real skills.

## Install

```bash
npx skills add Nyxiflare/formatmap
```

Or copy this folder to `~/.claude/skills/formatmap`.

## Use it

Just talk to Claude:

- *"What content should I make? I'm a faceless finance channel, 6 hours a week."*
- *"My reels aren't working anymore. Here's my profile: …"*
- *"Map the formats in the home-coffee niche on TikTok."*
- *"How do I make my talking-head videos feel more premium?"*

You get `formatmap-out/formatmap.html` (open it in any browser, works offline) and the same map as a table in chat.

## Known limitations

- **Effort and premium are judgement, written down as data.** They're a reasonable default for a solo creator, not measurements. Edit them if your experience differs.
- **Saturation is only as good as the sample.** Search results are personalised and change daily; Claude can't see inside TikTok or Instagram without the tools to do so. When most values are estimated, the map says it's a hypothesis.
- "Open" means nobody is filling it well yet, not proof the audience wants it. The 2-week test is what tells you.
- Format recognition from titles and thumbnails is Claude's call and can be wrong for edge cases.
- No guarantees of views or growth.

## Requirements

- Claude Code (or any agent that supports skills)
- Python 3.9+ (standard library only). The script makes no network requests.

## Tests

```bash
python -m unittest discover -s tests
```

## License

MIT. See [LICENSE](LICENSE). Free to use, change and share.
