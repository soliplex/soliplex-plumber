"""Query a running Soliplex stack's resolved installation config.

Unlike the rest of ``soliplex_plumber`` -- which does pure filesystem work on
an *existing* stack -- this module talks to a *running* one.
``soliplex-cli config <installation>`` exports the *resolved* installation
config as YAML, but ``soliplex-cli`` only exists inside the backend image, so
this module runs it in a one-off backend container (via the shared ``stack``
module) and parses the YAML output. It therefore needs Docker on ``PATH``.

The module installs a ``soliplex-config`` console script (``run`` wraps
``main`` with the user-facing error handling). It exposes the config at four
levels of granularity:

``show``
    Print the whole resolved config (the faithful ``soliplex-cli config``
    output, banner and all).

``get <key>``
    Print a single value addressed by a dotted path into the parsed config,
    e.g. ``room_paths`` (a list), ``room_paths.0`` (list index), or
    ``installation.name`` (nested key). Scalars print bare and list-of-scalars
    print one per line, so the output is shell-friendly; pass ``--format yaml``
    to dump any value (including nested structures) as YAML.

``rooms``
    A convenience over ``get room_paths``: print one
    ``{room_id, name, description}`` mapping (as YAML) for every room the
    installation actually loads. It is driven by the resolved ``room_paths`` --
    so unlike a ``rooms/*`` glob it honors installations that limit their room
    set or point ``room_paths`` at shared directories. ``room_paths`` come back
    as the backend container's absolute paths; each is mapped back to the host
    through the backend's ``<host-environment> -> <installation>`` bind mount,
    and the ``id``, ``name``, and ``description`` of every ``room_config.yaml``
    found beneath it (a directory may hold a single room or a tree of them) are
    read on the host. Rooms whose resolved path lies outside ``--installation``
    (an exotic shared mount) cannot be mapped to a host file; they are reported
    on stderr and skipped rather than silently dropped.

``room <room_id>``
    Print the full ``room_config.yaml`` (verbatim, comments and all) of the
    one loaded room whose ``id`` is ``room_id``, resolved the same way as
    ``rooms``. Errors if no loaded room has that id.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

import yaml

from soliplex_plumber import stack

# Fields lifted from each room_config.yaml into a `rooms` mapping, output key
# (left) <- room_config.yaml key (right). ``room_id`` is required; the rest are
# null when absent.
_ROOM_FIELDS = (
    ("room_id", "id"),
    ("name", "name"),
    ("description", "description"),
)


class SoliplexConfigError(stack.StackError):
    """A user-facing ``config``-subcommand error (printed without a traceback).

    Subclasses ``stack.StackError`` so the ``soliplex-config`` entry point's
    one handler catches both these and the shared stack errors (Docker /
    compose).
    """


class NoRoomPaths(SoliplexConfigError):
    def __init__(self):
        super().__init__(
            "soliplex-cli config output has no 'room_paths' "
            "(unexpected config shape -- is the backend service healthy?)"
        )


class KeyNotFound(SoliplexConfigError):
    def __init__(self, key):
        self.key = key
        super().__init__(
            f"no key {key!r} in the resolved installation config "
            "(use 'show' to inspect the available keys)"
        )


class RoomNotFound(SoliplexConfigError):
    def __init__(self, room_id):
        self.room_id = room_id
        super().__init__(
            f"no room with id {room_id!r} among the loaded rooms "
            "(use 'rooms' to list them)"
        )


def parse_config(stdout: str) -> dict:
    """Parse the YAML body of ``soliplex-cli config`` output.

    The export is prefixed with a ``#`` comment banner; YAML treats those as
    comments, so the whole stream loads directly.
    """
    loaded = yaml.safe_load(stdout)
    return loaded if isinstance(loaded, dict) else {}


def navigate(config: dict, key: str):
    """Resolve a dotted ``key`` into ``config``, or raise ``KeyNotFound``.

    Each ``.``-separated segment indexes a mapping by name or a sequence by
    integer position. Descending past a scalar, an unknown mapping key, a
    non-integer sequence index, or an out-of-range index all raise.
    """
    current = config
    for part in key.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyNotFound(key)
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise KeyNotFound(key) from None
        else:
            raise KeyNotFound(key)
    return current


def _is_scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _format_scalar(value) -> str:
    """Render a scalar the YAML way (``null``/``true``/``false``)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_value(value, fmt: str) -> str:
    """Render ``navigate``'s result for printing.

    ``yaml`` dumps any value as YAML. ``plain`` (the default) prints a scalar
    bare and a list of scalars one per line -- shell-friendly -- and falls back
    to a YAML dump for anything nested.
    """
    if fmt == "yaml":
        return yaml.safe_dump(
            value, sort_keys=False, allow_unicode=True
        ).rstrip("\n")
    if _is_scalar(value):
        return _format_scalar(value)
    if isinstance(value, list) and all(_is_scalar(item) for item in value):
        return "\n".join(_format_scalar(item) for item in value)
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip(
        "\n"
    )


