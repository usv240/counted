"""Read-aloud: the packet becomes plain sentences, long text is split under Polly's limit, and the endpoint is capped."""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from counted import budget, speech
from counted.service import api

PACKET = json.loads((Path(__file__).resolve().parents[1] / "web/recorded/oxygen.json").read_text(encoding="utf-8"))[
    "documents"]["family_packet"]


def test_packet_becomes_plain_sentences():
    text = speech.speakable(PACKET, "en")
    for mark in ("#", "[ ]", "**", "> ", "__"):
        assert mark not in text
    assert "your loved one, who died on 2021-02-17" in text  # the fill-in blank is spoken, not skipped
    assert "Death certificate, OR the signed certifier statement" in text
    assert all(line[-1] in ".!?:;" for line in text.splitlines())


def test_spanish_blank_is_spanish():
    assert "su ser querido" in speech.speakable("Apelo la decisión para __________, quien falleció.", "es")


def test_long_text_is_split_under_the_limit():
    text = " ".join(f"Sentence number {i} is here." for i in range(600))
    parts = speech.chunks(text)
    assert len(parts) > 1 and all(len(p) <= speech.MAX_CHARS for p in parts)
    assert " ".join(parts) == text


class FakePolly:
    def __init__(self):
        self.calls = []

    def synthesize_speech(self, **kw):
        self.calls.append(kw)
        return {"AudioStream": io.BytesIO(b"ID3fake-mp3")}


def test_synthesize_uses_the_family_language():
    polly = FakePolly()
    assert speech.synthesize("Hola. Lo siento mucho.", "es", client=polly).startswith(b"ID3")
    assert polly.calls[0]["VoiceId"] == "Lupe" and polly.calls[0]["LanguageCode"] == "es-US"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(speech, "synthesize", lambda text, lang: b"ID3" + lang.encode())  # no Polly call
    api._hits.clear()
    return TestClient(api.app)


def test_speak_endpoint_returns_mp3(client):
    r = client.post("/v1/speak", json={"text": PACKET, "language": "es"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3es"


def test_speak_rejects_other_languages_and_empty_text(client):
    assert client.post("/v1/speak", json={"text": PACKET, "language": "fr"}).status_code == 400
    assert client.post("/v1/speak", json={"text": "## \n- [ ] ", "language": "en"}).status_code == 400


def test_speak_has_its_own_daily_cap(client, monkeypatch):
    monkeypatch.setitem(budget.LIMITS, "speech", 1)
    monkeypatch.setitem(budget._used, "speech", 0)
    assert client.post("/v1/speak", json={"text": PACKET}).status_code == 200
    r = client.post("/v1/speak", json={"text": PACKET})
    assert r.status_code == 429 and "read-aloud" in r.json()["detail"]


def test_rate_limits_are_per_endpoint(client):
    from types import SimpleNamespace
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="1.2.3.4"))
    for _ in range(30):
        api.rate_limit(req, per_hour=200, bucket="interview")
    api.rate_limit(req, per_hour=30, bucket="assess")  # interview turns don't use up assessments


def test_a_spoofed_forwarded_header_does_not_reset_the_limit(client):
    from fastapi import HTTPException
    from types import SimpleNamespace
    for i in range(3):  # the client invents a new address each time; the load balancer appends the real one last
        api.rate_limit(SimpleNamespace(headers={"x-forwarded-for": f"10.0.0.{i}, 203.0.113.7"}, client=None),
                       per_hour=3, bucket="t")
    with pytest.raises(HTTPException):
        api.rate_limit(SimpleNamespace(headers={"x-forwarded-for": "10.9.9.9, 203.0.113.7"}, client=None),
                       per_hour=3, bucket="t")
