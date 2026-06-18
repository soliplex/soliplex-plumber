"""Shared fixtures for the unit tests."""

from __future__ import annotations

import pathlib

import pytest


@pytest.fixture
def alt_installation(tmp_path) -> pathlib.Path:
    """A stack whose ``alt/`` is a minimal, id-only alternative installation.

    Returns the stack root (has ``docker-compose.yml``); its ``alt/`` subdir
    is a valid installation directory (``alt/installation.yaml``) a caller can
    bind onto the in-container installation path -- via
    ``host_environment="alt"`` (or ``--host-environment alt``) -- to query that
    tree instead of the deployed one.
    """
    project = tmp_path / "stack"
    project.mkdir()
    (project / "docker-compose.yml").write_text("services: {}\n")
    alt = project / "alt"
    alt.mkdir()
    (alt / "installation.yaml").write_text('id: "alt"\n')
    return project
