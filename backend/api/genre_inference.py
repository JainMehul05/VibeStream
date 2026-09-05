"""Genre inference for tracks when Deezer doesn't provide genre directly.

Provides a lightweight, cached genre inference mechanism based on:
1. Static artist-to-genre mapping (built from known data)
2. Track title/album keyword matching (fallback)
3. Extensible for external API integration (Last.fm, MusicBrainz)
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Known artist-to-genre mappings (subset of major artists)
# In production, this would be loaded from a larger dataset or external API
ARTIST_GENRE_MAP = {
    # Pop
    "taylor swift": "pop",
    "ed sheeran": "pop",
    "dua lipa": "pop",
    "ariana grande": "pop",
    "justin bieber": "pop",
    "selena gomez": "pop",
    "katy perry": "pop",
    "lady gaga": "pop",
    "bruno mars": "pop",
    "miley cyrus": "pop",
    "shawn mendes": "pop",
    "camila cabello": "pop",
    "billie eilish": "pop",
    "olivia rodrigo": "pop",
    "harry styles": "pop",
    "the weeknd": "pop",
    "post malone": "pop",
    "justin timberlake": "pop",
    "beyonce": "pop",
    "rihanna": "pop",
    "adele": "pop",
    "sia": "pop",
    "katy perry": "pop",
    "maroon 5": "pop",
    "one direction": "pop",
    "jonas brothers": "pop",
    "backstreet boys": "pop",
    "nsync": "pop",
    "britney spears": "pop",
    "christina aguilera": "pop",

    # Hip Hop / Rap
    "drake": "hip hop",
    "kanye west": "hip hop",
    "kendrick lamar": "hip hop",
    "j. cole": "hip hop",
    "travis scott": "hip hop",
    "lil wayne": "hip hop",
    "eminem": "hip hop",
    "jay-z": "hip hop",
    "nicki minaj": "hip hop",
    "cardi b": "hip hop",
    "megan thee stallion": "hip hop",
    "doja cat": "hip hop",
    "lil nas x": "hip hop",
    "tyler the creator": "hip hop",
    "a$ap rocky": "hip hop",
    "future": "hip hop",
    "young thug": "hip hop",
    "gunna": "hip hop",
    "lil baby": "hip hop",
    "21 savage": "hip hop",
    "metro boomin": "hip hop",

    # R&B / Soul
    "the weeknd": "r&b",
    "sza": "r&b",
    "h.e.r.": "r&b",
    "daniel caesar": "r&b",
    "giveon": "r&b",
    "brent faiyaz": "r&b",
    "frank ocean": "r&b",
    "miguel": "r&b",
    "usher": "r&b",
    "chris brown": "r&b",
    "beyonce": "r&b",
    "rihanna": "r&b",
    "alicia keys": "r&b",
    "john legend": "r&b",

    # Rock / Alternative
    "imagine dragons": "rock",
    "twenty one pilots": "rock",
    "panic! at the disco": "rock",
    "fall out boy": "rock",
    "paramore": "rock",
    "linkin park": "rock",
    "coldplay": "rock",
    "arctic monkeys": "rock",
    "the 1975": "rock",
    "foals": "rock",
    "tame impala": "rock",
    "arctic monkeys": "rock",
    "muse": "rock",
    "radiohead": "rock",
    "foo fighters": "rock",
    "red hot chili peppers": "rock",
    "nirvana": "rock",
    "queen": "rock",
    "the beatles": "rock",
    "led zeppelin": "rock",
    "pink floyd": "rock",
    "the rolling stones": "rock",

    # Electronic / Dance
    "calvin harris": "electronic",
    "david guetta": "electronic",
    "martin garrix": "electronic",
    "avicii": "electronic",
    "kygo": "electronic",
    "zedd": "electronic",
    "marshmello": "electronic",
    "the chainsmokers": "electronic",
    "diplo": "electronic",
    "skrillex": "electronic",
    "deadmau5": "electronic",
    "daft punk": "electronic",
    "disclosure": "electronic",
    "flume": "electronic",
    "odeza": "electronic",

    # Indie / Folk
    "bon iver": "indie",
    "vampire weekend": "indie",
    "fleet foxes": "indie",
    "mumford & sons": "indie",
    "the lumineers": "indie",
    "of monsters and men": "indie",
    "hozier": "indie",
    "lord huron": "indie",
    "pha": "indie",
    "sufjan stevens": "indie",
    "iron & wine": "indie",

    # Latin
    "bad bunny": "latin",
    "j balvin": "latin",
    "karol g": "latin",
    "rosalia": "latin",
    "ozuna": "latin",
    "anuel aa": "latin",
    "daddy yankee": "latin",
    "maluma": "latin",
    "shakira": "latin",
    "enrique iglesias": "latin",

    # Country
    "luke combs": "country",
    "morgan wallen": "country",
    "kane brown": "country",
    "chris stapleton": "country",
    "kelsea ballerini": "country",
    "maren morris": "country",
    "thomas rhett": "country",
    "luke bryan": "country",
    "blake shelton": "country",
    "carrie underwood": "country",
}

# Genre keywords for fallback matching from track title/album
GENRE_KEYWORDS = {
    "hip hop": ["hip hop", "hiphop", "rap", "trap", "drill"],
    "pop": ["pop", "dance pop", "electropop", "synthpop", "k-pop"],
    "rock": ["rock", "alternative", "indie rock", "hard rock", "punk", "grunge", "metal"],
    "r&b": ["r&b", "rnb", "soul", "neo-soul", "contemporary r&b"],
    "electronic": ["electronic", "edm", "house", "techno", "trance", "dubstep", "ambient", "downtempo"],
    "latin": ["latin", "reggaeton", "bachata", "merengue", "cumbia", "salsa"],
    "country": ["country", "country pop", "folk country", "americana"],
    "indie": ["indie", "indie pop", "indie folk", "dream pop", "lo-fi"],
    "jazz": ["jazz", "smooth jazz", "bebop", "fusion"],
    "classical": ["classical", "orchestral", "symphony", "concerto"],
    "blues": ["blues", "blues rock", "delta blues"],
    "folk": ["folk", "folk rock", "singer-songwriter", "acoustic"],
    "funk": ["funk", "disco", "nu-disco"],
    "reggae": ["reggae", "dub", "ska"],
}

# Cache for artist genre lookups
@lru_cache(maxsize=1000)
def _get_artist_genre_cached(artist_lower: str) -> Optional[str]:
    """Cached genre lookup for an artist."""
    return ARTIST_GENRE_MAP.get(artist_lower)


def infer_genre_from_artist(artist: Optional[str]) -> Optional[str]:
    """Infer genre from artist name using static mapping.

    Args:
        artist: Artist name (e.g., "Taylor Swift")

    Returns:
        Genre string or None if unknown
    """
    if not artist:
        return None

    artist_lower = artist.strip().lower()
    genre = _get_artist_genre_cached(artist_lower)
    if genre:
        return genre

    # Try partial matching for featured artists (e.g., "Post Malone, Swae Lee")
    for known_artist, genre in ARTIST_GENRE_MAP.items():
        if known_artist in artist_lower or artist_lower in known_artist:
            return genre

    return None


def infer_genre_from_keywords(text: str) -> Optional[str]:
    """Infer genre from track title/album keywords.

    Args:
        text: Text to search (title, album, etc.)

    Returns:
        Genre string or None if no keywords match
    """
    if not text:
        return None

    text_lower = text.lower()
    for genre, keywords in GENRE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return genre
    return None


def infer_genre(track: dict) -> Optional[str]:
    """Infer genre for a track using all available signals.

    Priority:
    1. Artist mapping (highest confidence)
    2. Title/album keywords (lower confidence)

    Args:
        track: Track dict with keys: artist, name, album

    Returns:
        Genre string or None
    """
    # Try artist first
    artist = track.get("artist")
    if artist:
        genre = infer_genre_from_artist(artist)
        if genre:
            return genre

    # Fallback to title/album keywords
    name = track.get("name", "")
    album = track.get("album", "")
    for text in (name, album):
        genre = infer_genre_from_keywords(text)
        if genre:
            return genre

    return None


def get_genre_confidence(track: dict) -> float:
    """Get confidence score for genre inference (0.0 to 1.0)."""
    artist = track.get("artist", "")
    artist_lower = artist.strip().lower() if artist else ""

    if artist_lower in ARTIST_GENRE_MAP:
        return 0.9  # High confidence from direct artist mapping

    # Check partial artist match
    for known_artist in ARTIST_GENRE_MAP:
        if known_artist in artist_lower or artist_lower in known_artist:
            return 0.7

    # Keyword-based
    name = track.get("name", "")
    album = track.get("album", "")
    for text in (name, album):
        if infer_genre_from_keywords(text):
            return 0.5

    return 0.0


def clear_genre_cache():
    """Clear the LRU cache (useful for testing or when updating mappings)."""
    _get_artist_genre_cached.cache_clear()


__all__ = [
    "infer_genre",
    "infer_genre_from_artist",
    "infer_genre_from_keywords",
    "get_genre_confidence",
    "clear_genre_cache",
    "ARTIST_GENRE_MAP",
    "GENRE_KEYWORDS",
]