"""Двуязычность слоя данных.

Сторож в test_i18n.py смотрит только на .py, поэтому склейка «english / русский»
дожила в hosts/local.json и priors.json до публикации, а описание рецепта отвечало
по-русски при NN_LANG=en. Здесь под охраной сами JSON-файлы.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")

# Поля, которые читает человек: если в них есть русский, обязана быть форма {en, ru}.
HUMAN_FIELDS = {"notes", "description", "instruction", "_comment"}

# Поля-регулярки: ими ищут русский текст в чужом stderr, перевод сломал бы поиск.
MATCHING_FIELDS = {"match", "quota_patterns", "refusal_patterns"}


def _data_files() -> list[Path]:
    files = [ROOT / "priors.json", ROOT / "capabilities.json", ROOT / "dossier-rules.json"]
    for folder in (
        "providers",
        "hosts",
        "bridges",
        "recipes",
        "examples/providers",
        "examples/hosts",
    ):
        files.extend(sorted((ROOT / folder).glob("*.json")))
    return [path for path in files if path.is_file()]


def _strings(node: object, path: str) -> list[tuple[str, str]]:
    if isinstance(node, dict):
        found: list[tuple[str, str]] = []
        for key, value in node.items():
            found.extend(_strings(value, f"{path}.{key}"))
        return found
    if isinstance(node, list):
        found = []
        for index, value in enumerate(node):
            found.extend(_strings(value, f"{path}[{index}]"))
        return found
    if isinstance(node, str):
        return [(path, node)]
    return []


@pytest.fixture(scope="module")
def entries() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in _data_files():
        payload = json.loads(path.read_text(encoding="utf-8"))
        found.extend(_strings(payload, path.relative_to(ROOT).as_posix()))
    assert found, "файлы данных не нашлись — тест смотрит не туда"
    return found


def test_no_two_languages_glued_into_one_string(entries):
    """«english / русский» одной строкой: переключение языка её не берёт."""
    bad = [
        f"{where}: {text[:60]!r}"
        for where, text in entries
        if " / " in text and CYRILLIC.search(text)
    ]
    assert bad == []


def test_human_fields_with_russian_carry_both_languages(entries):
    bad: list[str] = []
    for where, text in entries:
        if not CYRILLIC.search(text):
            continue
        tail = where.split(".")[-1]
        if tail in {"en", "ru"}:
            continue
        field = where.split(".")[-1].split("[")[0]
        if field in MATCHING_FIELDS:
            continue
        if field in HUMAN_FIELDS:
            bad.append(f"{where}: {text[:60]!r}")
    assert bad == [], bad


def test_bilingual_halves_are_not_swapped(entries):
    """en без кириллицы, ru — с ней. Перепутанные половины ловятся здесь.

    Исключение: en и ru совпадают дословно. Это языконезависимый текст (имя
    продукта, команда), и требовать от него кириллицы бессмысленно.
    """
    by_path = dict(entries)
    bad: list[str] = []
    for where, text in entries:
        tail = where.rsplit(".", 1)[-1]
        if tail == "en" and CYRILLIC.search(text):
            bad.append(f"{where} (кириллица в en): {text[:40]!r}")
        if tail == "ru" and not CYRILLIC.search(text):
            twin = by_path.get(f"{where.rsplit('.', 1)[0]}.en")
            if twin != text:
                bad.append(f"{where} (нет кириллицы в ru): {text[:40]!r}")
    assert bad == [], bad
