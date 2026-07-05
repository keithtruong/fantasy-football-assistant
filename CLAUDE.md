# CLAUDE.md — Fantasy Football Assistant

Reference for any Claude Code session working in this repo. This is a living summary of the current design — for the reasoning and history behind each decision, see DECISIONS.md.

## Project purpose

A personal tool to manage fantasy football teams across 10 leagues and 3 platforms (ESPN, Yahoo, Sleeper), each with different sizes and scoring systems. Built and documented publicly as part of an active job-seeking portfolio, alongside this GitHub repo.

## Confidentiality rule — read before touching rankings code

The rankings data source must never be named in anything committed to this public repo: no code, comments, docs, README/DECISIONS content, or commit messages. Refer to it generically ("the rankings provider," "rankings source"). Actual source URLs and any provider-specific handling belong only in a local, gitignored config file — never committed. This is a personal preference about not tipping off fantasy competitors, not a technical constraint, so it's fine to discuss the real source by name in local notes or chat — just keep it out of anything that gets pushed.

## Scope: three core functions

1. Draft/post-draft analysis — live draft tool, most fully designed so far (see below).
2. In-season management — rankings + roster/waiver data → start/sit and waiver suggestions. Not yet designed in detail.
3. Win/loss tracking — historical record (13 years of data exists) of W/L, PF/PA, buy-ins/payouts, with visualization. Not yet designed in detail.

## Core architecture

- **Storage:** single SQLite database as source of truth — league settings/scoring, canonical players + per-platform name aliases, rankings (draft/weekly/ROS), rosters/transactions/waiver priority, matchup history. A single-file DB was chosen partly because it's trivial to sync between machines.
- **Player-name matching:** deterministic/rules-based (exact match → suffix-normalized match → manual override table), not LLM-based. Keeps things fast and token-light — don't reach for a model call to reconcile player names.
- **Stack:** Python for backend, data pipelines, and platform connectors (ESPN/Yahoo/Sleeper). Lightweight JS frontend for the draft board and any dashboards — live filtering/searching during a draft needs snappier interactivity than server-rendered pages.
- **Draft-day access:** runs as a local app, not hosted. The database file is synced by hand between machines — desktop is the always-on host for scheduled in-season pulls, laptop is on-demand/draft-day only, working from last-synced data.
- **In-season automation:** hybrid — scheduled routine pulls (rankings/rosters) on the desktop, with on-demand refresh always available.

## Draft tool design (most detailed piece so far)

**Navigation:** one global league selector sits above the tab bar and applies across all three tabs below (switching tabs doesn't reset the league). Tabs: Draft | Grid | Rosters.

**Pick entry is order-driven, not team-selected.** Snake order is known from league settings, so the tool tracks "on the clock" automatically — entering a pick means typing the player name and confirming, not choosing a team. An undo/edit-pick control handles corrections. This is the required baseline for every league (drafts are a mix of live in-platform and not), so it must always work without depending on any platform API. Live auto-poll from a platform's draft room is a possible future enhancement only — feasibility per platform (ESPN/Yahoo/Sleeper) is unverified, don't design around it.

**Draft tab:** rank list columns in this order: Rank, Player, Position. Position color-coding: QB green, RB blue, WR red, TE pink, DST amber, K purple. Also shows tier breaks, a round-value chip (rank vs. round-equivalent, `ceil(rank / team_count)`, to flag steals/reaches for your own picks and league-wide position-run pace generally), and a playoff strength-of-schedule tag. Right-hand rail (collapsible sections): your roster (with bye weeks shown inline), a team-by-position matrix with a "safe to wait / run risk" signal — this requires tracking every team's roster-in-progress during the draft, not just yours, since the signal depends on whether teams picking before your next turn still need a given position — and an ADP lookahead: roughly the next 10 players sorted by ADP ascending, with your rank shown alongside so you can compare directly rather than the tool computing a probability for you.

**Grid tab:** the full team x round draft board. Any cell is click-to-edit for after-the-fact corrections. Scales to the full team count (up to 18) via horizontal scroll, not compression. Includes a position-count summary block below the round grid (one row per position — QB/RB/WR/TE/DST/K — one column per team), highlighted once a team's count clears that position's starter requirement (from league settings) — carried forward directly from the legacy spreadsheet's conditional formatting.

**Rosters tab:** one card per team (not position-sectioned tables), horizontally scrollable across teams. Each card stacks QB/RB/WR/TE, showing that team's relative rank at the position across the league plus its actual rostered players — starters first, bench shown dimmed below (no text label).

**Exposure** (player/team concentration across all 10 leagues) lives at the app level, not nested inside the draft tool — it matters just as much in-season after trades/waivers, so it's a shared, year-round view alongside Draft and In-season.

## Known technical debt / must-handle-before-building

- The legacy `espnsecrets.py` has live ESPN session credentials (SWID + espn_s2) hardcoded in plaintext. Must be rotated and moved to a local, gitignored secrets store (or env vars) before any ESPN connector code is written. Never commit credentials of any kind.
- Live draft-polling feasibility per platform is unverified — treat as a separate investigation, not a dependency for the core draft tool.

## Where to look for more

- `DECISIONS.md` — full chronological log of every decision above, with context, rationale, and alternatives considered. Written in portfolio-readable style since it doubles as a work sample.
- `README.md` — project overview for external readers.
