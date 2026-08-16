# CLAUDE.md — Fantasy Football Assistant

Reference for any Claude Code session working in this repo. This is a living summary of the current design — for the reasoning and history behind each decision, see DECISIONS.md.

## Project purpose

A personal tool to manage fantasy football teams across 10 leagues and 3 platforms (ESPN, Yahoo, Sleeper), each with different sizes and scoring systems. Built and documented publicly as part of an active job-seeking portfolio, alongside this GitHub repo.

## Confidentiality rule — read before touching rankings code

The rankings data source must never be named in anything committed to this public repo: no code, comments, docs, README/DECISIONS content, or commit messages. Refer to it generically ("the rankings provider," "rankings source"). Actual source URLs and any provider-specific handling belong only in a local, gitignored config file — never committed. This is a personal preference about not tipping off fantasy competitors, not a technical constraint, so it's fine to discuss the real source by name in local notes or chat — just keep it out of anything that gets pushed.

## Scope boundary — advisory only, no write-back to platforms

This tool surfaces suggestions (waiver targets, lineup swaps) but never executes anything on Keith's behalf. He makes every add/drop, lineup change, and draft pick directly in ESPN/Yahoo/Sleeper (or via the local draft board for picks). This means platform connectors only ever need **read** access — rosters, league settings, waiver priority, matchups. No transactional/write API calls anywhere in this project. Keep this in mind when scoping any connector work: if a feature seems to require writing back to a platform, that's a sign it's out of scope.

## Core architecture

- **Storage:** single SQLite database as source of truth — league settings/scoring, canonical players + per-platform name aliases, rankings (draft/weekly/ROS), rosters/transactions/waiver priority, matchup history. A single-file DB was chosen partly because it's trivial to sync between machines.
- **Player-name matching:** deterministic/rules-based (exact match → suffix-normalized match → manual override table), not LLM-based. Keeps things fast and token-light — don't reach for a model call to reconcile player names.
- **Stack:** Python for backend, data pipelines, and platform connectors (ESPN/Yahoo/Sleeper). Lightweight JS frontend for the draft board and any dashboards — live filtering/searching during a draft needs snappier interactivity than server-rendered pages.
- **Draft-day access:** runs as a local app, not hosted. The database file is synced by hand between machines — desktop is the always-on host for scheduled in-season pulls, laptop is on-demand/draft-day only, working from last-synced data.
- **In-season automation:** hybrid — scheduled routine pulls (rankings/rosters) on the desktop, with on-demand refresh always available. Weekly matchup results (PF/PA/outcome) are filled in by hand today but are a good future automation candidate via the same read-only connectors, once built — historical years (2013 onward) stay a one-time spreadsheet import regardless, since platforms don't expose that retroactively.

## App-level navigation

Five peer sections, not nested inside each other: **Draft | In-season | Exposure | League settings | W-L**.

- **League settings** is the shared config (league name, platform, scoring, team count, roster construction/starters-per-position, rounds) that Draft, In-season, and W-L all read from — one source, not per-module copies. Low-frequency section (setup/edit), not a daily-use view. Formalizes the legacy "Settings" sheet's role.
- **Exposure** (player/team concentration across all 10 leagues) is cross-league by design — no league or year selector. Matters year-round (post-draft trades/waivers too), not just during drafts, which is why it isn't nested inside Draft. Not yet designed in detail beyond this scoping.
- **Draft** and **In-season** are scoped per-league via a shared league selector (see below). **W-L** is scoped per-year via a year selector instead, since its views span all leagues at once.

## Draft tool design (most detailed piece so far)

