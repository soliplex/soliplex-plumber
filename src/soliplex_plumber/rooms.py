"""Install a room into a Soliplex stack, wiring its ``room_paths`` entry.

The shared core behind the ``soliplex-template`` skill's ``add_room.py`` and
the ``soliplex-concierge`` installer. A room is written under an explicit
``parent_path`` (relative to the installation config, e.g. ``"./rooms"``) and
``room_paths`` is edited line-based (comment-preserving) so the room is
discovered. The governing rule: **installing a room never disables another** --
edits are append-only and the ``./rooms`` default is materialized before any
non-default parent is added.

- ``resolve_project`` / ``resolve_package_name`` -- locate + introspect it.
- ``validate_room_id`` -- the room-id / path-segment rule.
- ``room_parent_candidates`` -- the container entries of ``room_paths`` a
  caller can offer as a ``parent_path`` (or ``["./rooms"]`` when it is absent).
- ``install_room`` -- write the room dir from a rendered ``config_text``
  (+ optional prompt) under ``parent_path``; honor dry-run and force.
- ``install_room_from`` -- the same, but *copy* an existing room directory tree
  (multi-file templates); the caller patches the copied files afterward.

Section scanning + the generic installation.yaml primitives live in the sibling
:mod:`soliplex_plumber.installation`; the section catalog in
:mod:`soliplex_plumber.sections`. Pure filesystem work -- stdlib only.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import shutil

from soliplex_plumber import installation
from soliplex_plumber import sections

# A room id usable as a path segment and a YAML id: no '/', no '..', no
# leading dot (mirrors rag_db.py's DB_NAME_RE).
ROOM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Placeholder when the stack's own package can't be inferred (no 'src/<pkg>/');
# the '<pkg>.tools.greeting' demo tool in the skill templates references it.
DEFAULT_PACKAGE_NAME = "your_package"
# Written into the room dir when a prompt file is supplied; the config then
# points its system_prompt at this file (the 'search' demo room uses the form).
PROMPT_FILE_NAME = "prompt.txt"

# Stack-structure constants + the action strings live canonically in
# 'sections'/'installation'; re-exported here so existing consumers keep
# importing them by their historical names.
COMPOSE_FILE = sections.COMPOSE_FILE
ENVIRONMENT_DIR = sections.ENVIRONMENT_DIR
INSTALLATION_FILE = sections.INSTALLATION_FILE
ROOMS_DIR = sections.ROOMS_DIR

ADDED = installation.TargetAction.ADDED
UNCHANGED = installation.TargetAction.UNCHANGED
COVERED = installation.TargetAction.COVERED

# The default room-discovery container (a ``room_paths`` entry pointing here
# auto-discovers every room beneath it).
ROOMS_PARENT_ENTRY = sections.ROOM_PATHS.discovery_default


class AddRoomError(Exception):
    """A user-facing error (printed without a traceback).

    Message construction lives in these classmethod factories so call sites
    read ``raise AddRoomError.<reason>(...)`` with no inline message string.
    """

    @classmethod
    def compose_not_found(cls, path):
        return cls(
            f"no {COMPOSE_FILE} at {path} "
            "(run with --project-dir pointing at the stack directory)"
        )

    @classmethod
    def not_a_stack(cls, path):
        return cls(
            f"{path} is not a generated Soliplex stack: missing "
            f"'{INSTALLATION_FILE}'"
        )

    @classmethod
    def bad_room_id(cls, room_id):
        return cls(
            f"room id {room_id!r} must match {ROOM_ID_RE.pattern} "
            "(letters, digits, '.', '_', '-'; no leading dot)"
        )

    @classmethod
    def room_exists(cls, path):
        return cls(f"{path} already exists (use force to overwrite it)")

    @classmethod
    def parent_is_room(cls, path):
        return cls(
            f"parent_path {path} is itself a room (has a room_config.yaml); "
            "pass a container directory to install rooms into"
        )


def validate_room_id(room_id: str) -> None:
    if not ROOM_ID_RE.match(room_id):
        raise AddRoomError.bad_room_id(room_id)


def resolve_project(project_dir: str) -> pathlib.Path:
    """Return the resolved stack root, or raise if it is not a stack."""
    project = pathlib.Path(project_dir).resolve()
    if not (project / COMPOSE_FILE).is_file():
        raise AddRoomError.compose_not_found(project / COMPOSE_FILE)
    if not (project / INSTALLATION_FILE).is_file():
        raise AddRoomError.not_a_stack(project)
    return project


def resolve_package_name(project: pathlib.Path, override: str | None) -> str:
    """The stack's own package (for ``<pkg>.tools.greeting``), or placeholder.

    Prefer an explicit ``override``; otherwise infer the single package under
    ``src/`` (the generator scaffolds ``src/<package_name>/tools.py``); failing
    that, return ``DEFAULT_PACKAGE_NAME`` for the operator to edit.
    """
    if override is not None:
        return override
    src = project / "src"
    if src.is_dir():
        packages = [
            child.name
            for child in sorted(src.iterdir())
            if child.is_dir() and (child / "tools.py").is_file()
        ]
        if len(packages) == 1:
            return packages[0]
    return DEFAULT_PACKAGE_NAME


_ENTRY_RE = re.compile(r'-\s*["\']?([^"\'\s]+)["\']?\s*$')


def _norm_path(path_str: str) -> str:
    """Normalize a room_paths value so './rooms' == 'rooms' == './rooms/'."""
    return str(pathlib.PurePosixPath(path_str))


def _listed_room_paths(lines: list[str], lo: int, hi: int) -> set[str]:
    """Normalized path values of (non-comment) room_paths items in range."""
    listed = set()
    for i in range(lo, hi):
        if installation.is_item(lines[i]):
            match = _ENTRY_RE.search(lines[i])
            if match:
                listed.add(_norm_path(match.group(1)))
    return listed


def room_parent_candidates(project: pathlib.Path) -> list[str]:
    """The ``room_paths`` entries that are *containers* (not single rooms).

    A caller offers these as a ``parent_path`` to install into. An entry is a
    container when it has no ``room_config.yaml`` of its own (Soliplex then
    discovers its immediate ``*/room_config.yaml`` subdirs as rooms). When
    ``room_paths`` is absent the backend default ``["./rooms"]`` applies, so
    the sole candidate is ``"./rooms"``.
    """
    env = project / ENVIRONMENT_DIR
    lines = (project / INSTALLATION_FILE).read_text().splitlines(keepends=True)
    span = installation.section_span(lines, sections.ROOM_PATHS.key)
    if span is None:
        return [ROOMS_PARENT_ENTRY]
    start, end = span
    candidates = []
    for i in range(start + 1, end):
        if not installation.is_item(lines[i]):
            continue
        match = _ENTRY_RE.search(lines[i])
        if match and not (env / match.group(1) / "room_config.yaml").is_file():
            candidates.append(match.group(1))
    return candidates


def _ensure_room_path(
    text: str, parent_path: str, room_id: str
) -> tuple[str, str]:
    """Ensure ``room_paths`` discovers ``{parent_path}/{room_id}``.

    Append-only and idempotent: the explicit entry already listed ⇒
    ``UNCHANGED``; ``parent_path`` listed as a container ⇒ ``COVERED``; the
    ``./rooms`` default covering it (absent section) ⇒ ``COVERED``; otherwise
    splice the *individual* room entry ⇒ ``ADDED`` (materializing the
    ``./rooms`` default first when the section is absent, so nothing already
    enabled is lost).
    """
    entry = f"{parent_path}/{room_id}"
    default = ROOMS_PARENT_ENTRY
    lines = text.splitlines(keepends=True)
    span = installation.section_span(lines, sections.ROOM_PATHS.key)
    if span is None:
        if _norm_path(parent_path) == _norm_path(default):
            return text, installation.TargetAction.COVERED
        block = [f'  - "{default}"\n', f'  - "{entry}"\n']
        return (
            installation.append_section(text, sections.ROOM_PATHS.key, block),
            installation.TargetAction.ADDED,
        )
    start, end = span
    # Compare normalized paths so './rooms', 'rooms', and './rooms/' (which
    # Soliplex resolves identically) all count as the same entry / container.
    listed = _listed_room_paths(lines, start + 1, end)
    if _norm_path(entry) in listed:
        return text, installation.TargetAction.UNCHANGED
    if _norm_path(parent_path) in listed:
        return text, installation.TargetAction.COVERED
    lines[start + 1 : start + 1] = [f'  - "{entry}"\n']
    return "".join(lines), installation.TargetAction.ADDED


@dataclasses.dataclass(frozen=True)
class RoomInstalled:
    """Outcome of ``install_room`` / ``install_room_from``: where the config
    went + the ``room_paths`` action (``added``/``covered``/``unchanged``)."""

    config_path: pathlib.Path
    path_action: str


# Backward-compatible alias for the pre-rename name.
RoomInstall = RoomInstalled


def _install_room(
    project: pathlib.Path,
    room_id: str,
    *,
    parent_path: str,
    write_contents,
    force: bool,
    dry_run: bool,
) -> RoomInstalled:
    """Shared skeleton: place the room under ``parent_path`` and wire
    ``room_paths``. ``write_contents(room_dir)`` populates the dir (unless
    ``dry_run``). Raises ``AddRoomError`` when ``parent_path`` is itself a
    room, or when the room dir already exists and ``force`` is false."""
    env = project / ENVIRONMENT_DIR
    if (env / parent_path / "room_config.yaml").is_file():
        raise AddRoomError.parent_is_room(env / parent_path)
    room_dir = env / parent_path / room_id
    config_path = room_dir / "room_config.yaml"
    if room_dir.exists() and not force:
        raise AddRoomError.room_exists(room_dir)

    installation_path = project / INSTALLATION_FILE
    new_text, path_action = _ensure_room_path(
        installation_path.read_text(), parent_path, room_id
    )

    if not dry_run:
        write_contents(room_dir)
        if path_action == installation.TargetAction.ADDED:
            installation_path.write_text(new_text)

    return RoomInstalled(config_path=config_path, path_action=path_action)


def install_room(
    project: pathlib.Path,
    room_id: str,
    *,
    config_text: str,
    prompt_text: str | None = None,
    parent_path: str,
    force: bool = False,
    dry_run: bool = False,
) -> RoomInstalled:
    """Install a rendered room under ``parent_path``; return ``RoomInstalled``.

    Writes ``<parent_path>/<room_id>/room_config.yaml`` (and ``prompt.txt``
    when ``prompt_text`` is given), and ensures ``room_paths`` discovers it.
    With ``dry_run`` it computes the outcome but writes nothing.
    ``config_text`` is template-agnostic -- any caller-produced room config.
    """

    def _write(room_dir: pathlib.Path) -> None:
        room_dir.mkdir(parents=True, exist_ok=True)
        (room_dir / "room_config.yaml").write_text(config_text)
        if prompt_text is not None:
            (room_dir / PROMPT_FILE_NAME).write_text(prompt_text)

    return _install_room(
        project,
        room_id,
        parent_path=parent_path,
        write_contents=_write,
        force=force,
        dry_run=dry_run,
    )


def install_room_from(
    project: pathlib.Path,
    room_id: str,
    src_dir: pathlib.Path,
    *,
    parent_path: str,
    force: bool = False,
    dry_run: bool = False,
) -> RoomInstalled:
    """Install a room by *copying* the ``src_dir`` template tree in.

    Copies ``src_dir`` to ``<parent_path>/<room_id>/`` (handling multi-file
    room templates -- e.g. ``room_config.yaml`` + ``prompt.txt``) and ensures
    ``room_paths`` discovers it. Unlike ``install_room`` (which writes a
    rendered config string), the caller does any post-copy patching of the
    written files itself, using the returned ``config_path``. With ``dry_run``
    it computes the outcome but writes nothing.
    """

    def _write(room_dir: pathlib.Path) -> None:
        shutil.copytree(src_dir, room_dir, dirs_exist_ok=True)

    return _install_room(
        project,
        room_id,
        parent_path=parent_path,
        write_contents=_write,
        force=force,
        dry_run=dry_run,
    )
