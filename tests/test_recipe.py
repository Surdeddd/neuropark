import pytest

from nn.catalog import Catalog
from nn.errors import Exit, NnError
from nn.model import Capability, Host, Provider, Recipe, Role, RolesConfig, Step
from nn.recipe import StepResult, resolve_ref, run_recipe
from nn.registry import Entry, Registry

LOCAL = Host(id="local", kind="local")
TYPES = {"text": ("txt",), "srt": ("srt",), "audio": ("wav",), "video": ("mp4",)}
CAPS = {
    "transcribe": Capability("transcribe", ("audio",), "srt"),
    "translate": Capability("translate", ("srt",), "same"),
}
LONG = "строка достаточной длины чтобы пройти порог пустоты в классификаторе"


def prov(pid, capability, run, io_in, io_out) -> Provider:
    return Provider(
        id=pid,
        capability=capability,
        kind="tool",
        detect={"bin": "printf"},
        io_in=io_in,
        io_out=io_out,
        notes="фейк",
        source=f"providers/{pid}.json",
        run={"": run},
    )


FAKE_TRANSCRIBE = prov("t", "transcribe", f"printf '{LONG}' > {{out}}", ("audio",), "srt")
FAKE_TRANSLATE = prov("tr", "translate", f"printf '{LONG} ru' > {{out}}", ("srt",), "srt")


def build(providers, roles=None) -> tuple[Catalog, Registry]:
    catalog = Catalog(
        providers={p.id: p for p in providers},
        hosts={"local": LOCAL},
        capabilities=CAPS,
        types=TYPES,
        bridges={},
        recipes={},
        roles=RolesConfig(roles=roles or {}, patterns={}),
    )
    registry = Registry(
        hostname="testbox",
        generated_at="2026-08-12T10:00:00+00:00",
        entries={
            p.id: Entry(p.id, "local", "ok", "", None, "2026-08-12T10:00:00+00:00")
            for p in providers
        },
    )
    return catalog, registry


def test_two_step_chain_passes_output_forward(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    catalog, registry = build([FAKE_TRANSCRIBE, FAKE_TRANSLATE])
    recipe = Recipe(
        id="r",
        description="",
        steps=(Step(capability="transcribe"), Step(capability="translate")),
    )
    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert [r.envelope.outcome for r in results] == ["success", "success"]
    assert results[1].envelope.in_path == results[0].envelope.out


def test_failed_step_stops_the_chain(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    broken = prov("t", "transcribe", "exit 1", ("audio",), "srt")
    catalog, registry = build([broken, FAKE_TRANSLATE])
    recipe = Recipe(
        id="r",
        description="",
        steps=(Step(capability="transcribe"), Step(capability="translate")),
    )
    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert len(results) == 1
    assert results[0].envelope.outcome == "crash"


def test_resolve_ref_input_and_step():
    class FakeEnvelope:
        out = "/tmp/step0.srt"

    done = [StepResult(index=0, envelope=FakeEnvelope())]  # type: ignore[arg-type]
    assert resolve_ref("{input}", input_path="/tmp/a.wav", done=[], current_index=1) == "/tmp/a.wav"
    got = resolve_ref("{step0.out}", input_path="/tmp/a.wav", done=done, current_index=1)
    assert got == "/tmp/step0.srt"


def test_forward_reference_is_bad_data():
    with pytest.raises(NnError) as err:
        resolve_ref("{step2.out}", input_path="/tmp/a.wav", done=[], current_index=1)
    assert err.value.code == Exit.BAD_DATA


def test_garbage_reference_is_bad_data():
    with pytest.raises(NnError) as err:
        resolve_ref("{video}", input_path="/tmp/a.wav", done=[], current_index=1)
    assert err.value.code == Exit.BAD_DATA


def test_a_step_can_name_a_role(monkeypatch, tmp_path):
    """Шаг берёт провайдера из цепочки роли — это и было последней дырой в рецептах."""
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    catalog, registry = build(
        [FAKE_TRANSCRIBE], roles={"scribe": Role(name="scribe", providers=("t",))}
    )
    recipe = Recipe(id="r", description="", steps=(Step(role="scribe"),))
    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert [r.envelope.provider for r in results] == ["t"]
    assert results[0].envelope.outcome == "success"


def test_a_role_step_walks_the_chain_past_an_unavailable_provider(monkeypatch, tmp_path):
    """Первый в цепочке недоступен — берётся следующий, как и в оркестрации."""
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    broken = prov("broken", "transcribe", "exit 1", ("audio",), "srt")
    catalog, registry = build(
        [broken, FAKE_TRANSCRIBE],
        roles={"scribe": Role(name="scribe", providers=("broken", "t"))},
    )
    registry.entries["broken"] = Entry("broken", "local", "missing", "нет бинаря", None, None)
    recipe = Recipe(id="r", description="", steps=(Step(role="scribe"),))
    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert [r.envelope.provider for r in results] == ["t"]


def test_a_role_step_mixes_with_capability_steps(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    catalog, registry = build(
        [FAKE_TRANSCRIBE, FAKE_TRANSLATE],
        roles={"translator": Role(name="translator", providers=("tr",))},
    )
    recipe = Recipe(
        id="r",
        description="",
        steps=(Step(capability="transcribe"), Step(role="translator")),
    )
    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert [r.envelope.provider for r in results] == ["t", "tr"]
    assert results[-1].envelope.outcome == "success"


def test_an_unknown_role_names_the_ones_that_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    catalog, registry = build(
        [FAKE_TRANSCRIBE], roles={"scribe": Role(name="scribe", providers=("t",))}
    )
    recipe = Recipe(id="r", description="", steps=(Step(role="nosuch"),))
    with pytest.raises(NnError) as err:
        run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert err.value.code == Exit.NO_PROVIDER
    assert "scribe" in err.value.message


def test_a_step_with_neither_capability_nor_role_is_bad_data(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    catalog, registry = build([FAKE_TRANSCRIBE])
    recipe = Recipe(id="r", description="", steps=(Step(),))
    with pytest.raises(NnError) as err:
        run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert err.value.code == Exit.BAD_DATA


def test_step_can_pin_input_to_original(monkeypatch, tmp_path):
    monkeypatch.setenv("NN_STATE", str(tmp_path / "state"))
    source = tmp_path / "a.wav"
    source.write_bytes(b"\x00")
    second = prov("second", "translate", f"printf '{LONG}' > {{out}}", ("audio",), "srt")
    catalog, registry = build([FAKE_TRANSCRIBE, second])
    recipe = Recipe(
        id="r",
        description="",
        steps=(
            Step(capability="transcribe"),
            Step(capability="translate", in_ref="{input}"),
        ),
    )
    results = run_recipe(recipe, catalog=catalog, registry=registry, input_path=str(source))
    assert results[1].envelope.in_path == str(source)
