import stat
from pathlib import Path

import pytest

from app.core import init_secrets as mod

ALL = [mod.MASTER_KEY, mod.SESSION_KEY, mod.VAPID_PRIVATE_KEY, mod.VAPID_PUBLIC_KEY]


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_creates_all_secrets_with_private_permissions(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"

    created = mod.init_secrets(secrets_dir)

    assert sorted(created) == sorted(ALL)
    assert mode(secrets_dir) == 0o700
    for name in ALL:
        assert mode(secrets_dir / name) == 0o600, name
    assert len((secrets_dir / mod.MASTER_KEY).read_bytes()) == 32
    assert len((secrets_dir / mod.SESSION_KEY).read_bytes()) == 32
    assert (secrets_dir / mod.MASTER_KEY).read_bytes() != (
        secrets_dir / mod.SESSION_KEY
    ).read_bytes()


def test_never_overwrites_existing_secrets(tmp_path: Path) -> None:
    mod.init_secrets(tmp_path)
    before = {name: (tmp_path / name).read_bytes() for name in ALL}

    created = mod.init_secrets(tmp_path)

    assert created == []
    assert {name: (tmp_path / name).read_bytes() for name in ALL} == before


def test_tightens_loose_permissions(tmp_path: Path) -> None:
    mod.init_secrets(tmp_path)
    (tmp_path / mod.MASTER_KEY).chmod(0o644)
    tmp_path.chmod(0o755)

    mod.init_secrets(tmp_path)

    assert mode(tmp_path / mod.MASTER_KEY) == 0o600
    assert mode(tmp_path) == 0o700


def test_vapid_public_key_matches_private(tmp_path: Path) -> None:
    mod.init_secrets(tmp_path)
    public = (tmp_path / mod.VAPID_PUBLIC_KEY).read_bytes()
    (tmp_path / mod.VAPID_PUBLIC_KEY).unlink()

    created = mod.init_secrets(tmp_path)

    assert created == [mod.VAPID_PUBLIC_KEY]
    assert (tmp_path / mod.VAPID_PUBLIC_KEY).read_bytes() == public


def test_refuses_symlinked_secret(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_bytes(b"attacker-controlled")
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    (secrets_dir / mod.MASTER_KEY).symlink_to(target)

    with pytest.raises(RuntimeError, match="symlink"):
        mod.init_secrets(secrets_dir)


def test_main_prints_names_not_contents(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert mod.main(["init_secrets", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    key = (tmp_path / mod.MASTER_KEY).read_bytes()
    assert out == "init-secrets: created 4 new secret file(s)\n"
    assert key.hex() not in out
