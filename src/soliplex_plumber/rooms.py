"""Install a room into a Soliplex stack, wiring its ``room_paths`` entry.

The shared core behind the ``soliplex-template`` skill's ``add_room.py``
and the ``soliplex-concierge`` installer.

Writes a room under an explicit ``parent_path``, relative to the
installation config, e.g. ``"./rooms"``.

Edits the confi's ``room_paths`` via line-based (comment-preserving) line
insertions, so that the room is discovered.

The governing principle is that installing a new room never disables another:
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
:mod:`soliplex_plumber.sections`.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import shutil
import warnings

from soliplex_plumber import installation
from soliplex_plumber import sections

# A room id usable as a path segment and a YAML id: no '/', no '..', no
# leading dot (mirrors rag_db.py's DB_NAME_RE).
ROOM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Placeholder when the stack's own package can't be inferred (no 'src/<pkg>/');
# the '<pkg>.tools.greeting' demo tool in the skill templates references it.
DEFAULT_PACKAGE_NAME = "your_package"
# The files 'resolve_package_name' keys on under '<project>/src/': a project
# directory is the one with a 'pyproject.toml'; the package the generator
# scaffolds is the one with a 'tools.py' (authored from the skill template).
PROJECT_MARKER = "pyproject.toml"
TOOLS_MARKER = "tools.py"
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
    """Base class for user-facing errors."""


class ComposeNotFound(AddRoomError):
    def __init__(self, path):
        self.path = path
        super().__init__(
            f"no {COMPOSE_FILE} at {path} "
            "(run with --project-dir pointing at the stack directory)"
        )


class NotAStack(AddRoomError):
    def __init__(self, path):
        self.path = path
        super().__init__(
            f"{path} is not a generated Soliplex stack: missing "
            f"'{INSTALLATION_FILE}'"
        )


class BadRoomId(AddRoomError):
    def __init__(self, room_id):
        self.room_id = room_id
        super().__init__(
            f"room id {room_id!r} must match {ROOM_ID_RE.pattern} "
            "(letters, digits, '.', '_', '-'; no leading dot)"
        )


class ParentIsRoom(AddRoomError):
    def __init__(self, path):
        self.path = path
        super().__init__(
            f"parent_path {path} is itself a room (has a room_config.yaml); "
            "pass a container directory to install rooms into"
        )


class RoomExists(AddRoomError):
    def __init__(self, path):
        self.path = path
        super().__init__(f"{path} already exists (use force to overwrite it)")


# The install entry points accept their target/selector arguments by keyword;
# a bad combination is a programmer error, so these subclass ``TypeError``
# (not ``AddRoomError``, which consumers catch as a user-facing failure).
class InstallArgError(TypeError):
    """A bad combination of ``install_room`` / ``install_room_from`` args."""


class AmbiguousTarget(InstallArgError):
    def __init__(self):
        super().__init__("pass exactly one of `project` or `environment`")


class RequiredArgument(InstallArgError):
    def __init__(self, name):
        self.name = name
        super().__init__(f"`{name}` is required")


def validate_room_id(room_id: str) -> None:
    if not ROOM_ID_RE.match(room_id):
        raise BadRoomId(room_id)


def resolve_project(project_dir: str) -> pathlib.Path:
    """Return the resolved stack root, or raise if it is not a stack."""
    project = pathlib.Path(project_dir).resolve()

    if not (project / COMPOSE_FILE).is_file():
        raise ComposeNotFound(project / COMPOSE_FILE)

    if not (project / INSTALLATION_FILE).is_file():
        raise NotAStack(project)

    return project


def _nested_package(child: pathlib.Path) -> bool:
    """Is ``child`` a project directory wrapping its own like-named package?

    The current generated layout: ``<project>/src/`` holds *project*
    directories -- ours alongside any sibling checkouts (dev-mode clones the
    ``soliplex`` repo there) -- so ours is the one that is both a project
    (a ``pyproject.toml``) and the home of a package named after it.
    """
    return (child / PROJECT_MARKER).is_file() and (
        child / "src" / child.name / TOOLS_MARKER
    ).is_file()


def _bare_package(child: pathlib.Path) -> bool:
    """Is ``child`` a package directory scaffolded straight under ``src/``?

    The legacy generated layout: ``<project>/src/<pkg>/tools.py``, with the
    stack root doubling as that package's project directory.
    """
    return (child / TOOLS_MARKER).is_file()


# Raised against a stack still on the pre-'src/<project>/' layout, naming the
# move that silences it (soliplex-template#176 restructures the generator).
_LEGACY_LAYOUT_MESSAGE = (
    "inferred the package {name!r} from the legacy layout "
    "'src/{name}/{tools}', which is deprecated: restructure the stack so "
    "that 'src/' holds project directories -- move the package to "
    "'src/{name}/src/{name}/{tools}' and the stack's 'tests/' to "
    "'src/{name}/tests/', with their own '{project}' beside them. "
    "Support for this layout style will be removed after "
    "'soliplex-plumber v0.6'."
)


def _sole_match(children: list[pathlib.Path], probe) -> str | None:
    """The name of the one child ``probe`` matches, else ``None``."""
    matches = [child.name for child in children if probe(child)]

    return matches[0] if len(matches) == 1 else None


def resolve_package_name(project: pathlib.Path, override: str | None) -> str:
    """Return the stack's own package, or a placeholder.

    Used e.g. to render the dotted name of the ``<pkg>.tools.greeting`` tool.

    Resolution order:

    - explicit ``override``

    - the single project directory under ``<project>/src/`` holding both a
      ``pyproject.toml`` and its own ``src/<name>/tools.py``, as the
      generator scaffolds it.

    - the single package directly under ``<project>/src/`` containing
      ``tools.py``, as the generator scaffolded the legacy layout. Resolving
      this way emits a ``DeprecationWarning`` naming the restructuring that
      silences it.

    - ``DEFAULT_PACKAGE_NAME`` for the operator to edit.
    """
    if override is not None:
        return override

    src = project / "src"

    if src.is_dir():
        children = [child for child in sorted(src.iterdir()) if child.is_dir()]

        # Sharpest first: the bare shape is consulted only once the current
        # (project-directory) shape has failed to name exactly one package.
        name = _sole_match(children, _nested_package)
        if name is not None:
            return name

        name = _sole_match(children, _bare_package)
        if name is not None:
            warnings.warn(
                _LEGACY_LAYOUT_MESSAGE.format(
                    name=name, tools=TOOLS_MARKER, project=PROJECT_MARKER
                ),
                DeprecationWarning,
                stacklevel=2,
            )
            return name

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
    """Get ``room_paths`` entries that are *containers* (not single rooms).

    A caller offers these as a ``parent_path`` to install into.

    An entry is a deemed container when it has no ``room_config.yaml`` of its
    own: Soliplex then discovers its immediate subdirs contaiing
    ``room_config.yaml`` as rooms).

    When ``room_paths`` is absent the backend default ``["./rooms"]``
    applies, so the sole candidate is ``"./rooms"``.
    """
    env = project / ENVIRONMENT_DIR
    lines = (
        (project / INSTALLATION_FILE)
        .read_text(encoding="utf-8")
        .splitlines(keepends=True)
    )
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

    Append-only and idempotent:

    - If the explicit entry already listed ⇒ ``UNCHANGED``;

    - If ``parent_path`` listed as a container ⇒ ``COVERED``;

    - If the ``./rooms`` default covering it (absent section) ⇒ ``COVERED``;

    - Else splice the *individual* room entry ⇒ ``ADDED``,
      first materializing the ``./rooms`` default when the section is absent,
      so nothing already enabled is lost.
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
    *,
    project: pathlib.Path | None,
    environment: pathlib.Path | None,
    room_id: str | None,
    parent_path: str,
    write_contents,
    force: bool,
    dry_run: bool,
) -> RoomInstalled:
    """Shared helper for room installation.

    Validate/map the target from ``project``/``environment``.

    Exactly one of ``project`` (a stack root, whose ``backend/environment``
    tree is used) or ``environment`` (that installation tree directly)
    must be passe.

    Place the created room under ``parent_path``

    Wire the room into stack's ``room_paths``.

    Unless ``dry_run`` is True, populate the room using
    `write_contents(room_dir)``.

    Raise ``AmbiguousTarget`` if neither ``project`` nor ``environment``
    is passed, or if both are passed.

    Raise ``RequiredArgument`` if ``room_id`` is not passed.

    Raise ``ParentIsRoom`` when ``parent_path`` is itself a room.

    Raise ``RoomExists`` when the room dir already exists and
    ``force`` is false;

    ``TypeError`` on a bad selector combination.
    """
    if (project is None) == (environment is None):
        raise AmbiguousTarget()

    if room_id is None:
        raise RequiredArgument("room_id")

    env = environment if environment is not None else project / ENVIRONMENT_DIR

    if (env / parent_path / "room_config.yaml").is_file():
        raise ParentIsRoom(env / parent_path)

    room_dir = env / parent_path / room_id
    config_path = room_dir / "room_config.yaml"

    if room_dir.exists() and not force:
        raise RoomExists(room_dir)

    installation_path = env / INSTALLATION_FILE.name
    new_text, path_action = _ensure_room_path(
        installation_path.read_text(encoding="utf-8"),
        parent_path,
        room_id,
    )

    if not dry_run:
        write_contents(room_dir)
        if path_action == installation.TargetAction.ADDED:
            installation_path.write_text(new_text, encoding="utf-8")

    return RoomInstalled(config_path=config_path, path_action=path_action)


def install_room(
    *,
    project: pathlib.Path | None = None,
    room_id: str | None = None,
    environment: pathlib.Path | None = None,
    config_text: str,
    prompt_text: str | None = None,
    parent_path: str,
    force: bool = False,
    dry_run: bool = False,
) -> RoomInstalled:
    """Install a room under ``parent_path``; wire into stack's ``room_paths``.

    Target is the stack indicated by either ``project`` (a stack root)
    or ``environment`` (its ``backend/environment`` installation tree,
    e.g. a scratch copy); pass exactly one.

    ``room_id`` is required.

    ``config_text`` is template-agnostic -- any caller-produced room config.

    Write ``config_text`` to ``<parent_path>/<room_id>/room_config.yaml``.

    Writ ``prompt_text``, if given, to ``<parent_path>/<room_id>/prompt.txt``.

    If ``dry_run`` is True, compute the outcome but write nothing.
    """

    def _write(room_dir: pathlib.Path) -> None:
        room_dir.mkdir(parents=True, exist_ok=True)
        (room_dir / "room_config.yaml").write_text(
            config_text, encoding="utf-8"
        )
        if prompt_text is not None:
            (room_dir / PROMPT_FILE_NAME).write_text(
                prompt_text, encoding="utf-8"
            )

    return _install_room(
        project=project,
        room_id=room_id,
        environment=environment,
        parent_path=parent_path,
        write_contents=_write,
        force=force,
        dry_run=dry_run,
    )


def install_room_from(
    *,
    project: pathlib.Path | None = None,
    room_id: str | None = None,
    src_dir: pathlib.Path | None = None,
    environment: pathlib.Path | None = None,
    parent_path: str,
    force: bool = False,
    dry_run: bool = False,
) -> RoomInstalled:
    """Install a room by copying ``src_dir``; wire into stack's ``room_paths``.

    Target is the stack indicated by either ``project`` (a stack root)
    or ``environment`` (its ``backend/environment`` installation tree,
    e.g. a scratch copy); pass exactly one.

    Unlike ``install_room`` (which writes a rendered config string), the
    caller does any post-copy patching of the written files itself, using
    the returned ``config_path``.

    If ``dry_run`` is True, compute the outcome but write nothing.
    """
    if src_dir is None:
        raise RequiredArgument("src_dir")

    def _write(room_dir: pathlib.Path) -> None:
        shutil.copytree(src_dir, room_dir, dirs_exist_ok=True)

    return _install_room(
        project=project,
        room_id=room_id,
        environment=environment,
        parent_path=parent_path,
        write_contents=_write,
        force=force,
        dry_run=dry_run,
    )
