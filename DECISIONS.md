# Decision Journal

A running log of key decisions on the Fantasy Football Assistant project — what was decided, why, and what alternatives were considered. Kept for two reasons: to keep the project coherent as it grows, and to give portfolio reviewers a window into the thinking behind the build.

Newest entries at the top.

---

## 2026-07-04 — Win/loss tracking design

**Context:** Keith laid out what he wants from the W-L tracker, based on the shape of the legacy W-L 2025.xlsx (13 years of history, per-year and all-years rollups).

**Decisions:**

- **Four year-scoped views, selected by a year picker (not a league picker — these span all leagues at once):**
  1. Game-by-game results per league for the selected year (league, week, PF, PA, differential) — matches the legacy "20XX Results" sheet.
  2. Weekly aggregate across all leagues combined: net games-above-even for that week, plus a running cumulative total through the season.
  3. League summary for the year: one row per league with W/L/T, buy-in, max possible payout, actual payout, and finishing position — matches the legacy per-year sheet's columns.
  4. Close games: wins and losses with a margin under 6 points, showing league, week, and margin. Fixed threshold (6 points), not a relative/percentage rule or an unthresholded sorted list — Keith had a specific number already in mind from how he'd used the legacy sheet.
- **One all-years rollup, per league:** W/L/T, win percentage, years played, 1st/2nd/3rd-place finish counts, points for, points against. Points for/against were columns the legacy "All Years" sheet had but never actually filled in — this is a real gap the new tool closes, not just a carryover.
- **W-L becomes a fifth peer in the app-level nav**, alongside Draft, In-season, Exposure, and League settings.

**Games view correction:** initially built as one combined table (Week, League, Outcome, PF, PA, Diff all in one flat list). Keith corrected this — the legacy per-year sheet actually gives each league its own block, with weeks 1-17 as rows and a total row at the bottom, arranged side by side across the sheet. Rebuilt as one card per league, horizontally scrollable — the same pattern already used for the draft tool's Grid (team columns) and Rosters (team cards) tabs. Each week row shows PF and PA scores alongside outcome and differential, not just the differential.

**Future automation note:** weekly game results (PF/PA/outcome) have always been filled in by hand. That doesn't have to stay true going forward — the platform connectors are already planned as read-only and already need matchup data as part of the shared data model, so current/future-season results could populate automatically the same way rosters and settings do. Historical years (2013 through last season) stay a one-time import from the legacy spreadsheet, since platforms don't expose that retroactively. Manual entry remains available as a fallback for anything the APIs don't cover cleanly. Not a commitment yet, just a noted direction.

---

## 2026-07-04 — App-level navigation shape

**Context:** With Draft, In-season, and Exposure each designed as their own sections, Keith asked where league configuration (names, platforms, scoring, roster construction) fits.

**Decision:** League settings get their own shared section too — formalizing the legacy "Settings" sheet's role as a single table that every other part of the app reads from, rather than each module keeping its own copy. It's a distinct section from the three functional views, but a low-frequency one (setup/edit leagues) rather than something checked regularly.

**Resulting app-level nav:** Draft | In-season | Exposure | League settings (W-L tracking still to be designed and placed).

---

## 2026-07-04 — In-season tool design

**Context:** Keith walked through his actual weekly routine: Tuesday night waiver prep (before ETR's weekly refresh, so more subjective), Wednesday night once ETR's rest-of-season and weekly rankings are both out (waiver targets + setting lineups), then Thursday/Sunday-morning/Monday re-checks before each slate locks. He also pointed to the legacy "Weekly Rank Eval" tab (Manager 2025.xlsm) as the reference for two of the views.

**Decisions:**

- **Two core views, mirroring the legacy sheet exactly:** Weekly (Rostered | Available) and Rest-of-season (Rostered | Available), both grouped by position, scoped to one league at a time via the shared league-selector pattern.
- **Thursday/Sunday/Monday re-checks reuse the Wednesday lineup view as-is** — same screen, just reopened with whatever's refreshed since, rather than a separate "what changed" diff view.
- **Swap-candidate judgment calls shown as plain numbers, not a computed threshold** — same approach as the draft tool's ADP lookahead: your starter's rank sits next to the closest bench alternatives at that position, and Keith makes the call rather than the tool deciding what counts as "close enough."
- **Tuesday's pre-ETR step gets lightweight support, built around ETR's separate "Waiver Wire" suggestion content** (distinct from its numeric rankings tables — a written list of recommended pickups). The tool cross-references those suggested names against what's actually available (unrostered) in each of Keith's leagues, shown alongside his own worst-ranked players per position using the last available data (since that week's rankings refresh hasn't happened yet). This means the rankings-ingestion layer needs to handle more than tables — it also needs to parse an editorial suggestion list as its own content type.
- **Automation stays hybrid, as already decided for the core architecture** — scheduled pulls for the routine Tuesday/Wednesday/Thursday/Sunday/Monday refreshes, with manual/on-demand refresh always available too.

**Follow-up: "worst players" and "available" list behavior**

- **Raw rank is sufficient for sorting "worst rostered players"** — no extra tie-breaking logic needed.
- **Unranked players (injured/suspended for the week) still need to show up in the worst-players list**, not disappear just because that week's rankings omit them. They should be flagged with their status (injured/suspended/bye) rather than silently dropped — this means the in-season data model needs a player-status field per roster spot, most likely sourced from the platforms' own roster data (which typically carries injury designations) rather than from the rankings provider. Not yet verified which platforms expose this cleanly — flagged to check during connector build.
- **The "Available" list is never gated by whether it beats your roster.** It always shows the best-ranked available options at a position, even in weeks where none of them would actually improve on your worst rostered player — useful for depth/bye-week visibility, not just upgrade-hunting.
- **A visual indicator connects the two lists**: highlight when an available player's rank is better than one of your lowest-ranked rostered players at that position (an unranked/injured rostered player counts as automatically beaten). Surfaces real opportunities without hiding the baseline "who's out there" view.

**Scope boundary: advisory only, no write-back to platforms.** The tool surfaces suggestions (waiver targets, lineup swaps) but Keith executes the actual add/drop or lineup change directly in ESPN/Yahoo/Sleeper himself. This means platform connectors only need read access (rosters, league settings, waiver priority, matchups) — no transactional/write API calls, which simplifies auth scope and removes any risk of the tool making a roster move on its own.

**No separate lineup-setting screen needed.** The Weekly Ranks view (rostered players' weekly rank per position, with side-by-side comparisons against close alternatives) doubles as the lineup-setting tool — there's no additional "apply this lineup" interaction to design, since Keith sets the actual lineup in the platform itself. This closes out the in-season view design: Weekly and ROS Rostered-vs-Available cover waiver prep, waiver targeting, and lineup decisions all in one pair of views.

**Weekly view needs DST and K; rest-of-season doesn't.** Keith streams both positions frequently (matchup-based weekly swaps), so they need the same Rostered-vs-Available treatment as QB/RB/WR/TE in the Weekly tab. ROS doesn't need this — DST/K aren't rest-of-season strategic assets the way skill positions are, so that view stays QB/RB/WR/TE only.

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
