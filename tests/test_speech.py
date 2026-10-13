from __future__ import annotations

import json

from src.speech.preprocess import (
    PronunciationRule,
    SpeechConfig,
    load_pronunciation_file,
    preprocess_for_speech,
)


def test_speech_text_differs_but_cleaned_untouched():
    cleaned = "Hello  world.  “Quoted” text."
    speech, info = preprocess_for_speech(cleaned, SpeechConfig())
    assert cleaned == "Hello  world.  “Quoted” text."  # input not mutated
    assert '"Quoted"' in speech


def test_code_policy_read_keeps_code():
    text = "Intro\n```python\nprint(1)\n```"
    speech, _ = preprocess_for_speech(text, SpeechConfig(code_block_policy="read"))
    assert "print(1)" in speech


def test_code_policy_skip_removes_code():
    text = "Intro\n```python\nprint(1)\n```\nOutro"
    speech, info = preprocess_for_speech(text, SpeechConfig(code_block_policy="skip"))
    assert "print(1)" not in speech
    assert any(a["action"] == "remove_code_blocks" for a in info["applied"])


def test_code_policy_announce_replaces_code():
    text = "Intro\n```python\nprint(1)\n```"
    speech, _ = preprocess_for_speech(text, SpeechConfig(code_block_policy="announce"))
    assert "print(1)" not in speech
    assert "code block omitted" in speech


def test_pronunciation_rules_applied():
    cfg = SpeechConfig(pronunciation_rules=[PronunciationRule("Kokoro", "koh-koh-roh")])
    speech, info = preprocess_for_speech("Kokoro is a model.", cfg)
    assert "koh-koh-roh" in speech


def test_math_preserved():
    speech, _ = preprocess_for_speech("Energy is E = mc^2 exactly.", SpeechConfig())
    assert "E = mc^2" in speech


def test_abbreviation_expansion_opt_in():
    cfg = SpeechConfig(expand_abbreviations=True, abbreviations={"e.g.": "for example"})
    speech, _ = preprocess_for_speech("Use it, e.g. here.", cfg)
    assert "for example" in speech

    speech2, _ = preprocess_for_speech("Use it, e.g. here.", SpeechConfig())
    assert "e.g." in speech2


def test_pronunciation_file_loading(tmp_path):
    p = tmp_path / "pron.json"
    p.write_text(json.dumps({"rules": [{"pattern": "GPU", "replacement": "gee pee you"}]}), encoding="utf-8")
    rules = load_pronunciation_file(p)
    assert rules and rules[0].replacement == "gee pee you"


def test_pronunciation_file_missing_returns_empty(tmp_path):
    assert load_pronunciation_file(tmp_path / "nope.json") == []
