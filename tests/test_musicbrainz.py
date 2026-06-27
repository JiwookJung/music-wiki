from music_wiki.external.musicbrainz import (
    HttpMusicBrainzClient,
    first_release_group_mbid,
    parse_genres,
)

_SEARCH = {"release-groups": [{"id": "rg-123", "title": "Waltz for Debby"}]}
_LOOKUP = {
    "genres": [{"name": "jazz"}, {"name": "cool jazz"}],
    "tags": [{"name": "piano jazz"}],
}


def _fake_fetch(url):
    return _LOOKUP if "/release-group/rg-123" in url else _SEARCH


def test_parse_genres_from_lookup_response():
    assert parse_genres(_LOOKUP) == ["jazz", "cool jazz", "piano jazz"]
    assert parse_genres({}) == []
    assert parse_genres({"genres": [], "tags": []}) == []


def test_first_release_group_mbid():
    assert first_release_group_mbid(_SEARCH) == "rg-123"
    assert first_release_group_mbid({"release-groups": []}) is None
    assert first_release_group_mbid({}) is None


def test_lookup_does_search_then_lookup():
    calls = []

    def fetch(url):
        calls.append(url)
        return _fake_fetch(url)

    client = HttpMusicBrainzClient("ua/1.0", fetch=fetch, sleep=lambda s: None)
    genres = client.lookup_genres("Bill Evans", "Waltz for Debby")
    assert genres == ["jazz", "cool jazz", "piano jazz"]
    assert len(calls) == 2
    assert "query=" in calls[0]
    assert "/release-group/rg-123" in calls[1] and "inc=genres" in calls[1]


def test_lookup_empty_inputs_and_search_error_return_empty():
    def boom(url):
        raise RuntimeError("network down")

    client = HttpMusicBrainzClient("ua/1.0", fetch=boom, sleep=lambda s: None)
    assert client.lookup_genres("", "Album") == []
    assert client.lookup_genres("Artist", "Album") == []


def test_lookup_no_match_returns_empty():
    client = HttpMusicBrainzClient("ua/1.0", fetch=lambda u: {"release-groups": []},
                                   sleep=lambda s: None)
    assert client.lookup_genres("Nobody", "Nothing") == []


def test_lookup_caches_to_disk(tmp_path):
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        return _fake_fetch(url)

    client = HttpMusicBrainzClient("ua/1.0", fetch=fetch, sleep=lambda s: None,
                                   cache_dir=str(tmp_path))
    a = client.lookup_genres("Bill Evans", "Waltz for Debby")
    b = client.lookup_genres("Bill Evans", "Waltz for Debby")
    assert a == b == ["jazz", "cool jazz", "piano jazz"]
    assert calls["n"] == 2   # search+lookup once; second call from cache


def test_throttle_sleeps_between_search_and_lookup():
    slept = []
    client = HttpMusicBrainzClient("ua/1.0", fetch=_fake_fetch,
                                   sleep=lambda s: slept.append(s), min_interval=1.0)
    client.lookup_genres("Bill Evans", "Waltz for Debby")
    assert len(slept) == 1
    assert 0 < slept[0] <= 1.0
