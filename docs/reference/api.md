# API reference

!!! note "Implemented"
    This is the library's public surface. Every member below is implemented
    and covered by the test suite (100% branch coverage); the modules under
    `src/soliplex_plumber/` are the source of truth.

There is no re-exporting package `__init__` — **client code imports the
submodule and uses its members by dotted name** (e.g. `from soliplex_plumber
import rooms` then `rooms.install_room(...)`).

## `sections` — the installation.yaml section catalog

Declarative facts about each editable `installation.yaml` section, mirroring the
defaults the backend applies in `soliplex.config.installation` (the source of
truth). The editors consult it to decide an absent section's behavior.

| Member | Purpose |
| --- | --- |
| `Family` (`DISCOVERY` / `COLLECTION` / `WHITELIST`) | how a section behaves when an entry is added |
| `Section(key, family, parent=None, discovery_default=None, kind_field=None)` | one section's declarative facts |
| `ROOM_PATHS` / `ENVIRONMENT` / `SECRETS` / `META_TOOL_CONFIGS` / `SKILL_CONFIGS` | the catalog entries |
| `COMPOSE_FILE` / `ENVIRONMENT_DIR` / `INSTALLATION_FILE` / `ROOMS_DIR` / `STACK_MARKERS` | stack-structure constants (re-exported by `rooms`) |

The families: **discovery** lists default to a directory (`room_paths` →
`["./rooms"]`), so an entry beneath the default is already *covered* when the
section is absent; **collection** sections default to empty, so an absent section
is *created* to add an entry; **whitelist** (`skill_configs`) is permissive per
`kind` — empty/absent for a kind enables every discovered skill of it.

## `installation` — edit a stack's `installation.yaml`

Generic, comment-preserving, idempotent, stdlib-only line editors. Each is a
pure `text -> (new_text, TargetAction)` function. Scanning is **section-scoped**
and **comment-skipping**.

| Member | Purpose |
| --- | --- |
| `add_list_entry(text, *, section, block, probe)` | add `block` under a top-level collection `section:`; create it if absent |
| `add_nested_list_entry(text, *, parent, section, item, probe)` | add `item` under nested `parent.section:`; create parent/child if absent |
| `add_environment(text, var_name)` | add `var_name` to `environment:` |
| `add_secret(text, secret_name, *, env_var_name=None)` | add an `env_var`-sourced secret to `secrets:` |
| `add_meta_tool_config(text, class_path)` | register `class_path` under nested `meta.tool_configs:` |
| `add_skill_config(text, skill_name, *, kind="filesystem", confirm=False)` | whitelist a skill; `COVERED` when the kind is permissive; raises `WhitelistActive` when a kind's whitelist is active (unless `confirm`) |
| `resolve_stack(stack_dir, markers, error)` | resolve a stack root requiring every marker; `error(stack, marker)` builds the raised exception |
| `WhitelistActive(kind, entries)` | the one "stop and confirm" abort — a `skill_configs` kind already has an explicit whitelist |
| `section_span` / `is_item` / `append_section` | low-level scoped, comment-aware scan helpers (shared with `rooms`) |
| `TargetAction(StrEnum)` (`ADDED` / `UNCHANGED` / `COVERED`) | the action a helper reports |

## `rooms` — install a room into a Soliplex stack

Writes a room under an explicit `parent_path` (relative to the installation
config) and wires its `room_paths` entry line-based. Append-only: installing a
room never disables another (the `./rooms` default is materialized before any
non-default parent is added).

| Member | Purpose |
| --- | --- |
| `validate_room_id(room_id)` | enforce the room-id / path-segment rule (`ROOM_ID_RE`); raises `BadRoomId` |
| `resolve_project(project_dir)` | resolve + verify the stack root (has `COMPOSE_FILE` and `INSTALLATION_FILE`) |
| `resolve_package_name(project, override)` | the stack's own package (inferred from `src/<pkg>/tools.py`) or `DEFAULT_PACKAGE_NAME` |
| `room_parent_candidates(project)` | the `room_paths` container entries a caller can offer as a `parent_path` (or `["./rooms"]` when absent) |
| `install_room(project, room_id, *, config_text, prompt_text=None, parent_path, force=False, dry_run=False)` | write the room dir from a rendered `config_text` (+ optional prompt) under `parent_path` and wire `room_paths` |
| `install_room_from(project, room_id, src_dir, *, parent_path, force=False, dry_run=False)` | the same, but *copy* the `src_dir` template tree (multi-file); the caller patches the copied files afterward |
| `RoomInstalled(config_path, path_action)` | the install outcome (alias `RoomInstall` kept for back-compat) |
| `AddRoomError` | base class for user-facing errors |
| `ComposeNotFound(AddRoomError)` | No `docker-compose.yaml` found |
| `NotAStack(AddRoomError)` | target lacks required template-generated files |
| `BadRoomId(AddRoomError)` | invalid room ID syntac |
| `ParentIsRoom(AddRoomError)` | room directory exists |
| `RoomExists(AddRoomError)` | Allows users to catch this error specifically |
| `ADDED` / `UNCHANGED` / `COVERED` | the `installation.TargetAction` members, re-exported |
| `ROOMS_PARENT_ENTRY` | the `./rooms` default-discovery container |
