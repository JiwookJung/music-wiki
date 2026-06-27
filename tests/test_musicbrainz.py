from music_wiki.external.musicbrainz import HttpMusicBrainzClient, parse_genres

_MB_RESPONSE = {
    "release-groups": [
        {"title": "Waltz for Debby",
         "genres": [{"name": "jazz"}, {"name": "cool jazz"}],
         "tags": [{"name": "piano jazz"}]},
        {"title": "other"},
    ]
}


def test_parse_genres_first_match_only():
    assert parse_genres(_MB_RESPONSE) == ["jazz", "cool jazz", "piano jazz"]
    assert parse_genres({"release-groups": []}) == []
    assert parse_genres({}) == []


def test_lookup_uses_injected_fetch_and_throttles():
    calls = {"fetch": 0, "sleep": []}

    def fake_fetch(url):
        calls["fetch"] += 1
        assert "Waltz" in url and "Bill" in url
        return _MB_RESPONSE

    client = HttpMusicBrainzClient("ua/1.0", fetch=fake_fetch,
                                   sleep=lambda s: calls["sleep"].append(s))
    genres = client.lookup_genres("Bill Evans", "Waltz for Debby")
    assert genres == ["jazz", "cool jazz", "piano jazz"]
    assert calls["fetch"] == 1


def test_lookup_empty_inputs_and_fetch_error_return_empty():
    def boom(url):
        raise RuntimeError("network down")

    client = HttpMusicBrainzClient("ua/1.0", fetch=boom, sleep=lambda s: None)
    assert client.lookup_genres("", "Album") == []        # no fetch attempted
    assert client.lookup_genres("Artist", "Album") == []  # fetch error → []


def test_lookup_caches_to_disk(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        return _MB_RESPONSE

    client = HttpMusicBrainzClient("ua/1.0", fetch=fake_fetch, sleep=lambda s: None,
                                   cache_dir=str(tmp_path))
    a = client.lookup_genres("Bill Evans", "Waltz for Debby")
    b = client.lookup_genres("Bill Evans", "Waltz for Debby")   # served from cache
    assert a == b == ["jazz", "cool jazz", "piano jazz"]
    assert calls["n"] == 1


def test_throttle_sleeps_between_consecutive_fetches():
    slept = []
    client = HttpMusicBrainzClient(
        "ua/1.0", fetch=lambda url: _MB_RESPONSE,
        sleep=lambda s: slept.append(s), min_interval=1.0,
    )
    client.lookup_genres("A", "X")   # first call: _last starts at 0.0 → no sleep
    client.lookup_genres("B", "Y")   # second call within the interval → must sleep
    assert len(slept) == 1
    assert 0 < slept[0] <= 1.0
