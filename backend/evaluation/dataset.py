"""Synthetic evaluation dataset generation for VibeStream.

Since VibeStream has no production user data, we generate a synthetic but
realistic dataset that mimics real user behavior patterns:
- Users have latent taste profiles (preferred genres, artists, eras)
- Mood sequences follow realistic transitions (Markov-like)
- Feedback signals (like/unlike) correlate with latent preferences
- Cold-start users have no history

This is explicitly labeled OFFLINE SYNTHETIC EVALUATION.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta, timezone

import numpy as np


# Canonical emotions matching the system
EMOTIONS = ["sadness", "joy", "love", "anger", "fear", "neutral"]

# Genre catalog (Deezer-like)
GENRES = [
    "pop", "rock", "hip-hop", "electronic", "r&b", "country", "jazz",
    "classical", "folk", "reggae", "blues", "metal", "punk", "indie",
    "latin", "k-pop", "ambient", "soundtrack"
]

# Artist pools per genre (simplified)
ARTISTS_BY_GENRE = {
    "pop": ["Taylor Swift", "Ed Sheeran", "Dua Lipa", "The Weeknd", "Ariana Grande", "Justin Bieber", "Billie Eilish", "Olivia Rodrigo"],
    "rock": ["Queen", "The Beatles", "Led Zeppelin", "Pink Floyd", "Nirvana", "Radiohead", "Arctic Monkeys", "Imagine Dragons"],
    "hip-hop": ["Drake", "Kendrick Lamar", "J. Cole", "Travis Scott", "Post Malone", "Eminem", "Kanye West", "Lil Wayne"],
    "electronic": ["Daft Punk", "Calvin Harris", "Avicii", "Marshmello", "The Chainsmokers", "Zedd", "Kygo", "Martin Garrix"],
    "r&b": ["Beyoncé", "Rihanna", "SZA", "H.E.R.", "Daniel Caesar", "Frank Ocean", "The Weeknd", "Bruno Mars"],
    "country": ["Luke Combs", "Morgan Wallen", "Carrie Underwood", "Chris Stapleton", "Kacey Musgraves", "Taylor Swift", "Zach Bryan", "Lainey Wilson"],
    "jazz": ["Miles Davis", "John Coltrane", "Billie Holiday", "Ella Fitzgerald", "Louis Armstrong", "Dave Brubeck", "Chet Baker", "Herbie Hancock"],
    "classical": ["Ludwig van Beethoven", "Wolfgang Mozart", "Johann Bach", "Pyotr Tchaikovsky", "Frédéric Chopin", "Antonio Vivaldi", "Claude Debussy", "Sergei Rachmaninoff"],
    "folk": ["Bob Dylan", "Simon & Garfunkel", "Joni Mitchell", "Nick Drake", "Bon Iver", "Fleet Foxes", "Sufjan Stevens", "Iron & Wine"],
    "reggae": ["Bob Marley", "Peter Tosh", "Jimmy Cliff", "Burning Spear", "Toots and the Maytals", "Steel Pulse", "Black Uhuru", "Damian Marley"],
    "blues": ["B.B. King", "Muddy Waters", "Stevie Ray Vaughan", "Eric Clapton", "Robert Johnson", "Howlin' Wolf", "Buddy Guy", "Albert King"],
    "metal": ["Metallica", "Iron Maiden", "Black Sabbath", "Slayer", "Megadeth", "Judas Priest", "Pantera", "System of a Down"],
    "punk": ["The Ramones", "Sex Pistols", "The Clash", "Green Day", "Blink-182", "Bad Religion", "NOFX", "Rancid"],
    "indie": ["Tame Impala", "Vampire Weekend", "Arcade Fire", "The Strokes", "Phoenix", "Mac DeMarco", "Beach House", "Alvvays"],
    "latin": ["Bad Bunny", "J Balvin", "Rosalía", "Karol G", "Ozuna", "Maluma", "Shakira", "Marc Anthony"],
    "k-pop": ["BTS", "BLACKPINK", "TWICE", "Stray Kids", "NewJeans", "IVE", "SEVENTEEN", "ENHYPEN"],
    "ambient": ["Brian Eno", "Aphex Twin", "Tycho", "Boards of Canada", "William Basinski", "Stars of the Lid", "Hiroshi Yoshimura", "Gas"],
    "soundtrack": ["Hans Zimmer", "John Williams", "Ennio Morricone", "Howard Shore", "Joe Hisaishi", "Ludovico Einaudi", "Yann Tiersen", "Ramin Djawadi"],
}

# Era buckets
ERAS = ["pre1960", "1960s", "1970s", "1980s", "1990s", "2000s", "2010s"]

# Emotion -> genre affinity (what genres suit what moods)
EMOTION_GENRE_AFFINITY = {
    "sadness": {"pop": 0.3, "r&b": 0.8, "folk": 0.7, "classical": 0.6, "blues": 0.7, "ambient": 0.6, "soundtrack": 0.5},
    "joy": {"pop": 0.9, "electronic": 0.8, "latin": 0.7, "k-pop": 0.7, "rock": 0.5, "funk": 0.6},
    "love": {"r&b": 0.9, "pop": 0.7, "folk": 0.6, "jazz": 0.6, "soundtrack": 0.5},
    "anger": {"rock": 0.8, "metal": 0.9, "punk": 0.8, "hip-hop": 0.6},
    "fear": {"ambient": 0.7, "classical": 0.6, "soundtrack": 0.7, "electronic": 0.4},
    "neutral": {"pop": 0.5, "rock": 0.5, "electronic": 0.5, "hip-hop": 0.5, "indie": 0.5},
}


@dataclass
class Track:
    """Synthetic track with metadata."""
    track_id: str
    name: str
    artist: str
    genre: str
    era: str
    popularity: int  # 0-100
    release_date: str  # YYYY-MM-DD
    duration_ms: int


@dataclass
class UserProfile:
    """Synthetic user with latent preferences."""
    user_id: str
    # Latent preferences (ground truth for evaluation)
    genre_prefs: dict[str, float] = field(default_factory=dict)  # genre -> weight [-1, 1]
    artist_prefs: dict[str, float] = field(default_factory=dict)
    era_prefs: dict[str, float] = field(default_factory=dict)
    # Interaction history
    interactions: list[dict] = field(default_factory=list)  # {track_id, emotion, signal, timestamp}
    mood_history: list[str] = field(default_factory=list)


@dataclass
class EvaluationDataset:
    """Complete evaluation dataset."""
    users: list[UserProfile]
    tracks: list[Track]
    track_catalog: dict[str, Track]  # track_id -> Track
    # Ground truth: for each user, emotion -> set of relevant track_ids
    relevance: dict[str, dict[str, set[str]]]
    metadata: dict = field(default_factory=dict)

    def get_relevant_tracks(self, user_id: str, emotion: str) -> set[str]:
        """Get ground-truth relevant tracks for user+emotion."""
        return self.relevance.get(user_id, {}).get(emotion, set())


class SyntheticDatasetGenerator:
    """Generates synthetic but realistic evaluation datasets."""

    def __init__(
        self,
        n_users: int = 1000,
        n_tracks: int = 5000,
        seed: int = 42,
        interaction_sparsity: float = 0.01,
    ):
        self.n_users = n_users
        self.n_tracks = n_tracks
        self.seed = seed
        self.interaction_sparsity = interaction_sparsity
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

    def generate(self) -> EvaluationDataset:
        """Generate complete dataset."""
        print(f"Generating synthetic dataset: {self.n_users} users, {self.n_tracks} tracks...")
        tracks = self._generate_tracks()
        track_catalog = {t.track_id: t for t in tracks}
        users = self._generate_users(tracks)
        relevance = self._compute_relevance(users, tracks)
        metadata = {
            "generator": "SyntheticDatasetGenerator",
            "seed": self.seed,
            "n_users": self.n_users,
            "n_tracks": self.n_tracks,
            "interaction_sparsity": self.interaction_sparsity,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "label": "OFFLINE SYNTHETIC EVALUATION",
        }
        return EvaluationDataset(
            users=users,
            tracks=tracks,
            track_catalog=track_catalog,
            relevance=relevance,
            metadata=metadata,
        )

    def _generate_tracks(self) -> list[Track]:
        """Generate track catalog with realistic distributions."""
        tracks = []
        # Distribute tracks across genres
        tracks_per_genre = max(1, self.n_tracks // len(GENRES))
        track_id = 0
        for genre in GENRES:
            artists = ARTISTS_BY_GENRE.get(genre, ["Unknown Artist"])
            for _ in range(tracks_per_genre):
                if track_id >= self.n_tracks:
                    break
                artist = self.rng.choice(artists)
                era = self.rng.choice(ERAS)
                # Era -> year
                era_year_map = {
                    "pre1960": (1900, 1959),
                    "1960s": (1960, 1969),
                    "1970s": (1970, 1979),
                    "1980s": (1980, 1989),
                    "1990s": (1990, 1999),
                    "2000s": (2000, 2009),
                    "2010s": (2010, 2023),
                }
                year_range = era_year_map[era]
                year = self.rng.randint(*year_range)
                month = self.rng.randint(1, 12)
                day = self.rng.randint(1, 28)
                popularity = int(self.np_rng.beta(2, 5) * 100)  # Skewed toward lower popularity
                duration_ms = self.rng.randint(120_000, 420_000)  # 2-7 minutes
                track = Track(
                    track_id=f"track_{track_id:06d}",
                    name=f"{genre.title()} Track {track_id}",
                    artist=artist,
                    genre=genre,
                    era=era,
                    popularity=popularity,
                    release_date=f"{year:04d}-{month:02d}-{day:02d}",
                    duration_ms=duration_ms,
                )
                tracks.append(track)
                track_id += 1
        # Shuffle to avoid genre clustering
        self.rng.shuffle(tracks)
        return tracks[:self.n_tracks]

    def _generate_users(self, tracks: list[Track]) -> list[UserProfile]:
        """Generate users with latent preferences and interaction history."""
        users = []
        for u in range(self.n_users):
            user_id = f"user_{u:05d}"
            # Latent genre preferences (Dirichlet for diversity)
            genre_weights = self.np_rng.dirichlet(np.ones(len(GENRES)) * 0.5)
            genre_prefs = {g: float(w * 2 - 1) for g, w in zip(GENRES, genre_weights)}  # [-1, 1]
            # Artist preferences (subset)
            n_fav_artists = self.rng.randint(3, 8)
            all_artists = list(set(t.artist for t in tracks))
            fav_artists = self.rng.sample(all_artists, min(n_fav_artists, len(all_artists)))
            artist_prefs = {a: self.rng.uniform(0.3, 1.0) for a in fav_artists}
            # Era preferences
            n_fav_eras = self.rng.randint(1, 3)
            fav_eras = self.rng.sample(ERAS, n_fav_eras)
            era_prefs = {e: self.rng.uniform(0.2, 0.8) for e in fav_eras}
            # Interaction history - create realistic distribution with cold users
            # 20% cold (0), 25% 1-5, 25% 5-20, 30% 20+
            user_type = self.rng.random()
            if user_type < 0.20:
                n_interactions = 0
            elif user_type < 0.45:
                n_interactions = self.rng.randint(1, 5)
            elif user_type < 0.70:
                n_interactions = self.rng.randint(6, 20)
            else:
                n_interactions = self.rng.randint(21, 100)
            interactions = []
            mood_history = []
            for _ in range(n_interactions):
                track = self.rng.choice(tracks)
                emotion = self.rng.choice(EMOTIONS)
                # Signal probability based on latent preference match
                signal_prob = 0.1  # Base
                signal_prob += genre_prefs.get(track.genre, 0) * 0.2
                signal_prob += artist_prefs.get(track.artist, 0) * 0.3
                signal_prob += era_prefs.get(track.era, 0) * 0.1
                signal_prob = max(0.01, min(0.9, signal_prob))
                signal = "like" if self.rng.random() < signal_prob else "unlike"
                # Emotion transition (simple Markov)
                if mood_history:
                    prev = mood_history[-1]
                    # Tend to stay in same mood or move to adjacent
                    if self.rng.random() < 0.6:
                        emotion = prev
                mood_history.append(emotion)
                interactions.append({
                    "track_id": track.track_id,
                    "emotion": emotion,
                    "signal": signal,
                    "timestamp": (datetime.now(timezone.utc) - timedelta(days=self.rng.randint(0, 365))).isoformat(),
                })
            users.append(UserProfile(
                user_id=user_id,
                genre_prefs=genre_prefs,
                artist_prefs=artist_prefs,
                era_prefs=era_prefs,
                interactions=interactions,
                mood_history=mood_history,
            ))
        return users

    def _compute_relevance(self, users: list[UserProfile], tracks: list[Track]) -> dict:
        """Compute ground-truth relevance: which tracks each user would like per emotion."""
        relevance = {}
        for user in users:
            user_relevance = {}
            for emotion in EMOTIONS:
                relevant = set()
                for track in tracks:
                    # Score based on latent preferences + emotion-genre affinity
                    score = 0.0
                    score += user.genre_prefs.get(track.genre, 0) * 0.4
                    score += user.artist_prefs.get(track.artist, 0) * 0.4
                    score += user.era_prefs.get(track.era, 0) * 0.2
                    # Emotion-genre affinity
                    affinity = EMOTION_GENRE_AFFINITY.get(emotion, {}).get(track.genre, 0)
                    score += affinity * 0.3
                    # Normalize and threshold
                    if score > 0.3:  # Threshold for "relevant"
                        relevant.add(track.track_id)
                user_relevance[emotion] = relevant
            relevance[user.user_id] = user_relevance
        return relevance


def create_synthetic_dataset(
    n_users: int = 1000,
    n_tracks: int = 5000,
    seed: int = 42,
) -> EvaluationDataset:
    """Convenience function to create a synthetic dataset."""
    generator = SyntheticDatasetGenerator(n_users=n_users, n_tracks=n_tracks, seed=seed)
    return generator.generate()


def split_dataset(
    dataset: EvaluationDataset,
    train_ratio: float = 0.8,
    seed: int = 42,
) -> tuple[EvaluationDataset, EvaluationDataset]:
    """Split dataset into train/test by user (no data leakage)."""
    rng = random.Random(seed)
    user_ids = [u.user_id for u in dataset.users]
    rng.shuffle(user_ids)
    split_idx = int(len(user_ids) * train_ratio)
    train_ids = set(user_ids[:split_idx])
    test_ids = set(user_ids[split_idx:])
    train_users = [u for u in dataset.users if u.user_id in train_ids]
    test_users = [u for u in dataset.users if u.user_id in test_ids]
    train_rel = {uid: rel for uid, rel in dataset.relevance.items() if uid in train_ids}
    test_rel = {uid: rel for uid, rel in dataset.relevance.items() if uid in test_ids}
    train = EvaluationDataset(
        users=train_users,
        tracks=dataset.tracks,
        track_catalog=dataset.track_catalog,
        relevance=train_rel,
        metadata={**dataset.metadata, "split": "train"},
    )
    test = EvaluationDataset(
        users=test_users,
        tracks=dataset.tracks,
        track_catalog=dataset.track_catalog,
        relevance=test_rel,
        metadata={**dataset.metadata, "split": "test"},
    )
    return train, test


__all__ = [
    "Track",
    "UserProfile",
    "EvaluationDataset",
    "SyntheticDatasetGenerator",
    "create_synthetic_dataset",
    "split_dataset",
    "EMOTIONS",
    "GENRES",
    "ARTISTS_BY_GENRE",
    "ERAS",
]