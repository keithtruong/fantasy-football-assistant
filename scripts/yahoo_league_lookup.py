"""Look up your Yahoo league keys for a season.

Yahoo league keys are `{game_key}.l.{league_id}`, and game_key changes every season — the
bare numeric ID in a Yahoo league URL (e.g. football.fantasysports.yahoo.com/f1/150416) is
only the league_id portion. When adding or renewing a league in the app, use the full key
this script prints, not the bare URL number.

Usage:
    python -m scripts.yahoo_league_lookup [--season 2026]
"""

import argparse
import datetime

from ffassistant.connectors.yahoo import list_league_ids

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=datetime.date.today().year)
    args = parser.parse_args()

    keys = list_league_ids(args.season)
    if not keys:
        print(f"No Yahoo leagues found for {args.season}.")
    else:
        print(f"Yahoo league keys for {args.season}:")
        for key in keys:
            print(f"  {key}")
