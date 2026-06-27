import json

from music_wiki.external.local_llm import OpenAICompatibleLLMClient


def _fake_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_complete_builds_payload_and_extracts_content():
    seen = {}

    def fake_fetch(url, payload):
        seen["url"] = url
        seen["payload"] = payload
        return _fake_response("hello")

    client = OpenAICompatibleLLMClient("http://localhost:1234/v1", "qwen3-14b",
                                       fetch=fake_fetch)
    out = client.complete("SYS", "USER")
    assert out == "hello"
    assert seen["url"] == "http://localhost:1234/v1/chat/completions"
    assert seen["payload"]["model"] == "qwen3-14b"
    assert seen["payload"]["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert "response_format" not in seen["payload"]   # no schema → no response_format


def test_complete_passes_json_schema_as_response_format():
    seen = {}

    def fake_fetch(url, payload):
        seen["payload"] = payload
        return _fake_response('{"bucket": "재즈"}')

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=fake_fetch)
    schema = {"type": "object", "properties": {"bucket": {"type": "string"}}}
    out = client.complete("S", "U", json_schema=schema)
    assert json.loads(out) == {"bucket": "재즈"}
    assert seen["payload"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "result", "schema": schema},
    }


def test_complete_caches_by_prompt(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url, payload):
        calls["n"] += 1
        return _fake_response("cached-value")

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=fake_fetch,
                                       cache_dir=str(tmp_path))
    a = client.complete("S", "U")
    b = client.complete("S", "U")   # identical → served from disk cache
    assert a == b == "cached-value"
    assert calls["n"] == 1


def test_complete_does_not_cache_on_fetch_error(tmp_path):
    def boom(url, payload):
        raise RuntimeError("connection refused")

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=boom,
                                       cache_dir=str(tmp_path))
    try:
        client.complete("S", "U")
        assert False, "expected exception to propagate"
    except RuntimeError:
        pass
    assert list(tmp_path.glob("*.json")) == []   # nothing cached


def test_different_schema_is_a_cache_miss(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url, payload):
        calls["n"] += 1
        return {"choices": [{"message": {"role": "assistant", "content": "v"}}]}

    client = OpenAICompatibleLLMClient("http://x/v1", "m", fetch=fake_fetch,
                                       cache_dir=str(tmp_path))
    client.complete("S", "U", json_schema={"a": 1})
    client.complete("S", "U", json_schema={"a": 2})   # different schema → miss
    assert calls["n"] == 2
    # reordered keys are the SAME canonical schema → cache hit, no new fetch
    client.complete("S", "U", json_schema={"b": 1, "a": 1})
    client.complete("S", "U", json_schema={"a": 1, "b": 1})
    assert calls["n"] == 3
