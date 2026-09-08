"""Canonical NFL team abbreviations.

Every source spells some team codes its own way: ESPN uses "WSH" for
Washington and "LV"/"JAX" like the reference data, Yahoo returns title-case
codes ("Was", "Bal", "Sea"), and Sleeper and the rankings provider use "WAS"
(and the provider has been seen using "LA" for the Rams). Left unreconciled,
one real NFL team splits into several `players.nfl_team` values and stops
joining to the per-team reference tables — `nfl_team_byes`,
`nfl_team_playoff_sos`, `nfl_team_schedule`, `nfl_team_implied_totals` — which
each key off a single spelling. That's what made a rostered Commanders player
show up as separate "WAS" (has exposure, no bye week) and "WSH" (no exposure)
entries on the Exposure page. See DECISIONS.md.

`canonical_team_code()` collapses every known spelling onto the codes those
reference tables use (Washington -> "WSH", Rams -> "LAR", etc.). Apply it
wherever an external team code is about to be written to the database.
"""

# Non-canonical spellings mapped onto the code the reference tables use.
# Anything already canonical passes through untouched after upper-casing, so
# only the exceptions belong here.
_TEAM_CODE_ALIASES = {
    "WAS": "WSH",  # Sleeper / rankings provider -> ESPN + reference-table code
    "LA": "LAR",   # rankings provider's Rams code
    "STL": "LAR",  # Rams, pre-2016 relocation
    "SD": "LAC",   # Chargers, pre-2017 relocation
    "OAK": "LV",   # Raiders, pre-2020 relocation
    "JAC": "JAX",  # occasional alternate Jaguars code
    "ARZ": "ARI",  # occasional alternate Cardinals code
}

# Values that mean "no NFL team" across the sources (free agent, empty, the
# literal string "None" from an earlier bug).
_NULL_TEAM_CODES = {"", "FA", "NONE", "NULL", "0"}


def canonical_team_code(raw: str | None) -> str | None:
    """Return the canonical abbreviation for `raw`, or None if it names no team.

    Case-insensitive; surrounding whitespace is ignored. An unrecognised code
    passes through upper-cased rather than being dropped, so a newly relocated
    or renamed team still lands somewhere sensible until the alias map catches
    up with it.
    """
    if raw is None:
        return None
    code = raw.strip().upper()
    if code in _NULL_TEAM_CODES:
        return None
    return _TEAM_CODE_ALIASES.get(code, code)
