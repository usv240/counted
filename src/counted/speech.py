"""Read the family packet aloud with Amazon Polly, in English or Spanish.

Many of the relatives Counted is for are older, grieving, or more at ease listening than reading English paperwork.
The packet is markdown with checkboxes and a fill-in appeal letter; this turns it into sentences a voice can say,
then synthesizes it with a neural voice in the family's language.
"""

from __future__ import annotations

import re

import boto3

from .config import REGION

VOICES = {"en": ("Ruth", "en-US"), "es": ("Lupe", "es-US")}
BLANK = {"en": "your loved one", "es": "su ser querido"}
MAX_CHARS = 2800  # Polly's limit is 3,000 billed characters per request

_STEPS = [
    (re.compile(r"^\s*\|.*\|\s*$", re.M), ""),  # table rows
    (re.compile(r"\[[ xX]?\]\s*"), ""),  # checkboxes
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links: keep the words
    (re.compile(r"https?://\S+"), ""),
    (re.compile(r"[#*>`|]+"), ""),
    (re.compile(r"(?m)^\s*[-•]\s+"), ""),  # bullets
    (re.compile(r"[ \t]+"), " "),
]


def speakable(markdown: str, language: str = "en") -> str:
    """Markdown packet -> plain sentences. Blanks become words, and every line ends as a sentence."""
    text = re.sub(r"_{3,}", BLANK.get(language, BLANK["en"]), markdown)
    for pattern, repl in _STEPS:
        text = pattern.sub(repl, text)
    text = re.sub(r"(?<!_)_(?!_)", "", text)  # leftover italics markers
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln if ln[-1] in ".!?:;" else ln + "." for ln in lines]
    return "\n".join(lines)


def chunks(text: str, limit: int = MAX_CHARS) -> list[str]:
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sentence) + 1 > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur} {sentence}".strip()
        while len(cur) > limit:  # one runaway sentence
            out.append(cur[:limit])
            cur = cur[limit:]
    return out + ([cur] if cur else [])


def synthesize(markdown: str, language: str = "en", client=None) -> bytes:
    voice, code = VOICES.get(language, VOICES["en"])
    polly = client or boto3.client("polly", region_name=REGION)
    audio = b""
    for part in chunks(speakable(markdown, language)):
        res = polly.synthesize_speech(Text=part, VoiceId=voice, LanguageCode=code, Engine="neural",
                                      OutputFormat="mp3", SampleRate="24000")
        audio += res["AudioStream"].read()  # MP3 frames concatenate cleanly
    return audio
