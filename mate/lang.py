"""Language strings.

The ten ``LangVars-<code>.php`` classes were converted 1:1 into
``mate/lang/<code>.json`` (65 keys each: en, de, es, fr, it, nl, pt-br, ru, tr, zh).
``LangVars`` gives attribute access with the same names the PHP code used
(``lang.btnExport``, ``lang.ttlNoRecord`` ...), and falls back to English for
any key a translation lacks.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

_DIR = os.path.join(os.path.dirname(__file__), "lang")


@lru_cache(maxsize=None)
def _load(code: str) -> dict[str, Any]:
    path = os.path.join(_DIR, f"{code}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def available_languages() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(_DIR) if f.endswith(".json"))


class LangVars:
    def __init__(self, code: str = "en"):
        code = code if code in available_languages() else "en"
        self.code = code
        self._data = dict(_load("en"))
        self._data.update(_load(code))

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["_data"][name]
        except KeyError:
            raise AttributeError(name) from None

    def get(self, name: str, default: Any = None) -> Any:
        return self._data.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        """Plain dict for shipping to the browser."""
        return dict(self._data)
