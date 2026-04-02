---
date: 2026-04-02
topic: new-pick-sources
---

# New Expert Pick Sources: NFL.com + PFT

## Problem Frame

The leaderboard currently relies on two pick sources: ESPN (11 consistent experts) and Fantasy Nerds (24 experts with inconsistent weekly coverage). Fantasy Nerds experts don't all appear every week, making it unfair to compare someone who picked 18 weeks against someone who picked 4. We need additional sources with consistent weekly coverage to make the leaderboard more credible.

## Research Summary

We evaluated 11 potential sources. Most were eliminated:
- **NFLPickWatch**: Clean JSON API exists but is fully paywalled — all 228 experts locked (names, affiliations, results). Verified via direct API testing across multiple seasons.
- **CBS Sports, Bleacher Report, Covers.com**: JS-heavy SPAs requiring headless browser.
- **Yahoo, Fox Sports**: No stable expert panel or ATS-only.
- **The Athletic, Action Network**: Paywalled.

Two sources passed testing with `urllib.request`:

**NFL.com** — 5 editors pick every game every week via HTML tables.
- URL: `nfl.com/news/nfl-picks-week-{N}-{YEAR}-nfl-season`
- Experts: Ali Bhanpuri, Brooke Cersosimo, Dan Parr, Gennaro Filice, Tom Blair
- Format: Server-rendered HTML. One `<table>` per game. First row = expert first names. Second row = picks as "Team Score-Score" (e.g., "Eagles 27-20"). First table on page is a season standings summary, not picks.
- Verified weeks 1 and 10 of 2025. Consistent structure.

**NBC/ProFootballTalk** — 2 analysts pick every game every week in narrative text.
- URL: `nbcsports.com/nfl/profootballtalk/rumor-mill/news/pfts-week-{N}-{YEAR}-nfl-picks-florio-vs-simms`
- Experts: Mike Florio, Chris Simms
- Format: Server-rendered HTML. Each pick is a line: `Florio's pick: Eagles 30, Cowboys 17.` Regex-trivial parsing.
- Verified week 1 of 2025.

## Requirements

**NFL.com Scraper**

- R1. Scrape expert picks from NFL.com's weekly picks article. Parse the HTML tables to extract each expert's pick (winning team) for each game.
- R2. Map NFL.com team names (e.g., "Eagles", "49ers") to nflverse abbreviations via `normalize_team()` or a team name lookup.
- R3. Store picks in `data/picks/{season}/week-{week}-nfl.json` using the existing pick file schema.

**PFT Scraper**

- R4. Scrape expert picks from PFT's weekly picks article. Parse the "Florio's pick: Team Score, Team Score" lines.
- R5. Map PFT team names to nflverse abbreviations.
- R6. Store picks in `data/picks/{season}/week-{week}-pft.json` using the existing pick file schema.

**Game Identification**

- R7. Both scrapers need to match parsed picks to canonical game IDs (`{season}_{week:02d}_{away}_{home}`). This requires resolving team names to the nflverse schedule to determine away/home ordering. The Fantasy Nerds scraper already does this — reuse the same approach.

**Scorer Integration**

- R8. Add NFL.com and PFT as additional sources in `score_experts.py`. Load their pick files alongside ESPN and Fantasy Nerds. The existing `(expert, game_id)` deduplication handles any overlaps.

**Leaderboard Participation Flagging**

- R9. Add a `qualified` boolean field to each expert's leaderboard entry.
- R10. Experts who picked fewer than 50% of scored weeks are flagged `qualified: false`. "Scored weeks" = the number of weeks with results files, not the full season length.
- R11. All experts appear in the leaderboard regardless of qualification.

**Operational**

- R12. Use `urllib.request` only (consistent with existing scrapers).
- R13. Accept `--season` and `--week` arguments matching the existing scraper CLI pattern.

## Success Criteria

- Leaderboard grows from ~35 experts to ~42 (7 new: 5 NFL.com + 2 PFT), all with full-season coverage
- NFL.com and PFT experts appear every scored week (no participation gaps)
- Existing ESPN picks and scoring are unaffected

## Scope Boundaries

- No changes to the ESPN or Fantasy Nerds scrapers
- No UI or visualization work — leaderboard remains a JSON file
- No ATS picks from these sources (existing ATS scoring uses Vegas lines from results data)
- No NFLPickWatch integration (API is fully paywalled)

## Key Decisions

- **NFL.com + PFT over aggregators**: Aggregators (PickWatch, Fantasy Nerds) have inconsistent per-expert coverage. Individual outlet sources with fixed panels guarantee full-season consistency.
- **Two separate scrapers, not one**: NFL.com and PFT have completely different page structures (HTML tables vs narrative text). Separate scripts are simpler than a multi-format scraper.
- **Team name resolution via schedule lookup**: Both sources use display names ("Eagles") not abbreviations. Reuse the Fantasy Nerds approach of looking up teams in the nflverse schedule to get canonical game IDs.
- **Flag low participation rather than exclude**: All experts appear with a `qualified` field. Consumers decide how to filter.
- **50% threshold for qualification**: Roughly half the season — generous enough for minor gaps, strict enough to exclude someone who picked 3 out of 18 weeks.

## Dependencies / Assumptions

- NFL.com continues publishing picks at the predictable URL pattern and maintains the HTML table structure
- PFT continues the "Florio vs. Simms" format with the consistent "X's pick: Team Score, Team Score" pattern
- Neither source requires authentication or blocks `urllib.request` with a standard User-Agent

## Outstanding Questions

### Deferred to Planning

- [Affects R2, R5][Technical] What's the full mapping from display team names ("49ers", "Commanders") to nflverse abbreviations? The existing `normalize_team()` handles abbreviation variants but not display names. May need a display-name-to-abbrev lookup, or resolve via nflverse schedule team fields.
- [Affects R7][Technical] The Fantasy Nerds scraper resolves game IDs by matching teams against the nflverse schedule. Confirm this approach works cleanly for NFL.com and PFT team name formats.
- [Affects R4][Needs research] Does the PFT URL pattern stay consistent across all 18 weeks? Verify with a few more weeks. The slug may vary (e.g., playoff weeks).
- [Affects R1][Needs research] NFL.com's first table is a season standings summary. Confirm this is always the case (not just for weeks 1 and 10) so the scraper can reliably skip it.

## Next Steps

-> `/ce:plan` for structured implementation planning
