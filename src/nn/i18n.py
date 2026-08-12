from __future__ import annotations

import locale
import os

RU = "ru"
EN = "en"
SUPPORTED = (EN, RU)


def lang() -> str:
    """Активный язык. Приоритет строгий: NN_LANG, затем LC_ALL/LANG, затем локаль процесса."""
    forced = os.environ.get("NN_LANG", "").strip().lower()
    if forced in SUPPORTED:
        return forced

    for source in (os.environ.get("LC_ALL"), os.environ.get("LANG")):
        if source:
            return RU if source.lower().startswith("ru") else EN

    system = locale.getlocale()[0]
    return RU if system and system.lower().startswith("ru") else EN


def bi(en: str, ru: str) -> str:
    """Строка на активном языке."""
    return ru if lang() == RU else en