def map_to_host(
    container_path: str, installation: str, host_environment: pathlib.Path
) -> pathlib.Path | None:
    """Map an in-container room path to its host location, or None.

    Returns None when ``container_path`` is not under ``installation`` (the
    bind mount we know about), e.g. a room path into an unrelated shared mount.
    """
    cpath = pathlib.PurePosixPath(container_path)
    try:
        rel = cpath.relative_to(pathlib.PurePosixPath(installation))
    except ValueError:
        return None
    return host_environment.joinpath(*rel.parts)


def find_room_configs(room_dir: pathlib.Path) -> list[pathlib.Path]:
    """room_config.yaml files under ``room_dir`` (mirrors soliplex).

    A path that directly holds ``room_config.yaml`` is a single room;
    otherwise its immediate (non-hidden) subdirectories are scanned. A path
    that does not exist (listed in room_paths but absent) yields nothing.
    """
    direct = room_dir / "room_config.yaml"
    if direct.is_file():
        return [direct]
    if not room_dir.is_dir():
        return []
    configs = []
    for sub in sorted(room_dir.glob("*")):
        if sub.name.startswith("."):
            continue
        cfg = sub / "room_config.yaml"
        if cfg.is_file():
            configs.append(cfg)
    return configs


def read_room_meta(text: str) -> dict | None:
    """A room_config.yaml's ``{room_id, name, description}``, or None.

    Returns None when the document is not a mapping or has no (truthy) ``id``.
    ``name``/``description`` default to None when the room omits them.
    """
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return {out: data.get(src) for out, src in _ROOM_FIELDS}


def _resolve_room_configs(
    project: pathlib.Path,
    service: str,
    cli: str,
    installation: str,
    host_environment: str | None,
) -> tuple[list[tuple[dict, pathlib.Path]], list[str]]:
    """Locate the loaded rooms' host ``room_config.yaml`` files.

    Returns ``(entries, unmapped_container_paths)`` where ``entries`` is a list
    of ``(meta, path)`` in ``room_paths`` order -- ``meta`` is the room's
    ``{room_id, name, description}`` and ``path`` its host config file. Room id
    conflicts resolve first-past-the-post, matching soliplex.
    """
    result = stack.run_cli(
        project,
        ["config"],
        service=service,
        cli=cli,
        installation=installation,
        host_environment=host_environment,
    )
    config = parse_config(result.stdout)
    if "room_paths" not in config:
        raise NoRoomPaths()

    # Map container room paths (under ``installation``) back to host files.
    # When --host-environment was not given, run_cli relied on the stack's own
    # bind mount, whose host side is ``stack.DEFAULT_HOST_ENVIRONMENT``.
    mount = host_environment or stack.DEFAULT_HOST_ENVIRONMENT
    host_env = (project / mount).resolve()
    entries: list[tuple[dict, pathlib.Path]] = []
    seen: set[str] = set()
    unmapped: list[str] = []
    for container_path in config["room_paths"]:
        host_dir = map_to_host(container_path, installation, host_env)
        if host_dir is None:
            unmapped.append(container_path)
            continue
        for cfg in find_room_configs(host_dir):
            meta = read_room_meta(cfg.read_text())
            if meta and meta["room_id"] not in seen:
                seen.add(meta["room_id"])
                entries.append((meta, cfg))
    return entries, unmapped


