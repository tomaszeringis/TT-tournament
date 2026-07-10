"""
Voice Alias Expansion (Phase 3)

Expands multilingual command aliases before parsing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_ALIAS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "voice_aliases.json"
)


def load_aliases(path: Optional[str] = None) -> Dict[str, List[str]]:
    file_path = path or _DEFAULT_ALIAS_FILE
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("Failed to load voice aliases: %s", exc)
        return {}


class AliasExpander:
    def __init__(self, aliases: Optional[Dict[str, List[str]]] = None):
        self.aliases = aliases or load_aliases()

    def expand(self, text: str, language: str = "en") -> str:
        lang_aliases = self.aliases.get(language, {})
        expanded = text.lower()
        for canonical, variants in lang_aliases.items():
            for variant in variants:
                if variant.lower() in expanded:
                    expanded = expanded.replace(variant.lower(), canonical)
        return expanded
