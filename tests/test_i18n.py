import ast
import re
from pathlib import Path

from nn.i18n import EN, RU, bi, lang

SRC = Path(__file__).resolve().parents[1] / "src" / "nn"
CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")


def test_nn_lang_wins(monkeypatch):
    monkeypatch.setenv("NN_LANG", "en")
    assert lang() == EN
    monkeypatch.setenv("NN_LANG", "ru")
    assert lang() == RU


def test_unknown_nn_lang_falls_back_to_locale(monkeypatch):
    monkeypatch.setenv("NN_LANG", "klingon")
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    assert lang() == RU


def test_locale_decides_without_nn_lang(monkeypatch):
    monkeypatch.delenv("NN_LANG", raising=False)
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    assert lang() == RU


def test_english_is_the_default(monkeypatch):
    monkeypatch.delenv("NN_LANG", raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert lang() == EN


def test_bi_picks_active_language(monkeypatch):
    monkeypatch.setenv("NN_LANG", "en")
    assert bi("provider not found", "провайдер не найден") == "provider not found"
    monkeypatch.setenv("NN_LANG", "ru")
    assert bi("provider not found", "провайдер не найден") == "провайдер не найден"


def _bi_pairs() -> list[tuple[str, int, str, str]]:
    pairs: list[tuple[str, int, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "bi" or len(node.args) != 2:
                continue
            texts: list[str] = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    texts.append(arg.value)
                elif isinstance(arg, ast.JoinedStr):
                    texts.append(
                        "".join(
                            part.value
                            for part in arg.values
                            if isinstance(part, ast.Constant) and isinstance(part.value, str)
                        )
                    )
                else:
                    texts.append("")
            pairs.append((path.name, node.lineno, texts[0], texts[1]))
    return pairs


def test_every_bi_call_has_two_string_arguments():
    assert _bi_pairs(), "вызовов bi() не найдено — локализация где-то потерялась"


def test_english_half_is_free_of_cyrillic():
    wrong = [f"{name}:{line} {en!r}" for name, line, en, _ in _bi_pairs() if CYRILLIC.search(en)]
    assert wrong == []


def test_russian_half_actually_has_cyrillic():
    wrong = [
        f"{name}:{line} {ru!r}"
        for name, line, en, ru in _bi_pairs()
        if en and not CYRILLIC.search(ru)
    ]
    assert wrong == []


def test_no_slash_joined_bilingual_strings_left():
    """Анти-паттерн: 'english / русский' в одном литерале вместо переключения языка."""
    bad: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'"[^"]*[a-z]{3}[^"]* / [^"]*[а-я]{3}', line):
                bad.append(f"{path.name}:{number}")
    assert bad == []
