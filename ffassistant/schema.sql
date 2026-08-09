-- Fantasy Football Assistant — SQLite schema
-- Source of truth for league settings, players/aliases, rankings, rosters/transactions,
-- and matchup history. See CLAUDE.md "Core architecture" for the design this implements.

PRAGMA foreign_keys = ON;

-- ============================================================
-- League settings
-- ============================================================

-- One row per league. Scoring/roster-construction details live in the
-- child tables below rather than as fixed columns, since both vary a lot
-- across 10 leagues on 3 platforms.
CREATE TABLE IF NOT EXISTS leagues (
    league_id           INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    platform            TEXT NOT NULL CHECK (platform IN ('espn', 'yahoo', 'sleeper')),
    platform_league_id  TEXT,
    team_count          INTEGER NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes               TEXT
);

-- Scoring rules as key/value pairs (e.g. 'pass_td' -> 4, 'rec' -> 1) so
-- adding a new stat category never requires a schema change.
CREATE TABLE IF NOT EXISTS league_scoring (
    league_id   INTEGER NOT NULL REFERENCES leagues (league_id) ON DELETE CASCADE,
    stat_key    TEXT NOT NULL,
    points      REAL NOT NULL,
    PRIMARY KEY (league_id, stat_key)
);

-- Roster construction: one row per slot type (starters, flex, bench, IR).
-- Sum of counts = total draft rounds. Also what the draft Grid tab's
-- position-count summary checks against to flag "starters filled".
CREATE TABLE IF NOT EXISTS roster_slots (
    league_id   INTEGER NOT NULL REFERENCES leagues (league_id) ON DELETE CASCADE,
    slot_name   TEXT NOT NULL,   -- e.g. 'QB', 'RB', 'WR', 'TE', 'FLEX', 'DST', 'K', 'BENCH', 'IR'
    slot_count  INTEGER NOT NULL,
    PRIMARY KEY (league_id, slot_name)
);

-- Teams within a league (up to 18 per league). `is_mine` flags Keith's
-- own team; `draft_position` is the snake-draft slot used to drive
-- order-based pick entry in the draft tool. `team_name` is owned by the
-- platform sync (overwritten on every resync); `display_name` is Keith's
-- own override (e.g. the owner's actual name) and is never touched by
-- sync — NULL means "just use team_name".
CREATE TABLE IF NOT EXISTS teams (
    team_id             INTEGER PRIMARY KEY,
    league_id           INTEGER NOT NULL REFERENCES leagues (league_id) ON DELETE CASCADE,
    platform_team_id    TEXT,
    team_name           TEXT NOT NULL,
    display_name        TEXT,
    is_mine             INTEGER NOT NULL DEFAULT 0 CHECK (is_mine IN (0, 1)),
    draft_position      INTEGER,
    UNIQUE (league_id, platform_team_id)
);

CREATE INDEX IF NOT EXISTS idx_teams_league ON teams (league_id);

-- ============================================================
-- Players + platform aliases
-- ============================================================

-- Canonical player identity. Everything else (rankings, rosters,
-- transactions) points here, never at a platform-specific name directly.
CREATE TABLE IF NOT EXISTS players (
    player_id   INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    position    TEXT CHECK (position IN ('QB', 'RB', 'WR', 'TE', 'DST', 'K')),
    nfl_team    TEXT,
    bye_week    INTEGER,
    -- First NFL season, per Sleeper's public player data (years_exp = 0).
    -- Not meaningful for DST rows, which stay 0 (the schema default).
    is_rookie   INTEGER NOT NULL DEFAULT 0 CHECK (is_rookie IN (0, 1))
);

-- Per-platform/per-source name variants, resolved to a canonical player_id
-- via the exact -> suffix-normalized -> manual-override matching pipeline.
-- `source` covers platform connectors ('espn', 'yahoo', 'sleeper') and the
-- generic rankings feed ('rankings_provider' — never name it, see CLAUDE.md).
CREATE TABLE IF NOT EXISTS player_aliases (
    alias_id            INTEGER PRIMARY KEY,
    player_id           INTEGER NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    source              TEXT NOT NULL,
    source_player_id    TEXT,
    alias_name          TEXT NOT NULL,
    UNIQUE (source, alias_name)
);

CREATE INDEX IF NOT EXISTS idx_player_aliases_player ON player_aliases (player_id);

-- Queue of names the matching pipeline (exact -> suffix-normalized) could
-- not resolve. Reviewed by hand; resolving one inserts the mapping into
-- player_aliases (making it an exact match next time) and clears it here.
CREATE TABLE IF NOT EXISTS unresolved_aliases (
    unresolved_id   INTEGER PRIMARY KEY,
    source          TEXT NOT NULL,
    raw_name        TEXT NOT NULL,
    position_hint   TEXT,
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, raw_name)
);