def resolve_rooms(
    project: pathlib.Path,
    service: str,
    cli: str,
    installation: str,
    host_environment: str | None,
) -> tuple[list[dict], list[str]]:
    """Collect the loaded rooms' ``{room_id, name, description}`` mappings.

    Returns ``(rooms, unmapped_container_paths)`` where ``rooms`` is one
    mapping per loaded room in ``room_paths`` order.
    """
    entries, unmapped = _resolve_room_configs(
        project, service, cli, installation, host_environment
    )
    return [meta for meta, _ in entries], unmapped


def do_show(args: argparse.Namespace) -> int:
    project = stack.resolve_project(args.project_dir)

    result = stack.run_cli(
        project,
        ["config"],
        service=args.service,
        cli=args.cli,
        installation=args.installation,
        host_environment=args.host_environment,
    )

    print(result.stdout, end="")
    return 0


def do_get(args: argparse.Namespace) -> int:
    project = stack.resolve_project(args.project_dir)

    result = stack.run_cli(
        project,
        ["config"],
        service=args.service,
        cli=args.cli,
        installation=args.installation,
        host_environment=args.host_environment,
    )
    config = parse_config(result.stdout)
    value = navigate(config, args.key)

    print(render_value(value, args.format))
    return 0


def do_rooms(args: argparse.Namespace) -> int:
    project = stack.resolve_project(args.project_dir)

    rooms, unmapped = resolve_rooms(
        project,
        args.service,
        args.cli,
        args.installation,
        args.host_environment,
    )

    for container_path in unmapped:
        print(
            f"warning: room path {container_path!r} is outside "
            f"{args.installation!r}; cannot map to a host file -- skipped",
            file=sys.stderr,
        )
    print(render_value(rooms, "yaml"))
    return 0


def do_room(args: argparse.Namespace) -> int:
    project = stack.resolve_project(args.project_dir)

    entries, _ = _resolve_room_configs(
        project,
        args.service,
        args.cli,
        args.installation,
        args.host_environment,
    )

    for meta, cfg in entries:
        if meta["room_id"] == args.room_id:
            print(cfg.read_text(), end="")
            return 0
    raise RoomNotFound(args.room_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query a Soliplex stack's resolved installation config."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser(
        "show", help="print the whole resolved installation config"
    )
    stack.add_arguments(show)
    show.set_defaults(func=do_show)

    get = sub.add_parser(
        "get", help="print one config value by dotted path into the config"
    )
    get.add_argument(
        "key",
        help="dotted path, e.g. 'room_paths', 'room_paths.0', 'agents.chat'",
    )
    get.add_argument(
        "--format",
        choices=("plain", "yaml"),
        default="plain",
        help=(
            "plain (default): scalars bare, list-of-scalars one per line; "
            "yaml: dump any value as YAML"
        ),
    )
    stack.add_arguments(get)
    get.set_defaults(func=do_get)

    rooms = sub.add_parser(
        "rooms",
        help="print a {room_id, name, description} mapping per loaded room",
    )
    stack.add_arguments(rooms)
    rooms.set_defaults(func=do_rooms)

    room = sub.add_parser(
        "room", help="print the full room_config.yaml of one room by id"
    )
    room.add_argument(
        "room_id", help="the id of the room to print (see 'rooms')"
    )
    stack.add_arguments(room)
    room.set_defaults(func=do_room)

    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    return args.func(args)


def run() -> int:
    """Console-script entry point: ``main`` plus user-facing error handling.

    Backs the ``soliplex-config`` script -- a ``stack.StackError`` (Docker /
    compose / the ``SoliplexConfigError`` subclasses) or a failed
    ``soliplex-cli`` invocation is printed without a traceback and becomes exit
    code 2.
    """
    try:
        return main(sys.argv[1:])
    except stack.StackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed ({exc})", file=sys.stderr)
        return 2
