"""Step 3 of the weekly recap workflow — see scripts/prepare_weekly_recap.py
for steps 1-2 (gathering this week's data and hand-writing narrative text).

Re-gathers this week's recap data, merges in whatever narrative text has
been hand-written to data/recap_drafts/{league_id}_{season}_wk{week}_narratives.json,
renders the recap HTML, writes it to disk, and (with --post-groupme) posts
the link into TAMS' GroupMe channel.

Usage:
    python -m scripts.render_weekly_recap --league-id 3 [--season 2026] [--week 2]
        [--league-name TAMS] [--bot-name "TAMS Fantasybot"]
        [--post-groupme --recap-url https://.../wk2.html]

Runs fine with no narratives file at all, or an empty one — matchups just
render without their narrative paragraph, the same "missing data renders a
gap, not a crash" convention as the rest of ffassistant.recap. That's a
degraded recap, not a broken one, so this step is never blocked on step 2
having actually run.

Email delivery isn't wired up here yet (that goes through Keith's Gmail
connector once that's built) — this script only writes the HTML file and,
optionally, posts to GroupMe.
"""

import argparse
import datetime
import json
import sys

from ffassistant.config import REPO_ROOT
from ffassistant.connectors.groupme import post_message
from ffassistant.db import get_connection
from ffassistant.recap import apply_narratives
from ffassistant.recap_data import gather_recap_data
from ffassistant.recap_html import render_recap_html
from ffassistant.season import smart_current_week

DRAFTS_DIR = REPO_ROOT / "data" / "recap_drafts"
OUTPUT_DIR = REPO_ROOT / "data" / "recaps"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--season", type=int, default=None, help="Defaults to the current calendar year")
    parser.add_argument("--week", type=int, default=None, help="Defaults to smart_current_week()")
    parser.add_argument("--league-name", default="TAMS")
    parser.add_argument("--bot-name", default="TAMS Fantasybot")
    parser.add_argument("--post-groupme", action="store_true")
    parser.add_argument("--recap-url", default=None, help="Required with --post-groupme")
    args = parser.parse_args(argv)

    if args.post_groupme and not args.recap_url:
        parser.error("--post-groupme requires --recap-url")

    conn = get_connection()
    season = args.season or datetime.date.today().year
    week = args.week or smart_current_week(conn, season)
    if week is None:
        print("Could not resolve the current week — pass --week explicitly.", file=sys.stderr)
        return 1

    data = gather_recap_data(conn, args.league_id, season, week)

    narratives_path = DRAFTS_DIR / f"{args.league_id}_{season}_wk{week}_narratives.json"
    if narratives_path.exists():
        narratives = json.loads(narratives_path.read_text()).get("matchup_narratives", {})
        print(f"Loaded {len(narratives)} hand-written narrative(s) from {narratives_path}")
    else:
        narratives = {}
        print(f"No narratives file at {narratives_path} — rendering without matchup narratives.", file=sys.stderr)

    data["matchup_details"] = apply_narratives(data["matchup_details"], narratives)

    html_out = render_recap_html(data, league_name=args.league_name, bot_name=args.bot_name)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.league_id}_{season}_wk{week}.html"
    out_path.write_text(html_out)
    print(f"Wrote recap: {out_path}")

    if args.post_groupme:
        post_message(f"Week {week} TAMS recap is up: {args.recap_url}")
        print("Posted to GroupMe.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
