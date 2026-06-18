"""Run a Soliplex stack's ``soliplex-cli`` in a throwaway Docker container.

``soliplex-cli`` ships only inside the backend image, so to run it against a
stack on disk -- without the caller being *inside* a configured / running
stack -- we spin up a one-off container with ``docker compose run --rm``
pointed at the stack directory. This module is the shared plumbing for that:
validate the stack root, check Docker is present, build the ``docker compose
run`` argv, and run it (capturing the output for parsing, or streaming it
through to the caller).

``soliplex_plumber.soliplex_config`` builds on it (for the ``config``
subcommand it parses), and the ``soliplex-cli`` skill uses it to run arbitrary
subcommands. Unlike the rest of ``soliplex_plumber`` -- pure filesystem work
on an *existing* stack -- this module talks to a *running* one and needs
Docker on ``PATH``.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess

# The compose service that ships soliplex-cli, the binary's in-container path
# (the compose command launches it by absolute path -- the venv is not on
# PATH), and the in-container installation path it serves -- every soliplex-cli
# command takes that path as its leaf-command positional argument.
DEFAULT_SERVICE = "backend"
DEFAULT_CLI = "/app/.venv/bin/soliplex-cli"
DEFAULT_INSTALLATION = "/environment"
# The host directory (relative to the stack root) bind-mounted onto
# ``DEFAULT_INSTALLATION`` for the backend service. Overridable per-run so a
# caller can point the one-off container at an alternative installation tree
# (e.g. to dry-run changes) instead of the deployed one.
DEFAULT_HOST_ENVIRONMENT = "backend/environment"
# A wide terminal so rich (soliplex-cli's console) does not wrap long lines in
# the captured, non-TTY output (which would, e.g., corrupt parsed YAML).
WIDE_COLUMNS = "10000"


class StackError(Exception):
    """A user-facing error (printed without a traceback)."""


class DockerMissing(StackError):
    def __init__(self):
        super().__init__(
            "docker not found on PATH (the Docker CLI is required)"
        )


class ComposeNotFound(StackError):
    def __init__(self, path):
        self.path = path
        super().__init__(
            f"no docker-compose.yml at {path} "
            "(run from the stack directory or pass --project-dir)"
        )


def require_docker() -> None:
    """Raise ``DockerMissing`` unless the Docker CLI is on ``PATH``."""
    if shutil.which("docker") is None:
        raise DockerMissing()


def resolve_project(project_dir: str) -> pathlib.Path:
    """Resolve a stack root, requiring a ``docker-compose.yml``."""
    project = pathlib.Path(project_dir).resolve()
    compose = project / "docker-compose.yml"
    if not compose.is_file():
        raise ComposeNotFound(compose)
    return project


def cli_command(
    project: pathlib.Path,
    cli_args: list[str],
    *,
    service: str = DEFAULT_SERVICE,
    cli: str = DEFAULT_CLI,
    installation: str = DEFAULT_INSTALLATION,
    host_environment: str | None = None,
    columns: str = WIDE_COLUMNS,
) -> list[str]:
    """Build the ``docker compose run`` argv for a one-off soliplex-cli call.

    Runs ``cli`` (the in-container soliplex-cli path) with ``cli_args`` in a
    throwaway ``service`` container for the stack at ``project``, ending with
    ``installation`` -- the in-container installation path that every
    soliplex-cli command takes as its leaf-command positional. ``cli_args`` is
    therefore the subcommand (and any options), *without* that path.

    By default the container uses the stack's own bind mount for
    ``installation``. Pass ``host_environment`` (relative to ``project``) to
    instead bind-mount that host tree onto ``installation`` -- pointing the
    one-off container at an alternative installation. ``COLUMNS`` is forced to
    ``columns`` so the soliplex-cli console does not wrap long lines.
    """
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(project),
        "run",
        "--rm",
        "--no-TTY",
        "-e",
        f"COLUMNS={columns}",
    ]
    if host_environment is not None:
        host_path = (project / host_environment).resolve()
        cmd += ["-v", f"{host_path}:{installation}"]
    cmd += [service, cli, *cli_args, installation]
    return cmd


def run_cli(
    project: pathlib.Path,
    cli_args: list[str],
    *,
    service: str = DEFAULT_SERVICE,
    cli: str = DEFAULT_CLI,
    installation: str = DEFAULT_INSTALLATION,
    host_environment: str | None = None,
    columns: str = WIDE_COLUMNS,
    capture: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a soliplex-cli command in a one-off backend container.

    Requires Docker. ``cli_args`` is the subcommand (and options) without the
    installation path -- ``installation`` is appended as the positional, and
    ``host_environment`` (when given) is bind-mounted onto it to query an
    alternative installation (see :func:`cli_command`). With ``capture`` (the
    default) stdout/stderr are captured on the returned ``CompletedProcess`` --
    for parsing; pass ``capture=False`` to stream them through to the caller's
    terminal. ``check`` (the default) raises ``subprocess.CalledProcessError``
    on a non-zero exit.
    """
    require_docker()
    cmd = cli_command(
        project,
        cli_args,
        service=service,
        cli=cli,
        installation=installation,
        host_environment=host_environment,
        columns=columns,
    )
    return subprocess.run(cmd, capture_output=capture, text=True, check=check)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the CLI options that select and target a stack and its container.

    A consumer's argparse front end calls this, then hands the parsed values
    to :func:`resolve_project` (``project_dir``) and :func:`run_cli`
    (``service`` / ``cli`` / ``installation`` / ``host_environment``).
    ``--host-environment`` defaults to ``None`` -- omit it to use the stack's
    own bind mount; pass it to bind an alternative installation tree.
    """
    parser.add_argument(
        "--project-dir",
        default=".",
        help="stack directory (default: current directory)",
    )
    parser.add_argument(
        "--service",
        default=DEFAULT_SERVICE,
        help=(
            "compose service running soliplex-cli "
            f"(default: {DEFAULT_SERVICE})"
        ),
    )
    parser.add_argument(
        "--cli",
        default=DEFAULT_CLI,
        help=f"in-container soliplex-cli path (default: {DEFAULT_CLI})",
    )
    parser.add_argument(
        "--installation",
        default=DEFAULT_INSTALLATION,
        help=(
            f"in-container installation path (default: {DEFAULT_INSTALLATION})"
        ),
    )
    parser.add_argument(
        "--host-environment",
        default=None,
        help=(
            "host dir to bind-mount onto --installation, to query an "
            "alternative installation tree instead of the deployed one "
            "(default: the stack's own mount, i.e. "
            f"{DEFAULT_HOST_ENVIRONMENT})"
        ),
    )
