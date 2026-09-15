# Install a room

`rooms` is the template-agnostic core behind the `soliplex-template` skill's
`add_room.py` and the `soliplex-concierge` installer: it writes a room
directory into a stack's installation tree and makes sure `installation.yaml`
actually loads it.

!!! info "Reference"
    Member-by-member: [`rooms` in the API
    reference](../reference/api.md#rooms-install-a-room-into-a-soliplex-stack).

The governing rule is that **installing a room never disables another one**.
Every `room_paths` edit is append-only, and the implicit `./rooms` default is
materialized before any non-default parent is added, so a stack that was
relying on the default does not silently lose it.

## Resolve the stack first

`resolve_project` turns a directory string into a verified stack root. It
requires both markers a generated stack has — `docker-compose.yml` and
`backend/environment/installation.yaml` — so a typo in the path fails here
rather than half-way through an edit:

```python
from soliplex_plumber import rooms

project = rooms.resolve_project("/srv/stacks/acme-widgets")
```

It raises `ComposeNotFound` if there is no compose file and `NotAStack` if the
installation config is missing. Both derive from `AddRoomError`, so a CLI can
catch that one base class and print the message without a traceback.

!!! note "Two `resolve_project`s"
    [`stack.resolve_project`](stack.md) checks only for `docker-compose.yml`,
    because running a container does not require the installation tree to be
    valid. Use `rooms.resolve_project` when you are about to *edit* the
    installation.

## Install a room from a rendered config

Pass the room config as text. `rooms` never renders it for you — the caller
owns the template, `rooms` owns the wiring:

```python
config_text = """\
id: "handbook"
name: "Handbook"
description: "Answers questions about the employee handbook."
"""

installed = rooms.install_room(
    project=project,
    room_id="handbook",
    config_text=config_text,
    parent_path="./rooms",
)

installed.config_path   # <stack>/backend/environment/rooms/handbook/room_config.yaml
installed.path_action   # 'covered'
```

Every argument is keyword-only, including `project` and `room_id`.

To write a system prompt alongside the config, pass `prompt_text`; it lands in
`prompt.txt` next to `room_config.yaml`, which is the form the demo `search`
room uses:

```python
installed = rooms.install_room(
    project=project,
    room_id="handbook",
    config_text=config_text,
    prompt_text="You answer questions about the employee handbook.\n",
    parent_path="./rooms",
)
```

## Read the outcome

`install_room` returns a `RoomInstalled` with the config path it wrote and the
action it took on `room_paths`:

| `path_action` | What happened |
| --- | --- |
| `added` | an explicit `"<parent_path>/<room_id>"` entry was spliced into `room_paths` |
| `covered` | nothing to add — `parent_path` is already listed as a container, or `room_paths` is absent and the `./rooms` default already covers the room |
| `unchanged` | that exact entry was already listed |

The values are `installation.TargetAction` members, re-exported by `rooms` as
`ADDED` / `COVERED` / `UNCHANGED`:

```python
if installed.path_action == rooms.ADDED:
    print(f"wired {installed.config_path} into room_paths")
```

**`installation.yaml` is rewritten only for `added`.** The room directory
itself is written in all three cases (that is what you asked for); the config
file is left byte-for-byte alone when the room was already discoverable.

## Choose where the room goes

`parent_path` is relative to the installation config, and it must be a
*container* — a directory Soliplex scans for rooms — not a room itself.
`room_parent_candidates` reads the stack's `room_paths` and returns the entries
that qualify, which is what a CLI offers the operator:

```python
rooms.room_parent_candidates(project)   # ['./rooms']
```

An entry is a container when it has no `room_config.yaml` of its own; an entry
pointing straight at a single room is filtered out. When `room_paths` is absent
entirely the backend default applies, so the sole candidate is `"./rooms"`.

Passing a room as `parent_path` raises `ParentIsRoom` rather than nesting a
room inside another one.

### Installing outside the default container

Use any parent you like. The explicit entry is spliced in directly after the
`room_paths:` anchor:

```python
installed = rooms.install_room(
    project=project,
    room_id="handbook",
    config_text=config_text,
    parent_path="./shared",
)
installed.path_action   # 'added'
```

```yaml
# rooms loaded by this install
room_paths:
  - "./shared/handbook"
  - "./rooms"
  - "./shared/policy-bot"
```

Comments and the surrounding layout survive verbatim: the editors are
line-based, not a YAML round-trip.

When the stack has **no** `room_paths:` section at all, it is relying on the
`./rooms` default — and writing the section would replace that default rather
than extend it. So the default is materialized alongside the new entry, and the
rooms that were being discovered keep being discovered:

```yaml
name: "Acme Widgets"

room_paths:
  - "./rooms"
  - "./shared/handbook"
```

## Install a multi-file room template

When a room is more than a config file — a prompt, a skill directory, fixture
data — copy the tree instead of rendering a string. `install_room_from` does
the same wiring, but populates the room by copying `src_dir`:

```python
import pathlib

installed = rooms.install_room_from(
    project=project,
    room_id="about-acme-widgets",
    src_dir=pathlib.Path(__file__).parent / "templates" / "concierge",
    parent_path="./rooms",
)
```

The caller patches the copied files afterwards, using the returned
`config_path` as the anchor:

```python
config = installed.config_path
config.write_text(
    config.read_text(encoding="utf-8").replace("__PACKAGE__", package),
    encoding="utf-8",
)
```

## Try an edit without touching the live stack

Instead of a stack root, you can point either installer at an installation
tree directly with `environment=`. Combined with
[`stack.scratch_environment`](stack.md#work-against-a-scratch-copy) that gives
you a full rehearsal: install into a throwaway copy of
`backend/environment`, ask the real backend image to resolve it, and let the
copy evaporate:

```python
from soliplex_plumber import rooms, stack

with stack.scratch_environment(project) as env:
    rooms.install_room(
        environment=env.path,
        room_id="handbook",
        config_text=config_text,
        parent_path="./rooms",
    )
    result = env.run_cli(["config"])   # soliplex-cli sees the copy
    print(result.stdout)
```

Pass exactly one of `project=` or `environment=`; passing both or neither
raises `AmbiguousTarget`.

If you only want the *decision* and no files at all, use `dry_run=True` — the
outcome is computed and returned, nothing is written:

```python
planned = rooms.install_room(
    project=project,
    room_id="handbook",
    config_text=config_text,
    parent_path="./rooms",
    dry_run=True,
)
planned.path_action   # what a real run would do
```

## Overwrite an existing room

An existing room directory is an error, so a second run cannot quietly discard
a hand-edited room:

```python
try:
    rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=config_text,
        parent_path="./rooms",
    )
except rooms.RoomExists as exc:
    print(f"{exc.path} already exists")
```

Pass `force=True` to write over it. Note that `install_room_from` copies with
`dirs_exist_ok=True`, so forcing a template copy *merges* into the existing
directory: files in the template replace their counterparts, and files only the
stack has are left in place.

## Name the stack's own package

Rooms often reference a tool the stack itself ships, by dotted name. Rather
than making every caller guess, `resolve_package_name` infers it from the stack
layout:

```python
package = rooms.resolve_package_name(project, None)
tool_name = f"{package}.tools.greeting"
```

Pass a string as the second argument to override the inference; pass `None` to
infer. The resolution order is: the override, then the single project directory
under `src/` holding both a `pyproject.toml` and its own
`src/<name>/tools.py`, then the legacy `src/<pkg>/tools.py` layout, and finally
`rooms.DEFAULT_PACKAGE_NAME` (`"your_package"`) as a placeholder for the
operator to edit.

!!! warning "The legacy layout is deprecated"
    Resolving through `src/<pkg>/tools.py` emits a `DeprecationWarning` naming
    the restructuring that silences it — move the package to
    `src/<pkg>/src/<pkg>/` and its tests to `src/<pkg>/tests/`, with their own
    `pyproject.toml` beside them. Support for the old layout will be removed
    after `soliplex-plumber v0.6`.

## Validate a room id before using it

A room id is both a YAML id and a path segment, so it is checked against
`ROOM_ID_RE` — letters, digits, `.`, `_`, `-`, with no leading dot, no `/` and
no `..`. `install_room` does not call this for you; a CLI should, to reject bad
input before any work starts:

```python
try:
    rooms.validate_room_id(room_id)
except rooms.BadRoomId as exc:
    parser.error(str(exc))
```

## Handle the errors

| Raised | When | Catch it as |
| --- | --- | --- |
| `ComposeNotFound` | no `docker-compose.yml` at the target | `AddRoomError` |
| `NotAStack` | no `backend/environment/installation.yaml` | `AddRoomError` |
| `BadRoomId` | the room id is not a legal path segment / YAML id | `AddRoomError` |
| `ParentIsRoom` | `parent_path` has a `room_config.yaml` of its own | `AddRoomError` |
| `RoomExists` | the room directory exists and `force` is false | `AddRoomError` |
| `AmbiguousTarget` | neither or both of `project=` / `environment=` | `TypeError` |
| `RequiredArgument` | a required keyword (`room_id`, `src_dir`) was omitted | `TypeError` |

The first five are user-facing: catch `AddRoomError` at the top of a CLI and
print the message without a traceback. The last two subclass `TypeError`
instead, because a bad argument combination is a programmer error in the
calling code, not something the operator did.
