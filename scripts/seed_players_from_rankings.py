"""Preseason bootstrap: create canonical players from the Top-300 draft rankings.

Run this once before draft day, for each scoring format you draft with. Platform
league syncs only create a canonical player once someone is actually rostered, so
before any leagues have drafted the current season, most of the Top-300 (rookies,
free agents, anyone not still on a synced keeper roster) has no canonical player
yet — which means they're both missing from the Draft tab's rank list and
unselectable in pick entry (players.search only queries existing canonical
players). This script fixes that by treating the Top-300 feed as authoritative,
same trust level as a platform roster sync, and creating players for whatever
doesn't already match.

This is deliberately separate from the routine "Refresh Rankings" sync, which
stays conservative (queues unmatched names for manual review instead of creating)
to avoid polluting canonical names with weekly-feed scrape noise during the season.

Usage:
    python -m scripts.seed_players_from_rankings [--season 2026] [--scoring-format full_ppr]
"""

import argparse
import datetime

from ffassistant.db import get_connection
from ffassistant.ingest.rankings import sync_draft_rankings, sync_tiers
from ffassistant.name_matching import list_unresolved

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, default=datetime.date.today().year)
    parser.add_argument("--scoring-format", default="full_ppr")
    args = parser.parse_args()

    conn = get_connection()
    before = {r["raw_name"] for r in list_unresolved(conn, "rankings_provider")}

    sync_draft_rankings(conn, args.season, args.scoring_format, create_missing=True)
    sync_tiers(conn, args.season)

    after = {r["raw_name"] for r in list_unresolved(conn, "rankings_provider")}
    created = before - after

    print(f"Seeded {len(created)} new canonical players from the {args.scoring_format} Top-300 ({args.season}).")
    if after:
        print(f"{len(after)} names still unresolved (likely ambiguous multi-matches) — review manually:")
        for name in sorted(after):
            print(f"  {name}")
