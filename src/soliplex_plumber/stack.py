"""Run a Soliplex stack's ``soliplex-cli`` in a throwaway Docker container.

``soliplex-cli`` ships only inside the backend image, so to run it against a
stack on disk we spin up a one-off container with ``docker compose run --rm``
pointed at the stack directory.

This module is the shared plumbing for that flow:

- Validate the stack root.
- Check Docker is present.
- Build the ``docker compose run`` argv.
- Run it, capturing or streaming the output.

.. note::

   Because this module talks to a *running* Docker instance, it needs
   Docker on ``PATH``.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import pathlib
import shutil
import subprocess
import tempfile

DEFAULT_SERVICE = "backend"  # docker compose service name
DEFAULT_CLI = "/app/.venv/bin/soliplex-cli"  # in-container CLI command
DEFAULT_INSTALLATION = "/environment"  # in-container mount point
DEFAULT_HOST_ENVIRONMENT = "backend/environment"  # host dir, rel. to project
WIDE_COLUMNS = "10000"  # wide terminal, avoid 'rich' wrapping.


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

    ``["-e", "COLUMNS={columns}"]`` prevents soliplex-cli console from
    wrapping long lines.

    Pass ``host_environment`` (relative to ``project``) to bind-mount a
    non-default host tree onto ``installation``.

    The user-supplied on-container command (after the service name)
    is ``<cli> <cli_args> <installation>``:

    - ``cli`` is the top-level command ("soliplex-cli" by default)

    - ``cli_args`` is the subcommand (and any options)

    - ``installation`` is the on-container path to the installation config.
    """
    base_cmd = [
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
    mount_point = (
        []
        if host_environment is None
        else [
            "-v",
            f"{(project / host_environment).resolve()}:{installation}",
        ]
    )
    return [
        *base_cmd,
        *mount_point,
        service,
        cli,
        *cli_args,
        installation,
    ]


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

    Requires Docker.

    See :func:`cli_command` for these parameters:
    - ``project``
    - ``cli_args``
    - ``service``
    - ``cli``
    - ``installation``
    - ``host_environment``
    - ``columns``

    If ``capture`` is true, capture stdout/stderr for parsing on the returned
    ``CompletedProcess``;  otherwise they stream to the caller.

    If ``check`` is True, raise ``subprocess.CalledProcessError`` on a
    non-zero exit.
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


@dataclasses.dataclass(frozen=True)
class Environment:
    """A selected installation tree, bound to its stack for running the CLI.

    ``path`` is the resolved host tree to bind onto the in-container path
    (``installation``).

    :meth:`run_cli` is :func:`run_cli`, pre-bound to this stack's
    ``project``, ``service``, ``installation``, and ``host_environment=path``.
    """

    path: pathlib.Path
    project: pathlib.Path
    service: str
    installation: str

    def run_cli(
        self, cli_args: list[str], **kwargs
    ) -> subprocess.CompletedProcess:
        """Call :func:`run_cli` passing curried options.

        Pass only subcommand and non-default ``capture`` / ``check`` options.
        """
        return run_cli(
            self.project,
            cli_args,
            service=self.service,
            installation=self.installation,
            host_environment=str(self.path),
            **kwargs,
        )


@contextlib.contextmanager
def live_environment(
    project: pathlib.Path,
    *,
    service: str = DEFAULT_SERVICE,
    installation: str = DEFAULT_INSTALLATION,
    environment: str = DEFAULT_HOST_ENVIRONMENT,
):
    """Yield environment binding the stack's live installation config."""
    yield Environment(
        (project / environment).resolve(), project, service, installation
    )


@contextlib.contextmanager
def scratch_environment(
    project: pathlib.Path,
    *,
    service: str = DEFAULT_SERVICE,
    installation: str = DEFAULT_INSTALLATION,
    environment: str = DEFAULT_HOST_ENVIRONMENT,
):
    """Yield environment binding a scratch copy of the stack environment.

    Copy[*] ``<project>/<environment>`` into a temp directory beside the
    project, so that the bind path stays reachable by the docker daemon.

    Bind yielded :class:`Environment` to the copy.

    Remove the temp directory on exit.

    * By default, RAG databases are mounted to a ``rag/db`` mount from a tree
      outside the environment;  the copy omits any Lancd DBs which
      *are* in the tree to keep the copy cheap.
    """
    scratch_root = pathlib.Path(tempfile.mkdtemp(dir=project))
    try:
        scratch_env = scratch_root / pathlib.PurePosixPath(environment).name
        shutil.copytree(
            project / environment,
            scratch_env,
            ignore=shutil.ignore_patterns("*.lancedb"),
        )
        yield Environment(
            scratch_env.resolve(), project, service, installation
        )
    finally:
        shutil.rmtree(scratch_root, ignore_errors=True)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Add CLI options targeting a stack and its container."""
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