-- Weekly player status (injury/suspension/bye), used by the in-season
-- "worst rostered players" list so a missing ranking doesn't silently drop
-- someone who's just unranked that week. Populated from platform roster
-- data once connectors are built — schema slot reserved now per CLAUDE.md
-- "known technical debt" notes.
CREATE TABLE IF NOT EXISTS player_status (
    player_id   INTEGER NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('healthy', 'questionable', 'out', 'ir', 'suspended', 'bye')),
    source      TEXT,
    PRIMARY KEY (player_id, season, week)
);

-- Keith's own manual "target"/"avoid" call on a player, independent of rank —
-- e.g. "shy_away" for injury/contract/scheme concerns rank alone wouldn't
-- capture. Global per player (not per league/season): a personal read on the
-- player, not a per-draft computation like the rank-vs-ADP Reach/Wait tag.
CREATE TABLE IF NOT EXISTS player_manual_tags (
    player_id   INTEGER PRIMARY KEY REFERENCES players (player_id) ON DELETE CASCADE,
    tag         TEXT NOT NULL CHECK (tag IN ('sleeper', 'shy_away'))
);

-- Keith's read on a backfield's touch-share situation — a different axis from
-- player_manual_tags' target/avoid call (a player can be both e.g. "Shy-away"
-- and "Committee" at once), so it's a separate table rather than an extra
-- value on that one. 'one_injury_away' marks a backup who'd inherit
-- bellcow/near-bellcow work if the starter ahead of them got hurt.
CREATE TABLE IF NOT EXISTS player_role_tags (
    player_id   INTEGER PRIMARY KEY REFERENCES players (player_id) ON DELETE CASCADE,
    tag         TEXT NOT NULL CHECK (tag IN ('bellcow', 'committee', 'one_injury_away'))
);

-- ============================================================
-- NFL team reference data (static, one-time-per-season imports)
-- ============================================================

-- Bye week per NFL team. Team-level, not player-level — joined via players.nfl_team
-- rather than duplicated onto every player row.
CREATE TABLE IF NOT EXISTS nfl_team_byes (
    season      INTEGER NOT NULL,
    team        TEXT NOT NULL,
    bye_week    INTEGER NOT NULL,
    PRIMARY KEY (season, team)
);

-- Playoff strength-of-schedule (weeks 15-17), derived from de-vigged win-total
-- O/U lines: each team's score is the average implied-win-value of its three
-- playoff-week opponents. See DECISIONS.md for the full methodology.
CREATE TABLE IF NOT EXISTS nfl_team_playoff_sos (
    season                      INTEGER NOT NULL,
    team                        TEXT NOT NULL,
    own_implied_wins            REAL,
    wk15_opp                    TEXT,
    wk15_opp_wins               REAL,
    wk16_opp                    TEXT,
    wk16_opp_wins               REAL,
    wk17_opp                    TEXT,
    wk17_opp_wins               REAL,
    playoff_sos_avg_opp_wins    REAL,
    sos_rank                    INTEGER,
    PRIMARY KEY (season, team)
);

