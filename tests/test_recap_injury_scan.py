import unittest

from scripts import recap_injury_scan as scan

BASE = "https://www.nbcsports.com/fantasy/football/player-news/"


def item(date, first, last, body):
    return (f'<li><span>{first}</span> <span>{last}</span><span>SF</span><p>{body}</p>'
            f'<button data-share-url="{BASE}{date}/{first.lower()}-{last.lower()}-note">x</button>'
            f'<div>More {first} {last} News <a>Someone else (ankle) is out</a></div></li>')


def page(*items):
    return "<main><ul>" + "".join(items) + "</ul></main>"


class TestInjuryScan(unittest.TestCase):
    def test_regex_catches_real_injury_language_not_game_notes(self):
        self.assertTrue(scan.INJURY_WORDS.search("Deebo Samuel (hamstring) has been ruled out"))
        self.assertTrue(scan.INJURY_WORDS.search("exited in the third quarter"))
        self.assertTrue(scan.INJURY_WORDS.search("Jeanty (ankle, foot) is active"))
        self.assertFalse(scan.INJURY_WORDS.search("worked as the lead back in a crowded backfield"))

    def test_featured_players_skips_defenses(self):
        brief = [{"top_players_a": [{"full_name": "Deebo Samuel"}], "surprises_b": [{"full_name": "LA DST"}]}]
        self.assertEqual(scan.featured_players(brief), {"deebo samuel": "Deebo Samuel"})

    def test_scan_matches_subject_only_and_stops_at_since(self):
        pages = {
            1: page(item("2026-10-11", "Deebo", "Samuel", "Deebo Samuel (hamstring) was ruled out."),
                    item("2026-10-11", "George", "Kittle", "Kittle caught five passes.")),
            2: page(item("2026-10-01", "Deebo", "Samuel", "Old (knee) news.")),
        }
        names = {"deebo samuel": "Deebo Samuel", "george kittle": "George Kittle"}
        hits = scan.scan(names, "2026-10-08", fetch=lambda p: pages.get(p, page()))
        self.assertEqual([(h["player"], h["date"]) for h in hits], [("Deebo Samuel", "2026-10-11")])


if __name__ == "__main__":
    unittest.main()
