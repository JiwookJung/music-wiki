from __future__ import annotations

from music_wiki.core.store import Store

from .buckets import classify_by_rules


def classify_albums(store: Store) -> int:
    """Classify every album by rules, writing genre_bucket/confidence (source='rule').
    Albums already set by a human (genre_source == 'manual') are left untouched.
    Idempotent: re-running re-derives the same rule results."""
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            res = classify_by_rules(album.genres, artist.name, titles)
            store.set_album_genre(album.id, res.bucket, res.confidence, "rule")
            n += 1
    return n
