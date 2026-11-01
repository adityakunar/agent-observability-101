"""Run the model and audit targets with stub commands: no services, no network."""

import os
import re
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).parents[1] / "Makefile"
PINNED = re.search(r"^RAPID_MLX_VERSION\s*\?=\s*(\S+)", MAKEFILE.read_text(), re.M).group(1)


@pytest.mark.parametrize("version", [PINNED, "0.16.2"])
def test_model_checks_tool_version_before_starting(tmp_path: Path, version: str) -> None:
    (tmp_path / "Makefile").write_text(MAKEFILE.read_text())
    binary = tmp_path / "rapid-mlx"
    binary.write_text(
        f'#!/bin/sh\nif [ "$1" = --version ]; then echo "rapid-mlx {version}"; '
        "else touch model-started; fi\n"
    )
    binary.chmod(493)
    result = subprocess.run(
        ["make", "model"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (tmp_path / "model-started").exists() == (version == PINNED)
    if version == PINNED:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert f"uv tool install rapid-mlx=={PINNED}" in result.stderr


def _audit(tmp_path: Path, uv_script: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "Makefile").write_text(MAKEFILE.read_text())
    uv = tmp_path / "uv"
    uv.write_text(f'#!/bin/sh\necho "$*" >> calls.log\n{uv_script}\n')
    uv.chmod(493)
    return subprocess.run(
        ["make", "audit", f"UV={uv}", "AUDIT_ARGS=--ignore-until-fixed GHSA-test"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize("vulnerable", [False, True])
def test_audit_scans_the_lockfile_and_fails_on_findings(tmp_path: Path, vulnerable: bool) -> None:
    result = _audit(tmp_path, f'case "$*" in *--help*) exit 0;; esac\nexit {int(vulnerable)}')
    calls = (tmp_path / "calls.log").read_text()
    assert "audit --locked --preview-features audit-command --ignore-until-fixed GHSA-test" in calls
    assert (result.returncode != 0) == vulnerable


def test_audit_explains_an_old_uv(tmp_path: Path) -> None:
    result = _audit(tmp_path, "exit 2")
    assert result.returncode != 0
    assert "uv self update" in result.stderr
    assert "--locked" not in (tmp_path / "calls.log").read_text()
