from __future__ import annotations

from music_wiki.core.store import Store

from .buckets import UNCLASSIFIED, classify_by_rules


def enrich_genres(store: Store, mb_client, *, threshold: float = 0.8) -> int:
    """For non-manual, low-confidence albums, look up MusicBrainz genres and
    re-bucket via the rule mapper. Writes source='musicbrainz' only when the
    looked-up result is a real bucket and more confident than the current one."""
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            conf = album.genre_confidence if album.genre_confidence is not None else 0.0
            if conf >= threshold and album.genre_bucket not in (None, UNCLASSIFIED):
                continue
            mb_genres = mb_client.lookup_genres(artist.name, album.title)
            if not mb_genres:
                continue
            res = classify_by_rules(mb_genres, artist.name, [], album=album.title)
            if res.bucket != UNCLASSIFIED and res.confidence > conf:
                store.set_album_genre(album.id, res.bucket, res.confidence, "musicbrainz")
                n += 1
    return n
