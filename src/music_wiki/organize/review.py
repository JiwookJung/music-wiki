from __future__ import annotations

import csv

from music_wiki.core.store import Store

from .buckets import BUCKETS, UNCLASSIFIED, classify_by_rules

_FIELDS = ["album_id", "artist", "album", "proposed_bucket", "confidence", "source", "signals"]


def export_review(store: Store, out_path: str, threshold: float = 0.8) -> int:
    rows = []
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if album.genre_source == "manual":
                continue
            conf = album.genre_confidence if album.genre_confidence is not None else 0.0
            if conf >= threshold and album.genre_bucket not in (None, UNCLASSIFIED):
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            res = classify_by_rules(album.genres, artist.name, titles, album=album.title)
            rows.append({
                "album_id": album.id, "artist": artist.name, "album": album.title,
                "proposed_bucket": album.genre_bucket or UNCLASSIFIED,
                "confidence": f"{conf:.2f}", "source": album.genre_source or "",
                "signals": res.signals,
            })
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def import_review(store: Store, in_path: str) -> int:
    n = 0
    with open(in_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bucket = (row.get("proposed_bucket") or "").strip()
            if bucket not in BUCKETS and bucket != UNCLASSIFIED:
                continue
            try:
                album_id = int(row["album_id"])
            except (ValueError, KeyError, TypeError):
                continue
            store.set_album_genre(album_id, bucket, 1.0, "manual")
            n += 1
    return n
