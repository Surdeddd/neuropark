import pytest


@pytest.fixture(autouse=True)
def _fixed_language(monkeypatch):
    """Тесты сверяют русские подстроки, поэтому язык фиксируется независимо от окружения."""
    monkeypatch.setenv("NN_LANG", "ru")
