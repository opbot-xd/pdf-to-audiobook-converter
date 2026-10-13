from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Bump when speech-preparation *logic* changes so cached speech.txt is
# invalidated even though the SpeechConfig itself is unchanged.
SPEECH_VERSION = "1"


@dataclass
class PronunciationRule:
    pattern: str
    replacement: str
    regex: bool = False


@dataclass
class SpeechConfig:
    code_block_policy: str = "read"  # read|announce|skip
    expand_abbreviations: bool = False
    abbreviations: Dict[str, str] = field(default_factory=dict)
    pronunciation_rules: List[PronunciationRule] = field(default_factory=list)
    preserve_math: bool = True
    normalize_punctuation: bool = True


def load_pronunciation_file(path: Path) -> List[PronunciationRule]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        rules: List[PronunciationRule] = []
        for r in data.get("rules", []):
            rules.append(
                PronunciationRule(
                    pattern=r["pattern"],
                    replacement=r.get("replacement", ""),
                    regex=bool(r.get("regex", False)),
                )
            )
        return rules
    except Exception as e:
        logger.warning("Failed to load pronunciation file %s: %s", path, e)
        return []


def preprocess_for_speech(cleaned_text: str, config: Optional[SpeechConfig] = None) -> Tuple[str, Dict]:
    if config is None:
        config = SpeechConfig()

    text = cleaned_text
    applied: List[Dict] = []

    # Code blocks: simple heuristic - fenced blocks
    if config.code_block_policy == "skip":
        # remove fenced code blocks
        text_new = re.sub(r"```[\s\S]*?```", "", text)
        text_new = re.sub(r"`[^`]+`", "", text_new)
        if text_new != text:
            applied.append({"action": "remove_code_blocks", "policy": "skip"})
        text = text_new
    elif config.code_block_policy == "announce":
        text = re.sub(r"```[\s\S]*?```", "\n[code block omitted in narration]\n", text)
        text = re.sub(r"`([^`]+)`", r" \1 ", text)
        applied.append({"action": "announce_code_blocks", "policy": "announce"})

    # Normalize spacing
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

    if config.normalize_punctuation:
        # basic normalization only - don't change meaning
        text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        applied.append({"action": "normalize_quotes"})

    # Expand abbreviations if any
    if config.expand_abbreviations and config.abbreviations:
        for abbr, full in config.abbreviations.items():
            # Use lookarounds instead of \b: abbreviations often end in '.'
            # (e.g. "e.g."), where \b has no boundary to match.
            text = re.sub(rf"(?<!\w){re.escape(abbr)}(?!\w)", full, text)
        applied.append({"action": "expand_abbreviations", "count": len(config.abbreviations)})

    # Pronunciation rules
    for rule in config.pronunciation_rules:
        try:
            if rule.regex:
                text = re.sub(rule.pattern, rule.replacement, text)
            else:
                text = text.replace(rule.pattern, rule.replacement)
            applied.append({"action": "pronunciation", "pattern": rule.pattern})
        except Exception as e:
            logger.warning("Failed to apply pronunciation rule %s: %s", rule.pattern, e)

    return text.strip(), {"applied": applied}
