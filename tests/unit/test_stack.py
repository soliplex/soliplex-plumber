"""Offline unit tests for the ``soliplex_plumber.stack`` plumbing.

The module spins up a one-off ``docker compose run`` container, so the
``docker``/``shutil.which`` and ``subprocess.run`` seams are mocked and the
filesystem is routed through ``tmp_path`` -- no real Docker, no network.

Each test is laid out in three blank-line-separated phases -- setup, then the
single call under test (the "act"), then the assertions -- and performs that
act exactly once (cases that would repeat it are parametrized or split).
"""

from __future__ import annotations

import pathlib
import subprocess
from unittest import mock

import pytest

from soliplex_plumber import stack


# --------------------------------------------------------------------------
# Helpers / fixtures
# --------------------------------------------------------------------------
def _make_project(tmp_path, *, compose=True) -> pathlib.Path:
    project = tmp_path / "stack"
    project.mkdir(exist_ok=True)
    if compose:
        (project / "docker-compose.yml").write_text("services: {}\n")
    return project


@pytest.fixture
def which(monkeypatch):
    w = mock.Mock(return_value="/usr/bin/docker")
    monkeypatch.setattr(stack.shutil, "which", w)
    return w


@pytest.fixture
def run(monkeypatch):
    r = mock.Mock()
    monkeypatch.setattr(stack.subprocess, "run", r)
    return r


# --------------------------------------------------------------------------
# require_docker
# --------------------------------------------------------------------------
def test_require_docker_present(which):
    result = stack.require_docker()

    assert result is None


def test_require_docker_missing(which):
    which.return_value = None

    with pytest.raises(stack.DockerMissing):
        stack.require_docker()


# --------------------------------------------------------------------------
# resolve_project
# --------------------------------------------------------------------------
def test_resolve_project_ok(tmp_path):
    project = _make_project(tmp_path)

    resolved = stack.resolve_project(str(project))

    assert resolved == project.resolve()


def test_resolve_project_no_compose(tmp_path):
    project = _make_project(tmp_path, compose=False)

    with pytest.raises(stack.ComposeNotFound):
        stack.resolve_project(str(project))


# --------------------------------------------------------------------------
# cli_command
# --------------------------------------------------------------------------
def test_cli_command_defaults(tmp_path):
    project = _make_project(tmp_path)

    cmd = stack.cli_command(project, ["config"])

    assert cmd == [
        "docker",
        "compose",
        "--project-directory",
        str(project),
        "run",
        "--rm",
        "--no-TTY",
        "-e",
        "COLUMNS=10000",
        "backend",
        "/app/.venv/bin/soliplex-cli",
        "config",
        "/environment",
    ]
    assert "-v" not in cmd  # no bind mount unless host_environment is given


def test_cli_command_overrides(tmp_path):
    project = _make_project(tmp_path)

    cmd = stack.cli_command(
        project,
        ["audit", "rooms"],
        service="api",
        cli="/usr/bin/soliplex-cli",
        installation="/install",
        host_environment="alt/env",
        columns="120",
    )

    assert cmd[3] == str(project)
    assert cmd[8:] == [
        "COLUMNS=120",
        "-v",
        f"{(project / 'alt' / 'env').resolve()}:/install",
        "api",
        "/usr/bin/soliplex-cli",
        "audit",
        "rooms",
        "/install",
    ]


# --------------------------------------------------------------------------
# run_cli
# --------------------------------------------------------------------------
def test_run_cli_captures_by_default(tmp_path, which, run):
    project = _make_project(tmp_path)
    run.return_value = mock.Mock(stdout="room_paths: []\n")

    result = stack.run_cli(project, ["config"])

    assert result.stdout == "room_paths: []\n"
    assert run.call_args_list == [
        mock.call(
            stack.cli_command(project, ["config"]),
            capture_output=True,
            text=True,
            check=True,
        )
    ]


def test_run_cli_passthrough_does_not_capture(tmp_path, which, run):
    project = _make_project(tmp_path)

    stack.run_cli(project, ["audit", "rooms"], capture=False, check=False)

    _, kwargs = run.call_args
    assert kwargs == {"capture_output": False, "text": True, "check": False}


def test_run_cli_binds_alternative_installation(alt_installation, which, run):
    project = alt_installation

    stack.run_cli(project, ["audit", "installation"], host_environment="alt")

    (sent_cmd,), _ = run.call_args
    assert "-v" in sent_cmd
    assert f"{(project / 'alt').resolve()}:/environment" in sent_cmd


def test_run_cli_requires_docker(tmp_path, which, run):
    which.return_value = None
    project = _make_project(tmp_path)

    with pytest.raises(stack.DockerMissing):
        stack.run_cli(project, ["config"])

    assert run.call_args_list == []


def test_run_cli_propagates_called_process_error(tmp_path, which, run):
    project = _make_project(tmp_path)
    run.side_effect = subprocess.CalledProcessError(1, ["docker"])

    with pytest.raises(subprocess.CalledProcessError):
        stack.run_cli(project, ["config"])
