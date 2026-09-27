"""Plugin discovery, loading rules and the import boundary (ARCHITECTURE.md §14, ADR 0008)."""

import ast
from pathlib import Path

import pytest
from planhaven_sdk import Manifest, PluginError

from app.plugins_host.host import LoadedPlugins as Loaded
from app.plugins_host.host import _Registry, discover, load

FIXTURES = str(Path(__file__).parent / "fixtures" / "plugins")
REPO = Path(__file__).resolve().parents[2]


def test_discovery_reads_manifests_without_importing() -> None:
    found = {p.plugin_id: p for p in discover((FIXTURES, "/nonexistent"))}
    assert found["example"].compatible
    assert found["example"].error is None
    assert not found["wrong_api"].compatible
    assert found["wrong_api"].error == "unsupported api_version"
    assert found["broken"].manifest is None
    assert "invalid plugin.toml" in (found["broken"].error or "")


def test_only_enabled_compatible_plugins_load() -> None:
    discovered = discover((FIXTURES,))
    assert load(discovered, set()).manifests == {}

    loaded = load(discovered, {"example", "wrong_api"})
    assert set(loaded.manifests) == {"example"}
    assert [pid for pid, _ in loaded.handlers["task.completed"]] == ["example"]
    assert loaded.errors == {"wrong_api": "unsupported api_version"}


def test_plugins_can_only_subscribe_to_declared_events() -> None:
    manifest = Manifest.model_validate(
        {"plugin": {"id": "quiet", "name": "Q", "version": "1", "api_version": "1"}}
    )
    with pytest.raises(PluginError, match="not declared"):
        _Registry(manifest, Loaded()).on_event("task.completed", _noop)


async def _noop(*_: object) -> None:
    return None


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize(
    "root", [REPO / "plugins", REPO / "sdk" / "python", Path(FIXTURES)], ids=lambda p: p.name
)
def test_plugins_and_sdk_never_import_the_application(root: Path) -> None:
    offenders = [
        str(path.relative_to(REPO))
        for path in root.rglob("*.py")
        if "app" in _imports(path) or "backend" in _imports(path)
    ]
    assert offenders == [], f"must use only planhaven_sdk, not the app: {offenders}"


def test_entrypoint_must_be_the_plugins_own_code(tmp_path: Path) -> None:
    from app.plugins_host.host import _entrypoint

    (tmp_path / "evil").mkdir()
    with pytest.raises(PluginError, match="inside the plugin"):
        _entrypoint(tmp_path / "evil", "os:system")
    with pytest.raises(PluginError, match="inside the plugin"):
        _entrypoint(tmp_path / "evil", "json:loads")
