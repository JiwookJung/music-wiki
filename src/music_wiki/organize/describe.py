from __future__ import annotations

from music_wiki.core.encoding import recover_text
from music_wiki.core.store import Store
from music_wiki.external.local_llm import LocalLLMClient

DESCRIBE_SYSTEM = (
    "너는 음악 큐레이터다. 주어진 메타데이터만으로 한국어 2~4문장의 앨범 소개를 쓴다. "
    "장르·분위기·감상 포인트 중심으로 서술하고, 발매연도·인물사·수상 등 확인 불가한 "
    "사실은 단정하지 않는다. 모르면 추측하지 말고 음악적 인상만 쓴다. "
    "머리말이나 따옴표 없이 본문만 출력한다."
)


def _prompt(artist: str, album: str, bucket: str | None, genres: list[str],
            titles: list[str]) -> str:
    tags = ", ".join((recover_text(g) or "") for g in genres) or "(없음)"
    sample = "; ".join(titles[:8]) or "(없음)"
    return (f"아티스트: {artist}\n앨범: {album}\n장르 버킷: {bucket or '미정'}\n"
            f"장르 태그: {tags}\n수록곡 일부: {sample}\n이 앨범을 한국어로 소개해줘.")


def describe_albums(store: Store, client: LocalLLMClient, *,
                    force: bool = False, limit: int | None = None) -> int:
    n = 0
    for artist in store.iter_artists():
        for album in store.albums_for_artist(artist.id):
            if limit is not None and n >= limit:
                return n
            if album.description and not force:
                continue
            titles = [t.title for t in store.tracks_for_album(album.id)]
            user = _prompt(artist.name, album.title, album.genre_bucket,
                           album.genres, titles)
            try:
                text = client.complete(DESCRIBE_SYSTEM, user)
                text = (text or "").strip()
                if not text:
                    continue
                store.set_album_description(album.id, text, f"llm:{client.model}")
                n += 1
            except Exception:
                continue   # per-album isolation: one failure does not abort the rest
    return n
