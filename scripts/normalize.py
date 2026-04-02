"""
Team abbreviation normalization and shared utilities.

Canonical abbreviations follow nflverse conventions.
ESPN sometimes uses different abbreviations that we map here.
"""

import re

# Map non-standard abbreviations to canonical nflverse form
ABBREV_ALIASES: dict[str, str] = {
    "WSH": "WAS",
    "LAR": "LA",   # ESPN uses LAR, nflverse uses LA for Rams
    # ESPN occasionally uses different codes
    "SFO": "SF",
    "TBB": "TB",
    "GNB": "GB",
    "NWE": "NE",
    "KAN": "KC",
    "NOR": "NO",
    "SDG": "SD",
}

# All 32 canonical team abbreviations (nflverse convention)
TEAMS = frozenset([
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
])


def normalize_team(abbrev: str) -> str:
    """Normalize a team abbreviation to canonical nflverse form."""
    upper = abbrev.strip().upper()
    return ABBREV_ALIASES.get(upper, upper)


def make_game_id(season: int, week: int, away: str, home: str) -> str:
    """Build a game ID: {season}_{week:02d}_{away}_{home}."""
    return f"{season}_{week:02d}_{away}_{home}"


def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug."""
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))
