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
    """Анти-паттерн: 'english / русский' вместо переключения языка.

    Ловится и однострочный литерал, и склейка из соседних строк — второй вариант
    сторож однажды пропустил, и склейка дожила до вывода nn adapt.
    """
    bad: list[str] = []
    single = re.compile(r'"[^"]*[a-z]{3}[^"]* / [^"]*[а-я]{3}')
    continuation = re.compile(r'^\s*" / [^"]*[а-яА-Я]')
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if single.search(line) or continuation.match(line):
                bad.append(f"{path.name}:{number}")
    assert bad == []


def _call_name(node: ast.Call) -> str | None:
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None)


class _Collector(ast.NodeVisitor):
    """Один проход: помечает литералы внутри bi() и собирает русские вне него.

    Наивная версия делала вложенные ast.walk и уходила в кубическую сложность —
    прогон тестов вставал на минуты. Здесь состояние ведётся по стеку визита.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.offenders: list[str] = []
        self._inside_bi = 0
        self._inside_user_facing = 0
        self._cyrillic = re.compile(r"[а-яА-ЯёЁ]")

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        bi_call = name == "bi"
        user_facing = name in {"print", "NnError", "Rejection", "Finding"}
        self._inside_bi += int(bi_call)
        self._inside_user_facing += int(user_facing)
        self.generic_visit(node)
        self._inside_bi -= int(bi_call)
        self._inside_user_facing -= int(user_facing)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str):
            return
        unwrapped = self._inside_user_facing and not self._inside_bi
        if unwrapped and self._cyrillic.search(node.value):
            self.offenders.append(f"{self.filename}:{node.lineno} {node.value[:40]!r}")


def test_every_printed_literal_goes_through_bi():
    """Русский текст в print/NnError вне bi() означает, что английский режим его не переведёт."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        collector = _Collector(path.name)
        collector.visit(ast.parse(path.read_text(encoding="utf-8")))
        offenders.extend(collector.offenders)
    assert offenders == [], offenders


# Русский текст, который НЕ является интерфейсом: регулярки, которыми ищется отказ
# модели в её собственном ответе. Перевод сломал бы сопоставление, а не помог бы.
MATCHING_DATA = {"DEFAULT_REFUSALS"}


class _EveryLiteral(ast.NodeVisitor):
    """Тот же обход, но литералы ловятся везде, а не только в print/NnError.

    Прошлая версия сторожила лишь вызовы print и NnError, поэтому мимо неё прошли
    русские строки в конструкторах датаклассов, в аргументах хелперов и в модульных
    константах: `nn quota`, `nn scan` и все ошибки валидации отвечали по-русски даже
    при NN_LANG=en. Найдено живым прогоном холодного старта 2026-08-12.
    """

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.offenders: list[str] = []
        self._inside_bi = 0
        self._inside_matching_data = 0
        self._docstrings: set[int] = set()
        self._cyrillic = re.compile(r"[а-яА-ЯёЁ]")

    def note_docstrings(self, tree: ast.Module) -> None:
        holders = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        for node in ast.walk(tree):
            if isinstance(node, holders) and ast.get_docstring(node, clean=False) is not None:
                body = node.body
                if body and isinstance(body[0], ast.Expr):
                    self._docstrings.add(id(body[0].value))

    def visit_Call(self, node: ast.Call) -> None:
        bi_call = _call_name(node) == "bi"
        self._inside_bi += int(bi_call)
        self.generic_visit(node)
        self._inside_bi -= int(bi_call)

    def visit_Assign(self, node: ast.Assign) -> None:
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        data = bool(names & MATCHING_DATA)
        self._inside_matching_data += int(data)
        self.generic_visit(node)
        self._inside_matching_data -= int(data)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, str) or id(node) in self._docstrings:
            return
        if self._inside_bi or self._inside_matching_data:
            return
        if self._cyrillic.search(node.value):
            self.offenders.append(f"{self.filename}:{node.lineno} {node.value[:40]!r}")


def test_no_russian_literal_lives_outside_bi():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        collector = _EveryLiteral(path.name)
        collector.note_docstrings(tree)
        collector.visit(tree)
        offenders.extend(collector.offenders)
    assert offenders == [], offenders