-- Full-season opponent schedule (weeks 1-17), one row per team per week it
-- plays — bye weeks have no row here (join nfl_team_byes for that). Opponent
-- difficulty is derived at read time from nfl_team_playoff_sos.own_implied_wins
-- rather than stored here, since it's the same win-total value regardless of
-- which week's matchup you're looking at.
CREATE TABLE IF NOT EXISTS nfl_team_schedule (
    season      INTEGER NOT NULL,
    team        TEXT NOT NULL,
    week        INTEGER NOT NULL,
    opponent    TEXT NOT NULL,
    is_home     INTEGER NOT NULL CHECK (is_home IN (0, 1)),
    PRIMARY KEY (season, team, week)
);

-- ============================================================
-- Rankings (draft / weekly / rest-of-season + editorial waiver suggestions)
-- ============================================================

-- Numeric rankings tables. One row per player per ranking snapshot.
-- `ranking_type` distinguishes draft-season ADP-style rankings from
-- in-season weekly and rest-of-season rankings.
CREATE TABLE IF NOT EXISTS rankings (
    ranking_id      INTEGER PRIMARY KEY,
    player_id       INTEGER NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    ranking_type    TEXT NOT NULL CHECK (ranking_type IN ('draft', 'weekly', 'ros')),
    season          INTEGER NOT NULL,
    week            INTEGER,   -- NULL for 'draft' and 'ros', set for 'weekly'
    scoring_format  TEXT,      -- only meaningful for ranking_type = 'draft' (e.g. full_ppr, superflex)
    rank            INTEGER,
    tier            INTEGER,
    adp             REAL,      -- only meaningful for ranking_type = 'draft'
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rankings_lookup ON rankings (ranking_type, season, week);
CREATE INDEX IF NOT EXISTS idx_rankings_player ON rankings (player_id);

-- Editorial "waiver wire" suggestion content — a written recommendation
-- list, distinct from the numeric rankings tables above. Supports the
-- Tuesday pre-refresh waiver-prep step. `raw_name` is kept alongside the
-- resolved player_id for traceability when name-matching is uncertain.
CREATE TABLE IF NOT EXISTS waiver_suggestions (
    suggestion_id   INTEGER PRIMARY KEY,
    player_id       INTEGER REFERENCES players (player_id) ON DELETE SET NULL,
    raw_name        TEXT NOT NULL,
    season          INTEGER NOT NULL,
    week            INTEGER NOT NULL,
    note            TEXT,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_waiver_suggestions_lookup ON waiver_suggestions (season, week);

-- ============================================================
-- Rosters / transactions
-- ============================================================

-- Draft picks, one row per pick. Doubles as the Grid tab's team x round
-- board and drives order-based pick entry (round/pick_number come from
-- team_count + draft_position, not chosen per pick).
CREATE TABLE IF NOT EXISTS draft_picks (
    draft_pick_id   INTEGER PRIMARY KEY,
    league_id       INTEGER NOT NULL REFERENCES leagues (league_id) ON DELETE CASCADE,
    season          INTEGER NOT NULL,
    round           INTEGER NOT NULL,
    pick_number     INTEGER NOT NULL,   -- overall pick number for the draft
    team_id         INTEGER NOT NULL REFERENCES teams (team_id) ON DELETE CASCADE,
    player_id       INTEGER REFERENCES players (player_id) ON DELETE SET NULL,
    picked_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (league_id, season, pick_number)
);

CREATE INDEX IF NOT EXISTS idx_draft_picks_league_season ON draft_picks (league_id, season);

-- Current roster membership snapshot — who's on which team right now.
-- Starter/bench display is derived at the application layer from position
-- + roster_slots counts, not stored here.
CREATE TABLE IF NOT EXISTS roster_spots (
    roster_spot_id  INTEGER PRIMARY KEY,
    team_id         INTEGER NOT NULL REFERENCES teams (team_id) ON DELETE CASCADE,
    player_id       INTEGER NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    -- NULL when a full roster sync can't tell provenance apart from prior state
    acquired_via    TEXT CHECK (acquired_via IS NULL OR acquired_via IN ('draft', 'waiver', 'trade', 'free_agent')),
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (team_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_roster_spots_team ON roster_spots (team_id);
CREATE INDEX IF NOT EXISTS idx_roster_spots_player ON roster_spots (player_id);

-- Waiver/trade transaction log (post-draft roster moves). `related_player_id`
-- covers trades (the player sent back the other way) and waiver drops.
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id      INTEGER PRIMARY KEY,
    league_id           INTEGER NOT NULL REFERENCES leagues (league_id) ON DELETE CASCADE,
    team_id             INTEGER NOT NULL REFERENCES teams (team_id) ON DELETE CASCADE,
    player_id           INTEGER NOT NULL REFERENCES players (player_id) ON DELETE CASCADE,
    related_player_id   INTEGER REFERENCES players (player_id) ON DELETE SET NULL,
    transaction_type    TEXT NOT NULL CHECK (transaction_type IN ('add', 'drop', 'trade')),
    season              INTEGER NOT NULL,
    week                INTEGER,
    transaction_date    TEXT NOT NULL DEFAULT (datetime('now')),
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_transactions_league_season ON transactions (league_id, season);

-- ============================================================
-- Matchup history (W-L tracking)
-- ============================================================

-- Stable identity for a real-world league across many seasons, independent of
-- the live `leagues` table (which gets recreated/re-synced each year as
-- platform league IDs churn, especially Yahoo's). W-L history must survive
-- that churn, so it never references `leagues`/`teams` at all — same idea as
-- separating a canonical player identity from churn-prone platform aliases.
CREATE TABLE IF NOT EXISTS league_history (
    league_history_id   INTEGER PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    active              INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

-- Per-season league facts: buy-in/payout/finish and W-L record. Year-scoped
-- (dues and payouts can change year to year even for the same league) and
-- keyed off `league_history`, not the live `leagues` table, for the same
-- churn-resistance reason as `matchups` below.
CREATE TABLE IF NOT EXISTS league_seasons (
    league_season_id    INTEGER PRIMARY KEY,
    league_history_id   INTEGER NOT NULL REFERENCES league_history (league_history_id) ON DELETE CASCADE,
    season              INTEGER NOT NULL,
    wins                INTEGER NOT NULL DEFAULT 0,
    losses              INTEGER NOT NULL DEFAULT 0,
    ties                INTEGER NOT NULL DEFAULT 0,
    buy_in              REAL,
    max_payout          REAL,
    actual_payout       REAL,
    finish_position     INTEGER,
    UNIQUE (league_history_id, season)
);

-- One row per week per league-history entry — matches the legacy per-year
-- "Results" sheet (league, week, PF, PA, differential, playoff round) and
-- feeds the Games/Weekly/Close-games W-L views directly. No opponent
-- identity: the legacy data never tracked it, and there's only ever one row
-- per league-history per week (this is always "my" result), never per team.
CREATE TABLE IF NOT EXISTS matchups (
    matchup_id          INTEGER PRIMARY KEY,
    league_history_id   INTEGER NOT NULL REFERENCES league_history (league_history_id) ON DELETE CASCADE,
    season              INTEGER NOT NULL,
    week                INTEGER NOT NULL,
    points_for          REAL NOT NULL,
    points_against      REAL NOT NULL,
    outcome             TEXT NOT NULL CHECK (outcome IN ('W', 'L', 'T')),
    playoff_round       TEXT CHECK (playoff_round IN ('semifinal', 'final', 'third_place')),
    UNIQUE (league_history_id, season, week)
);

CREATE INDEX IF NOT EXISTS idx_matchups_season_week ON matchups (season, week);
CREATE INDEX IF NOT EXISTS idx_matchups_league_season ON matchups (league_history_id, season);
