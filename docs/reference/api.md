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

## `stack` — run `soliplex-cli` against a stack in a throwaway container

The shared plumbing for talking to a *running* stack. `soliplex-cli` ships only
inside the backend image, so this spins up a one-off `docker compose run --rm`
container pointed at a stack directory and runs the requested command — the
caller need not be *inside* a configured/running stack. It needs **Docker** on
`PATH`. `soliplex_config` builds on it, and the `soliplex-cli` skill uses it to
run arbitrary subcommands.

Every soliplex-cli command takes the in-container installation path as its
leaf-command positional, so `cli_args` is the subcommand (and options) *without*
that path: `run_cli` appends `installation`. By default the container uses the
stack's own bind mount; pass `host_environment` to bind that host tree onto
`installation` instead — pointing the one-off container at an alternative
installation (e.g. to dry-run changes). A consumer's CLI wires the options that
feed these calls via `add_arguments`.

| Member | Purpose |
| --- | --- |
| `require_docker()` | raise `DockerMissing` unless the Docker CLI is on `PATH` |
| `resolve_project(project_dir)` | resolve a stack root requiring a `docker-compose.yml`; raises `ComposeNotFound` |
| `cli_command(project, cli_args, *, service=…, cli=…, installation=…, host_environment=None, columns=…)` | build the `docker compose run … <cli> <*cli_args> <installation>` argv; only adds `-v <host_environment>:<installation>` when `host_environment` is given |
| `run_cli(project, cli_args, *, capture=True, check=True, …)` | `require_docker()` then run the command; `capture` returns output for parsing, else streams it; returns a `CompletedProcess` |
| `live_environment(project, *, service=…, installation=…, environment=…)` | context manager yielding an `Environment` for the stack's real installation tree (audited in place, no copy) |
| `scratch_environment(project, *, service=…, installation=…, environment=…)` | context manager yielding an `Environment` for a throw-away config-only copy of the tree (skips `*.lancedb`; removed on exit) |
| `Environment(path, project, service, installation)` | a selected installation tree bound to its stack; `.path` is the host bind source, `.run_cli(cli_args, **kw)` is `run_cli` pre-bound to `project` / `service` / `installation` / `host_environment=path` |
| `add_arguments(parser)` | add the `--project-dir` / `--service` / `--cli` / `--installation` / `--host-environment` options a consumer feeds to `resolve_project` / `run_cli` |
| `DEFAULT_SERVICE` / `DEFAULT_CLI` / `DEFAULT_INSTALLATION` / `DEFAULT_HOST_ENVIRONMENT` / `WIDE_COLUMNS` | the container defaults |
| `StackError` | base class for the user-facing errors (printed without a traceback) |
| `DockerMissing` / `ComposeNotFound` | the specific failure modes |

## `soliplex_config` — query a running stack's resolved installation config

Builds on `stack`: runs `soliplex-cli config <installation>` (via
`stack.run_cli`) and parses the resolved-config YAML. It installs the
**`soliplex-config`** console script (`run` wraps `main` with the user-facing
error handling) and backs a thin `soliplex-cli config` shim; the host-mapping
helpers honor the resolved `room_paths`, mapping each back through the backend's
`<host-environment> → <installation>` bind mount.

| Member | Purpose |
| --- | --- |
| `parse_config(stdout)` | parse the YAML body (banner comments and all) into a dict (`{}` if not a mapping) |
| `navigate(config, key)` | resolve a dotted `key` (mapping names / sequence indices) into the config; raises `KeyNotFound` |
| `render_value(value, fmt)` | render a value `plain` (scalar bare, list-of-scalars one per line, else YAML) or `yaml` |
| `map_to_host(container_path, installation, host_environment)` | map an in-container room path to its host location, or `None` when outside `installation` |
| `find_room_configs(room_dir)` | the `room_config.yaml` files under a path (single room or its immediate subdirs) |
| `read_room_meta(text)` | a room config's `{room_id, name, description}`, or `None` (not a mapping / no `id`) |
| `resolve_rooms(project, service, cli, installation, host_environment)` | the loaded rooms' `{room_id, name, description}` mappings + the unmapped container paths |
| `do_show` / `do_get` / `do_rooms` / `do_room` | the subcommand handlers (each takes the parsed `argparse.Namespace`) |
| `build_parser()` / `parse_args(argv)` / `main(argv)` | the `show`/`get`/`rooms`/`room` CLI; `main` returns the process exit code |
| `run()` | the `soliplex-config` console-script entry point — `main(sys.argv[1:])` with `stack.StackError` / `CalledProcessError` printed (no traceback) as exit code 2 |
| `SoliplexConfigError(stack.StackError)` | base class for the config-specific errors below |
| `NoRoomPaths` / `KeyNotFound` / `RoomNotFound` | the specific failure modes |