**Navigation:** one global league selector sits above the tab bar and applies across all three tabs below (switching tabs doesn't reset the league). Tabs: Draft | Grid | Rosters.

**Pick entry is order-driven, not team-selected.** Snake order is known from league settings, so the tool tracks "on the clock" automatically — entering a pick means typing the player name and confirming, not choosing a team. An undo/edit-pick control handles corrections. This is the required baseline for every league (drafts are a mix of live in-platform and not), so it must always work without depending on any platform API. Live auto-poll from a platform's draft room is a possible future enhancement only — feasibility per platform (ESPN/Yahoo/Sleeper) is unverified, don't design around it.

**Draft tab:** rank list columns in this order: Rank, Player, Position. Position color-coding: QB green, RB blue, WR red, TE pink, DST amber, K purple. Also shows tier breaks, a round-value chip (rank vs. round-equivalent, `ceil(rank / team_count)`, to flag steals/reaches for your own picks and league-wide position-run pace generally), and a playoff strength-of-schedule tag. Right-hand rail (collapsible sections): your roster (with bye weeks shown inline), a team-by-position matrix with a "safe to wait / run risk" signal — this requires tracking every team's roster-in-progress during the draft, not just yours, since the signal depends on whether teams picking before your next turn still need a given position — and an ADP lookahead: roughly the next 10-20 players sorted by ADP ascending, with your rank shown alongside so you can compare directly rather than the tool computing a probability for you.

**Grid tab:** the full team x round draft board. Any cell is click-to-edit for after-the-fact corrections. Scales to the full team count (up to 18) via horizontal scroll, not compression. Includes a position-count summary block below the round grid (one row per position — QB/RB/WR/TE/DST/K — one column per team), highlighted once a team's count clears that position's starter requirement (from league settings) — carried forward directly from the legacy spreadsheet's conditional formatting.

**Rosters tab:** one card per team (not position-sectioned tables), horizontally scrollable across teams. Each card stacks QB/RB/WR/TE, showing that team's relative rank at the position across the league plus its actual rostered players — starters first, bench shown dimmed below (no text label).

## In-season tool design

Built around Keith's actual weekly routine: Tuesday night waiver prep (before the rankings provider's weekly refresh, so more subjective), Wednesday night once both rest-of-season and weekly rankings are out (waiver targets + set lineups), then Thursday/Sunday-morning/Monday re-checks before each slate locks.

**Two views**, same league-selector convention as Draft, mirroring the legacy "Weekly Rank Eval" tab: **Weekly** (Rostered | Available) and **Rest-of-season** (Rostered | Available), grouped by position. Weekly needs QB/RB/WR/TE/DST/K — Keith streams DST and K frequently based on matchups. ROS stays QB/RB/WR/TE only; DST/K aren't rest-of-season assets.

**No separate lineup-setting or diff screen.** Thursday/Sunday/Monday re-checks reuse the same Weekly view, just reopened with refreshed data — the Weekly view already is the lineup tool, since Keith sets the actual lineup in the platform itself.

**List behavior:**
- "Worst rostered players" sorts by raw rank, worst first — no extra tie-breaking needed.
- Unranked players (injured/suspended that week) must still appear, flagged by status rather than dropped. Needs a player-status field per roster spot — likely from platform roster data, not the rankings provider; unverified which platforms expose this cleanly, check during connector build.
- The "Available" list is never gated by whether it beats the roster — always shows the best-ranked available options, useful for depth/bye visibility even when nothing there is actually an upgrade.
- A visual indicator highlights when an available player's rank beats one of the lowest-ranked rostered players at that position (unranked/injured rostered players count as automatically beaten).
- Swap-candidate judgment calls are shown as plain side-by-side numbers, not a computed threshold — same philosophy as the draft tool's ADP lookahead.

**Tuesday prep** cross-references the rankings provider's separate "Waiver Wire" suggestion content (a written recommendation list, distinct from its numeric rankings tables) against what's actually available/unrostered in each league. This means rankings ingestion needs to handle at least two content types: numeric tables and editorial suggestion lists.

## Win/loss tracking design

Based on the legacy W-L 2025.xlsx (13 years of history back to 2013). Year-scoped views use a **year picker**, not the league selector, since they span all leagues at once.

