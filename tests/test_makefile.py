"""Exercise startup's readiness gate without starting services or using the network."""

import os
import subprocess
from pathlib import Path

import pytest

MAKEFILE = Path(__file__).parents[1] / "Makefile"


def _startup(
    tmp_path: Path, *, healthy: bool, external: bool = False
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "Makefile").write_text(MAKEFILE.read_text())
    commands = {
        "uv": 'if [ "$1" = sync ]; then exit 0; fi\ncase "$*" in *settings.llm_base_url*) echo http://localhost:9000/v1; exit 0;; esac\necho "dashboard failed"\nexit 1',
        "curl": "exit 0" if healthy else 'case "$*" in *models*) exit 0;; *) exit 1;; esac',
        "rapid-mlx": 'echo "should reuse the running model" >&2\nexit 1',
        "sleep": "exit 0",
        "lsof": "exit 0",
    }
    for name, script in commands.items():
        path = tmp_path / name
        path.write_text(f"#!/bin/sh\n{script}\n")
        path.chmod(493)
    return subprocess.run(
        [
            "make",
            "up",
            f"UV={tmp_path / 'uv'}",
            "STARTUP_TIMEOUT=1",
            f"LLM={('external' if external else 'auto')}",
        ],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_failed_dashboard_never_claims_readiness(tmp_path: Path) -> None:
    result = _startup(tmp_path, healthy=False)
    assert result.returncode != 0
    assert "services did not start" in result.stderr
    assert ".run/ui.log" in result.stderr
    assert "ready ->" not in result.stdout
    assert "using local LLM already listening" in result.stdout
    assert not (tmp_path / ".run/mlx.pid").exists()


def test_healthy_services_are_reused(tmp_path: Path) -> None:
    result = _startup(tmp_path, healthy=True)
    assert result.returncode == 0, result.stderr
    assert "ready ->" in result.stdout
    assert "using pizza MCP server + delivery desk already listening" in result.stdout
    assert not (tmp_path / ".run/ui.pid").exists()


def test_external_model_is_not_started_or_waited_on(tmp_path):
    result = _startup(tmp_path, healthy=True, external=True)
    assert result.returncode == 0, result.stderr
    assert "no model process managed" in result.stdout
    assert "using local LLM" not in result.stdout
    assert not (tmp_path / ".run/mlx.pid").exists()


@pytest.mark.parametrize("version", ["0.16.8", "0.16.2"])
def test_managed_model_checks_tool_version_before_starting(tmp_path: Path, version: str) -> None:
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
    assert (tmp_path / "model-started").exists() == (version == "0.16.8")
    if version == "0.16.8":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "uv tool install rapid-mlx==0.16.8" in result.stderr


def test_down_stops_managed_process_and_keeps_logs_and_unmanaged_process(tmp_path):
    (tmp_path / "Makefile").write_text(MAKEFILE.read_text())
    run_dir = tmp_path / ".run"
    run_dir.mkdir()
    (run_dir / "ui.log").write_text("service output\n")
    managed = subprocess.Popen(["sleep", "60"])
    unmanaged = subprocess.Popen(["sleep", "60"])
    try:
        (run_dir / "ui.pid").write_text(str(managed.pid))
        result = subprocess.run(
            ["make", "down"], cwd=tmp_path, capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, result.stderr
        assert managed.wait(timeout=5) != 0
        assert unmanaged.poll() is None
        assert not (run_dir / "ui.pid").exists()
        assert (run_dir / "ui.log").read_text() == "service output\n"
        again = subprocess.run(
            ["make", "down"], cwd=tmp_path, capture_output=True, text=True, timeout=10
        )
        assert again.returncode == 0, again.stderr
    finally:
        for process in (managed, unmanaged):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


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
