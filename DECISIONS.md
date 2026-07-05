# Decision Journal

A running log of key decisions on the Fantasy Football Assistant project — what was decided, why, and what alternatives were considered. Kept for two reasons: to keep the project coherent as it grows, and to give portfolio reviewers a window into the thinking behind the build.

Newest entries at the top.

---

## 2026-07-04 — Draft tool screen layout

**Context:** Keith laid out the full set of information the draft experience needs to show — per-league rankings with tiers/colors/round-value tracking, position-run pace, the full team x round board, per-team position-filled status, an ADP lookahead for value/wait tradeoffs, projected starter strength by team, bye-week clustering, cross-league exposure, and a playoff strength-of-schedule tag. He asked for a layout recommendation based on screen real estate (has to work on a laptop) and how these pieces cross over with each other, rather than specifying the screen breakdown himself.

**Decisions:**

- **Draft and Room merge into one screen, not two tabs.** The rankings list (with tiers, colors, round-value chips, playoff-SOS tag) is the main content; a right-hand rail holds your roster/position needs, the team-by-position matrix with the safe-to-wait signal, and the ADP lookahead — all visible without switching tabs, since these are exactly the things you weigh together while deciding a live pick under time pressure. Rail sections are collapsible so the laptop-width layout doesn't feel cramped when you don't need every panel open.
- **Grid (full team x round board) stays a separate tab.** Different layout shape entirely (wide matrix vs. a list), and it's used for audit/correction during and after the draft rather than for the moment-to-moment pick decision — low crossover with the live view.
- **Rosters (projected starters, relative strength by position, bye-week clustering) stays a separate tab.** Reflection/comparison view, not something you need mid-pick.
- **Exposure is promoted out of the draft tool entirely.** Since it matters just as much in-season after trades and waivers as it does during drafts, it becomes a shared, year-round view at the app level (alongside Draft and In-season), not nested under either one.

**Resulting structure:** app-level nav = Draft | In-season | Exposure (W-L tracking to be placed once discussed). Within Draft for a given league: Draft (board + rail) | Grid | Rosters.

**Follow-up refinements:**

- **Rank list column order:** Rank, then Player name, then Position — matching the legacy sheet's column order. (Earlier mockup had put the position badge before the player name within the cell; corrected.)
- **Grid tab carries forward the legacy position-count summary.** Each per-league "Draft Board" sheet had a block directly under the round-by-round grid — one row per position (QB/RB/WR/TE/DST/K), one column per team — showing a live count of how many players that team has drafted at each position, with conditional formatting that highlights a team's cell once that count clears the starter requirement for that position (from league settings). Carrying this forward as-is in the new Grid tab, rather than only surfacing it in the Draft tab's "Team needs" rail panel.
- **ADP lookahead is a longer, plainer list than first mocked up.** The legacy "ADP Next" sheet listed roughly the next 10-20 players sorted by ADP ascending, with Rank/Player/Position/Team/Bye/ADP/Pos Tier columns side by side — letting Keith compare his own rank against market ADP directly and spot the gap himself. Replacing the earlier probability-bar mockup with this simpler, longer, sortable list to match.
- **Position colors carried over from the source workbook.** QB = green, RB = blue, WR = red, matching the legacy "Draft Station" sheet's header gradient fills. TE, DST, and K (uncolored in the source) get pink, amber, and purple respectively — distinct from each other and from QB/RB/WR, per feedback that the first pass (teal/gray/gray) wasn't distinct enough.
- **Grid tab gets per-cell click-to-edit** for correcting a specific pick after the fact, and scales to the full team count (up to 18) via horizontal scroll rather than trying to compress everything to one screen width.
- **Rosters tab redesigned around the legacy "Live Rosters" sheet.** That sheet organizes by position (QB/RB/WR/TE sections), with one column per team showing that team's relative rank at the position (compared to the rest of the league) plus the actual rostered players — starters first, bench below. Rebuilding the Rosters tab this way instead of the earlier single 0-100 "strength score" table, since Keith wants to see the actual players, not just an abstracted number.
- **Rosters tab regrouped by team, not by position.** Keith clarified the legacy sheet is really structured as one box per team (up to 18), each box containing all of that team's positions stacked inside it — not position-sectioned tables with teams as columns. Rebuilt as one card per team (QB/RB/WR/TE with rank + starters/bench inside each card), arranged in a horizontally scrollable row so it scales to the full team count the same way the Grid tab does. Bench players are shown dimmed rather than under a "Bench" text label, per feedback.
- **League selector is one shared control above the Draft/Grid/Rosters tab bar**, not duplicated per tab — switching tabs keeps the same league in view rather than resetting it. In-season will get its own equivalent selector later; Exposure doesn't need one since it's cross-league by design.
- **Bye-week info moves to the Draft tab**, attached to Keith's own roster panel in the rail, rather than living on the Rosters tab.

---

## 2026-07-04 — Draft-day pick entry

**Context:** Working through the draft board UI, specifically how picks get recorded during a live draft so the tool always knows who's taken and by whom, across leagues where drafting happens differently (some live inside the platform's own draft room, some over a call or in person and entered afterward).

**Decisions:**