**Four year-scoped views:**
1. **Games** — one card per league (not a combined table), each showing weeks 1-17 as rows (outcome, PF, PA, differential) plus a total row at the bottom. Horizontally scrollable across leagues — same per-entity-card pattern as the draft tool's Grid and Rosters tabs.
2. **Weekly** — aggregate across all leagues combined: net games-above-even for that week, plus a running cumulative total through the season.
3. **Leagues** — one row per league for the year: W/L/T, buy-in, max possible payout, actual payout, finishing position.
4. **Close games** — wins and losses with a margin under 6 points (fixed threshold, Keith's specific number), showing league, week, and margin.

**One all-years rollup**, per league: W/L/T, win percentage, years played, 1st/2nd/3rd-place finish counts, points for, points against. PF/PA are a real gap-fill — the legacy "All Years" sheet had those columns but never populated them.

## Known technical debt / must-handle-before-building

- The legacy `espnsecrets.py` has live ESPN session credentials (SWID + espn_s2) hardcoded in plaintext. Must be rotated and moved to a local, gitignored secrets store (or env vars) before any ESPN connector code is written. Never commit credentials of any kind.
- Live draft-polling feasibility per platform is unverified — treat as a separate investigation, not a dependency for the core draft tool.
- Player injury/status field availability per platform (needed for the in-season "worst players" flagging) is unverified — check during connector build.

## Year-over-year maintenance checklist

Almost every module above has some yearly-refresh dependency baked into its design. Run through this before each new NFL season (and update it as the actual build reveals more of these than are listed here today):

- **Credentials & config:** rotate/refresh ESPN SWID + espn_s2 session cookies (they expire) in the local secrets store. Re-verify per-platform league IDs in the local config — some platforms reissue a new league ID on renewal, others keep the same one across years. Confirm the rankings provider's URLs in the local gitignored config still resolve for the new season; provider URL patterns can shift year to year even when the provider itself doesn't.
- **League settings:** re-confirm each of the 10 leagues' team count, scoring rules, roster construction/starters-per-position, and draft rounds against the platform for the new season — any of these can change year to year even for a "same" league. Re-confirm draft order/keeper rules per league where applicable.
- **Player data:** refresh the canonical player table with new rookies and reconcile retired/departed players. Expect new manual-override entries in the name-matching table — rookies are the most common source. Refresh bye weeks and playoff strength-of-schedule inputs from the new NFL schedule (feeds the draft tool's SOS tag and in-season prep).
- **Draft tool:** pull the new season's ADP data before draft day (feeds the ADP lookahead panel) and ingest the new season's draft rankings from the rankings provider. Confirm how each league's prior Draft/Grid/Rosters data is handled for the new draft (archived vs. overwritten) once that persistence behavior is actually built.
- **In-season tool:** no standing yearly action beyond the rankings-ingestion refresh above — Weekly/ROS views read whatever season is current by definition.
- **Exposure:** once built, confirm it recomputes cleanly off the new season's rosters post-draft — keeper leagues may carry some exposure over from the prior year, worth a specific check.
- **W-L tracker:** add the new year to the year picker and create its "Games" card per league once week 1 results exist. PF/PA entry stays manual until the in-season automation candidate mentioned above is built.

## Suggested build order

Draft is the most time-sensitive (drafts happen in August) and the most fully specified, so it's the priority. Roughly:

1. Data model / SQLite schema (league settings, players + aliases, rankings, rosters, matchups) + rotate/move the ESPN credentials out of plaintext first.
2. Player-name matching pipeline (exact → suffix-normalized → manual override).
3. Platform connectors (ESPN/Yahoo/Sleeper), read-only.
4. Rankings ingestion (generic "rankings provider" interface; real URLs in a local gitignored config), handling both numeric tables and the editorial waiver-suggestion content type.
5. Draft tool (Draft/Grid/Rosters tabs).
6. In-season tool (Weekly/ROS views).
7. League settings admin.
8. Exposure and W-L tracker (least time-pressured, can trail the rest).

## Session workflow

- Keith closes the window without a sign-off, so there's no reliable "session end" signal to wait for. Instead, update proactively at natural checkpoints — right after a real decision is made or a chunk of work is completed, not deferred to a session boundary that may never come. Update the row for "Keith's FF Assistant" in the Notion database "Project Status Tracker": set Last Updated to today, append one line to Recent Progress (don't rewrite the whole log — keep only the latest 2-3 entries), and revise Open Tasks to reflect what's actually still outstanding. Skip this for purely exploratory work with no decisions or completed changes.

## Where to look for more

- `DECISIONS.md` — full chronological log of every decision above, with context, rationale, and alternatives considered. Written in portfolio-readable style since it doubles as a work sample.
- `README.md` — project overview for external readers.
