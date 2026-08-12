"""Предохранитель против грабли, которую я вылечил дважды.

`Path("/").glob("var/...")` на macOS не проходит промежуточный симлинк
/var → private/var: возвращает пустой результат и тратит на это ~20 секунд.
Первый раз это поймалось в detect, второй раз я переизобрёл то же в init.
Теперь раскрытие шаблонов живёт в одном месте, и тест это охраняет.
"""

import ast
import time
from pathlib import Path

from nn.detect import glob_paths

SRC = Path(__file__).resolve().parents[1] / "src" / "nn"


def test_glob_paths_finds_files_under_a_symlinked_temp_root(tmp_path):
    target = tmp_path / "models"
    target.mkdir()
    wanted = target / "a.bin"
    wanted.write_bytes(b"x")
    found = glob_paths(str(target / "*.bin"))
    assert found == [wanted]


def test_glob_paths_is_fast(tmp_path):
    """Регрессия по времени: наивная реализация укладывалась в десятки секунд."""
    target = tmp_path / "models"
    target.mkdir()
    (target / "a.bin").write_bytes(b"x")
    started = time.monotonic()
    for _ in range(20):
        glob_paths(str(target / "*.bin"))
    assert time.monotonic() - started < 2.0


def test_glob_paths_returns_empty_on_no_match(tmp_path):
    assert glob_paths(str(tmp_path / "*.nothing")) == []


def test_glob_paths_expands_home():
    assert all(str(path).startswith(str(Path.home())) for path in glob_paths("~/*"))


def test_pattern_globbing_goes_only_through_glob_paths():
    """Path.glob допустим лишь для перечисления известной папки по литералу без разделителей.

    Всё, что приходит извне как шаблон, обязано идти через glob_paths — иначе
    возвращается грабля с симлинком /var: пустой результат за десятки секунд.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", None) not in {"glob", "rglob"}:
                continue
            receiver = getattr(getattr(node.func, "value", None), "id", None)
            if receiver == "globlib":
                continue  # единственная санкционированная реализация, внутри glob_paths
            args = node.args
            literal = (
                len(args) == 1
                and isinstance(args[0], ast.Constant)
                and isinstance(args[0].value, str)
                and "/" not in args[0].value
            )
            if not literal:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert offenders == [], offenders
