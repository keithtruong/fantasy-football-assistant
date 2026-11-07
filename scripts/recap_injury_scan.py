"""Injury check for the weekly recap's matchup narratives.

prepare_weekly_recap's docstring makes an injury check on every featured
player a required step before finalizing a narrative (box-score points can't
reveal that someone left a game hurt). This does the mechanical part: walks
the Rotoworld player-news archive back to the start of that NFL week and
prints every item about a featured player (anyone in a matchup's
top_players_*/surprises_*) that mentions an injury, exit, or status word —
so the writer reads a short list instead of paging the archive by hand.

It only gathers; deciding what's narratively relevant stays with the writer.
Matching is by the item's lead (subject player's name), same as the news
watcher, so related-story strips at the bottom of each item don't produce
false hits.

Usage:
    python -m scripts.recap_injury_scan --league-id 3 --week 5 [--season 2026] [--since 2026-10-08]

--since defaults to 6 days before today, which covers Thursday through
Monday night when this runs on the Tuesday after the week ends.
"""

import argparse
import datetime
import json
import re
import sys

from bs4 import BeautifulSoup

from ffassistant.connectors import nbc_news
from ffassistant.name_matching import normalize
from scripts import prepare_weekly_recap

MAX_PAGES = 40
_BODY = r"ankle|hamstring|knee|quad|groin|shoulder|foot|toe|back|ribs|calf|neck|hip|wrist|hand|thumb|concussion|illness|adductor|achilles|elbow"
INJURY_WORDS = re.compile(
    r"\b(injur\w*|exited|left the game|did not return|didn.t return|won.t return|will not return|ruled out|"
    r"carted|concussion protocol|walking boot|questionable to return|doubtful to return|mri|x-rays?|hobbled|"
    r"limped|limping|tweaked|aggravat\w*|playing through)\b"
    rf"|\((?:{_BODY})(?:[,/ ]+(?:{_BODY}))*\)",
    re.I,
)


def featured_players(brief: list[dict]) -> dict[str, str]:
    """normalized name -> display name, skipping team defenses."""
    names = {}
    for m in brief:
        for k in ("top_players_a", "top_players_b", "surprises_a", "surprises_b"):
            for p in m.get(k, []):
                if not p["full_name"].endswith("DST"):
                    names[normalize(p["full_name"])] = p["full_name"]
    return names


def scan(names: dict[str, str], since: str, fetch=nbc_news.fetch_page_html) -> list[dict]:
    hits, seen = [], set()
    for page_num in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(fetch(page_num), "html.parser")
        oldest = None
        for el in soup.find_all(attrs={"data-share-url": True}):
            link = el["data-share-url"]
            date = link.rstrip("/").split("/")[-2]
            oldest = date
            if date < since or link in seen:
                continue
            seen.add(link)
            container = el
            while container.parent is not None and len(container.parent.find_all(attrs={"data-share-url": True})) == 1:
                container = container.parent
            strings = list(container.stripped_strings)
            lead = normalize(" ".join(strings[:6]))
            match = next((n for n in sorted(names, key=len, reverse=True) if lead.startswith(n + " ")), None)
            if not match:
                continue
            text = " ".join(strings).split(" More ")[0]
            if INJURY_WORDS.search(text):
                hits.append({"date": date, "player": names[match], "link": link, "text": text[:600]})
        if oldest is None or oldest < since:
            break
    return sorted(hits, key=lambda h: (h["player"], h["date"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--league-id", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--season", type=int, default=None)
    parser.add_argument("--since", default=None, help="YYYY-MM-DD; defaults to 6 days ago")
    args = parser.parse_args(argv)
    season = args.season or datetime.date.today().year
    since = args.since or (datetime.date.today() - datetime.timedelta(days=6)).isoformat()

    brief_path, _ = prepare_weekly_recap._paths(args.league_id, season, args.week)
    hits = scan(featured_players(json.loads(brief_path.read_text())), since)
    if not hits:
        print(f"No injury-related Rotoworld items for featured players since {since}.")
    for h in hits:
        print(f"[{h['date']}] {h['player']}: {h['text']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
