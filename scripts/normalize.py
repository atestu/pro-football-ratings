"""
Team abbreviation normalization and shared utilities.

Canonical abbreviations follow nflverse conventions.
ESPN sometimes uses different abbreviations that we map here.
"""

import re

# Map non-standard abbreviations to canonical nflverse form
ABBREV_ALIASES: dict[str, str] = {
    "WSH": "WAS",
    "LAR": "LA",   # ESPN/Fantasy Nerds use LAR, nflverse uses LA for Rams
    "JAC": "JAX",  # Fantasy Nerds uses JAC, nflverse uses JAX
    # ESPN occasionally uses different codes
    "SFO": "SF",
    "TBB": "TB",
    "GNB": "GB",
    "NWE": "NE",
    "KAN": "KC",
    "NOR": "NO",
    "SDG": "SD",
}

# Map team display names (nicknames) to canonical nflverse abbreviations
TEAM_NICK_TO_ABBREV: dict[str, str] = {
    "Cardinal": "ARI",
    "Cardinals": "ARI",
    "Falcons": "ATL",
    "Ravens": "BAL",
    "Bills": "BUF",
    "Panthers": "CAR",
    "Bears": "CHI",
    "Bengals": "CIN",
    "Browns": "CLE",
    "Cowboys": "DAL",
    "Broncos": "DEN",
    "Lions": "DET",
    "Packers": "GB",
    "Texans": "HOU",
    "Col": "IND",
    "Cols": "IND",
    "Colts": "IND",
    "Jaguars": "JAX",
    "Chiefs": "KC",
    "Rams": "LA",
    "Chargers": "LAC",
    "Raiders": "LV",
    "Dolphin": "MIA",
    "Dolphins": "MIA",
    "Vikings": "MIN",
    "Patriots": "NE",
    "Saints": "NO",
    "Giants": "NYG",
    "Jets": "NYJ",
    "Eagles": "PHI",
    "Steelers": "PIT",
    "Seahawks": "SEA",
    "49ers": "SF",
    "Buccaneers": "TB",
    "Titans": "TEN",
    "Commanders": "WAS",
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


def normalize_team_name(name: str) -> str:
    """Resolve a team display name (nickname) to a canonical nflverse abbreviation.

    Raises KeyError if the name is not recognized.
    """
    return TEAM_NICK_TO_ABBREV[name.strip()]


def make_game_id(season: int, week: int, away: str, home: str) -> str:
    """Build a game ID: {season}_{week:02d}_{away}_{home}."""
    return f"{season}_{week:02d}_{away}_{home}"


def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug."""
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))
