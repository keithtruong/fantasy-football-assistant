"""Step 1 of the weekly recap workflow (mechanical — safe to run by hand or
on a schedule): gathers this week's recap data and writes a narrow
"narrative brief" JSON — just the facts (scores/top players/surprises) a
writer needs in order to hand-write each matchup's Yahoo-recap-style
paragraph.

ffassistant.recap_html/ffassistant.recap_data have no model access, so this
script deliberately stops short of writing any prose itself. The real
workflow is three steps:

    1. python -m scripts.prepare_weekly_recap --league-id 3 [--season 2026] [--week 2]
       -> writes data/recap_drafts/{league_id}_{season}_wk{week}_brief.json
          (this week's matchup facts) and, only if one doesn't already
          exist, an empty *_narratives.json stub to fill in.

    2. (a live Claude session, NOT this script) reads the brief and writes
       one {"headline": ..., "body": ...} entry per matchup into the stub's
       "matchup_narratives" dict, keyed by the brief entry's own "key"
       field (see ffassistant.recap.narrative_key/narrative_brief) — this
       is the same "a Claude session does this part live, not an API" shape
       as the Next Week Preview's Vegas over/under research.

       Style, per Keith's explicit direction (modeled on real Yahoo AI
       matchup recaps he supplied as examples — see DECISIONS.md): headline
       is one punchy, punny line built from the actual team/player names
       ("American Njigba Warrior Makes The Vinegar Strokes Look Like a D-
       Student!" is a real Yahoo one); body is full Yahoo-caliber snark —
       sarcastic similes, needling the losing side by name, citing the
       real over/under-projection numbers from top_players_*/surprises_*
       rather than inventing flavor. No letter grades (A+/D- report-card
       gimmick) and no closing tease about next week — Keith turned both
       of those down; end the body once this week's story is told. See
       ffassistant.recap.narrative_brief's docstring for the full style
       guide and worked examples.

       Two required checks before finalizing a narrative, both because the
       brief's numbers alone aren't enough to write it correctly:

       - Experience level: every player in top_players_a/b and
         surprises_a/b carries is_rookie — read it off that field, don't
         guess from memory/training data which draft class someone belongs
         to. A second-year (or later) player described as a "rookie" is a
         real, recurring mistake, not a hypothetical (see DECISIONS.md or
         ask Keith if unsure why this note exists).
       - In-game injuries: there is no in-game injury-timeline data in this
         project — box score points alone can't reveal that someone left
         hurt (they can outscore their projection before leaving, so even a
         big game is no evidence either way). Before finalizing each
         matchup's narrative, web-search for injury news on that matchup's
         featured players (anyone named in top_players_a/b or
         surprises_a/b) and reflect anything found in the prose. This is a
         required step, not a nice-to-have — skipping it is how a
         mid-game injury goes unmentioned.

    3. python -m scripts.render_weekly_recap --league-id 3 [...]
       merges that narratives file back in, renders the HTML, writes it to
       disk, and (with --post-groupme) posts the link to GroupMe.

Re-running step 1 for the same league/season/week overwrites the brief
(this week's facts may have changed since last run) but never touches an
existing narratives file — rerunning shouldn't blow away narration that's
already been hand-written.
"""

import argparse
import datetime
import json
import sys

from ffassistant.config import REPO_ROOT
from ffassistant.db import get_connection
from ffassistant.recap import narrative_brief
from ffassistant.recap_data import gather_recap_data
from ffassistant.season import smart_current_week

DRAFTS_DIR = REPO_ROOT / "data" / "recap_drafts"


def _paths(league_id: int, season: int, week: int):
    stem = f"{league_id}_{season}_wk{week}"
    return DRAFTS_DIR / f"{stem}_brief.json", DRAFTS_DIR / f"{stem}_narratives.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=None, help="Defaults to the current calendar year")
    parser.add_argument("--week", type=int, default=None, help="Defaults to smart_current_week()")
    args = parser.parse_args(argv)

    conn = get_connection()
    season = args.season or datetime.date.today().year
    week = args.week or smart_current_week(conn, season)
    if week is None:
        print("Could not resolve the current week — pass --week explicitly.", file=sys.stderr)
        return 1

    data = gather_recap_data(conn, args.league_id, season, week)
    brief = narrative_brief(data["matchup_details"])

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    brief_path, narratives_path = _paths(args.league_id, season, week)
    brief_path.write_text(json.dumps(brief, indent=2))
    print(f"Wrote brief ({len(brief)} matchups): {brief_path}")

    if narratives_path.exists():
        print(f"Narratives stub already exists, left as-is: {narratives_path}")
    else:
        narratives_path.write_text(json.dumps({"matchup_narratives": {}}, indent=2))
        print(f"Wrote empty narratives stub: {narratives_path}")

    print("\nNext: read the brief and fill in matchup_narratives (keyed by each entry's 'key'), then run "
          "scripts.render_weekly_recap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
