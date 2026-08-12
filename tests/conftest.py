import pytest


@pytest.fixture(autouse=True)
def _fixed_language(monkeypatch):
    """Тесты сверяют русские подстроки, поэтому язык фиксируется независимо от окружения."""
    monkeypatch.setenv("NN_LANG", "ru")


@pytest.fixture(autouse=True)
def _isolated_user_layer(request, monkeypatch, tmp_path_factory):
    """Личный слой пользователя не должен попадать в тесты репозитория.

    Иначе сломанный манифест на чьей-то машине валит чужой набор тестов, а результат
    зависит от того, что у человека установлено. Живые смоуки исключены намеренно:
    им нужен настоящий парк, они и проверяют реальное железо.
    """
    if request.node.get_closest_marker("smoke"):
        return
    monkeypatch.setenv("NN_HOME", str(tmp_path_factory.mktemp("nn-home")))