- **Order-driven entry, not per-pick team selection.** Snake draft order is fixed and known from each league's settings, so the tool tracks "on the clock" automatically and only needs the player name per pick — search, hit enter, done. Team attribution and clock advancement happen automatically from the known order, with an "undo/edit pick" control for corrections (typos, out-of-order hearsay, autopicks). This is the reliable baseline for every league regardless of how the draft happens.
- **Live auto-poll from the platform is a possible later enhancement, not a commitment.** Since some leagues draft live in-platform and others don't, manual entry has to work everywhere anyway. Whether ESPN/Yahoo/Sleeper expose usable in-progress draft data (versus only post-completion) hasn't been verified — worth investigating later for the in-platform leagues, but not something to design around yet.
- **Every team's roster-in-progress is tracked during the draft, not just Keith's** — this is why order-driven attribution matters and isn't just a bookkeeping shortcut. Knowing which positions every other team has already filled enables a "safe to wait" read: if the teams picking before Keith's next turn already have a given position's starting slots filled, there's low risk of a run on it and he can punt that position for now. This mirrors what the legacy system's per-league "Heat Map" and "Team Exposure" sheets were already tracking, so it's a validated need carried forward, not new scope.

---

## 2026-07-04 — Core architecture

**Context:** Full scope is now defined: managing 10 leagues across three platforms (ESPN, Yahoo, Sleeper), each with different sizes and scoring systems. A prior Excel/VBA + Python system (not committed to this repo) handled this manually for years and informed a lot of this design. Three functions are required: draft/post-draft analysis, in-season management (rankings + roster/waiver data → start/sit and waiver suggestions), and long-term win/loss and payout tracking.

**Decisions:**

- **Single local database as the source of truth.** SQLite replaces the old spreadsheet-per-concern approach. One file holds league settings/scoring, canonical players + per-platform name aliases, rankings (draft, weekly, rest-of-season), rosters/transactions/waiver priority, and matchup history. A single-file database was also the deciding factor for the access-model decision below — it's trivial to copy or sync, unlike a server-based database.
- **Deterministic player-name matching, not LLM-based.** Platform and rankings-provider name variants (e.g. suffix differences like "Kenneth Walker" vs "Kenneth Walker III") get resolved with a rules-based pipeline — exact match, then normalized/suffix-stripped match, then a manual override table for anything left over — rather than asking a model to reconcile names on every run. Keeps the system fast and avoids unnecessary token spend, which was an explicit goal from the start.
- **Rankings source stays generic in code.** The site we pull rankings from is intentionally not named anywhere in this public repo — code and docs refer to it as a generic "rankings provider," with real source URLs and any provider-specific handling kept in a local, untracked config file. This is a personal preference around not tipping off league competitors, not a technical requirement.
- **Draft-day tool runs locally, synced by hand.** Rather than hosting the app somewhere reachable from any device, it runs as a local app on whichever machine is at the draft, with the database file synced over beforehand. Chosen for simplicity and zero hosting cost/security surface, at the cost of needing to remember the sync step before each draft.
- **Stack: Python backend, JS frontend.** Data pipelines, platform API connectors, and rankings ingestion stay in Python — it directly reuses lessons from the legacy `yahoo_fantasy_api`/`espn_api` scripts. The draft-day board and any dashboards get a lightweight JS frontend talking to a local Python API, since real-time filtering/searching across hundreds of players during a live draft needs snappier interactivity than server-rendered pages give.
- **Hybrid automation for in-season data pulls, desktop as home base.** Routine pulls (weekly rankings, rosters) run on a schedule on the desktop, which is on consistently enough that this isn't a real gap. The laptop is treated as an on-demand/draft-day companion rather than a second scheduled host — it works from whatever the database looked like at last sync, with a manual refresh available anytime.

**Security note carried over:** the legacy `espnsecrets.py` file has live ESPN session credentials hardcoded in plaintext. Not yet resolved — needs rotating and moving to a local, gitignored secrets file (or env vars) before any platform-connector code is written.

**Next up:** repo scaffolding and data model design, likely picked up in Claude Code given the git/GitHub constraints noted below.

---

## 2026-07-04 — Project kickoff and repo setup

**Context:** Starting the Fantasy Football Assistant project. Goal is to manage teams across multiple leagues and platforms, with the build documented for a job-seeking portfolio alongside a public GitHub repo (https://github.com/keithtruong/fantasy-football-assistant).

**Decisions:**

- **Documentation-first start.** Before any solutioning on scope or architecture, set up a README and a decision journal so every subsequent choice gets recorded as it happens rather than reconstructed later.
- **Decision log format:** a single `DECISIONS.md` file (not a per-entry folder), written in portfolio-readable style — plain-English context and rationale, not just terse commit-style notes — since this doubles as a work sample for recruiters.
- **Git setup:** local repo initialized with `origin` pointed at the existing GitHub repo; push deferred until credentials/auth are confirmed.

**Note on environment:** git operations against the connected project folder failed in this session — the folder is mounted through a network/FUSE layer that doesn't support git's file-locking behavior (`.git/config` came back corrupted). Repo history was built in a local sandbox path instead, with the plain files copied into the project folder. Running `git init` directly from a native terminal on the local machine (not through this mount) is expected to work normally — see the commands below.

**To connect this folder to GitHub, run from a terminal in this folder:**

```
git init
git add .
git commit -m "Initial commit: README and decision journal"
git branch -M main
git remote add origin https://github.com/keithtruong/fantasy-football-assistant.git
git push -u origin main
```

**Next up:** high-level discussion of project scope (leagues, platforms, core use cases) before any architecture or tooling decisions are made.
