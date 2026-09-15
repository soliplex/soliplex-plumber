# Query a running stack

Everything else in `soliplex-plumber` reads the files you wrote.
`soliplex_config` reads what the backend actually *resolved* from them —
defaults applied, includes merged, `room_paths` expanded to container paths. It
runs `soliplex-cli config` in a one-off backend container (via
[`stack`](stack.md)) and parses the YAML it prints, so it needs Docker on
`PATH`.

!!! info "Reference"
    Member-by-member: [`soliplex_config` in the API
    reference](../reference/api.md#soliplex_config-query-a-running-stacks-resolved-installation-config).

## The `soliplex-config` command

Installing the package installs a `soliplex-config` console script with four
subcommands, from coarsest to finest. Each takes the
[stack-targeting options](stack.md#wire-the-options-into-your-own-cli)
(`--project-dir`, `--service`, `--cli`, `--installation`,
`--host-environment`).

### `show` — the whole resolved config

```console
$ soliplex-config show --project-dir /srv/stacks/acme-widgets
#------------------------------------------------------------------------------
# Source: /environment
#------------------------------------------------------------------------------
id: acme-widgets
server_name: Acme Widgets
server_description: Internal assistants for Acme Widgets.
meta:
  tool_configs:
  - acme_widgets.tools.WidgetTools
secrets:
- secret_name: GITEA_TOKEN
  sources:
  - kind: env_var
    env_var_name: GITEA_TOKEN
environment:
  OLLAMA_BASE_URL: http://ollama:11434
room_paths:
- /environment/rooms/handbook
- /environment/shared/policy-bot
# ... and the remaining keys (agent_configs, oidc_paths, quizzes_paths, ...)
```

The faithful `soliplex-cli config` output, banner comments and all. Start here
when you do not yet know which key you want.

### `get` — one value by dotted path

Each `.`-separated segment indexes a mapping by name or a sequence by position:

```console
$ soliplex-config get server_name
Acme Widgets

$ soliplex-config get meta.tool_configs
acme_widgets.tools.WidgetTools

$ soliplex-config get room_paths
/environment/rooms/handbook
/environment/shared/policy-bot

$ soliplex-config get room_paths.0
/environment/rooms/handbook
```

The default `plain` format is shell-friendly: a scalar prints bare, and a list
of scalars prints one per line, so `get room_paths` pipes straight into a
loop. Anything nested falls back to a YAML dump. Pass `--format yaml` to get
YAML for *any* value, including scalars:

```console
$ soliplex-config get room_paths --format yaml
- /environment/rooms/handbook
- /environment/shared/policy-bot
```

An unknown key, an index past the end, or descending into a scalar all fail
the same way:

```console
$ soliplex-config get nope
error: no key 'nope' in the resolved installation config (use 'show' to inspect the available keys)
```

### `rooms` — what the stack actually loads

A convenience over `get room_paths` that reports the rooms themselves:

```console
$ soliplex-config rooms
- room_id: handbook
  name: Handbook
  description: Answers questions about the employee handbook.
- room_id: policy-bot
  name: Policy Bot
  description: null
```

This is driven by the *resolved* `room_paths`, which is why it beats globbing
`rooms/*`: it honors an installation that limits its room set or points at
shared directories, and it shows rooms that live outside the conventional
directory. Each container path is mapped back to the host through the
backend's `<host-environment>` → `<installation>` bind mount, and every
`room_config.yaml` beneath it is read on the host — a `room_paths` entry may
name a single room or a directory of them.

Room id conflicts resolve first-past-the-post, matching the backend. A room
path that lies outside `--installation` (an exotic shared mount) cannot be
mapped to a host file; those are reported on stderr and skipped rather than
silently dropped.

### `room` — one room's config, verbatim

```console
$ soliplex-config room handbook
# The handbook room: answers from the handbook RAG database only.
id: handbook
name: Handbook
description: Answers questions about the employee handbook.
system_prompt: "file:prompt.txt"
```

Prints the full `room_config.yaml` of the loaded room with that id — comments
and all, because it is the file, not a re-dump. Errors with `RoomNotFound` if
no loaded room has that id.

## Query an alternative tree

`--host-environment` binds a host directory onto the in-container installation
path, so you can resolve a tree the stack is not actually deployed with. That
is how you check an edit before shipping it:

```console
$ soliplex-config rooms --host-environment alt
- room_id: handbook
  name: Handbook
  description: Answers questions about the employee handbook.
- room_id: policy-bot
  name: Policy Bot
  description: null
- room_id: onboarding
  name: Onboarding
  description: null
```

The `onboarding` room is the edit under test: it exists in the `alt` tree, and
not yet in the one the stack is deployed with.

## Use it as a library

The subcommands are thin wrappers over functions you can call directly. The
parse/navigate/render trio works on captured output and needs no Docker of its
own:

```python
from soliplex_plumber import soliplex_config, stack

project = stack.resolve_project(".")
result = stack.run_cli(project, ["config"])

config = soliplex_config.parse_config(result.stdout)
value = soliplex_config.navigate(config, "room_paths.0")
print(soliplex_config.render_value(value, "plain"))
```

`parse_config` loads the whole stream — the `#` banner is a YAML comment — and
returns `{}` for anything that is not a mapping. `navigate` raises `KeyNotFound`
for a missing key, a non-integer or out-of-range index, or a descent past a
scalar.

To get the loaded rooms without shelling out to the CLI:

```python
rooms, unmapped = soliplex_config.resolve_rooms(
    project,
    stack.DEFAULT_SERVICE,
    stack.DEFAULT_CLI,
    stack.DEFAULT_INSTALLATION,
    None,
)

for room in rooms:
    print(room["room_id"], "-", room["name"])

for container_path in unmapped:
    print(f"outside the bind mount, skipped: {container_path}")
```

`resolve_rooms` returns the `{room_id, name, description}` mappings in
`room_paths` order, plus the container paths it could not map to the host. The
last argument is `host_environment`; pass `None` to use the stack's own mount.

Three smaller helpers are public because they are useful on their own, and they
touch no container:

```python
import pathlib

host_dir = soliplex_config.map_to_host(
    "/environment/rooms/handbook",
    "/environment",
    pathlib.Path("/srv/stacks/acme-widgets/backend/environment"),
)
# PosixPath('/srv/stacks/acme-widgets/backend/environment/rooms/handbook')

configs = soliplex_config.find_room_configs(host_dir)
meta = soliplex_config.read_room_meta(configs[0].read_text())
# {'room_id': 'handbook', 'name': 'Handbook', 'description': None}
```

`map_to_host` returns `None` when the path is not under the mount you know
about. `find_room_configs` treats a directory holding a `room_config.yaml` as a
single room and otherwise scans its immediate, non-hidden subdirectories; a
listed-but-absent path yields nothing. `read_room_meta` returns `None` when the
document is not a mapping or has no `id`.

## Handle the errors

The config-specific failures — `NoRoomPaths`, `KeyNotFound`, `RoomNotFound` —
derive from `SoliplexConfigError`, which derives from `stack.StackError`. One
`except stack.StackError` therefore catches both these and the shared Docker /
compose failures:

```python
import sys

try:
    exit_code = soliplex_config.main(sys.argv[1:])
except stack.StackError as exc:
    print(f"error: {exc}", file=sys.stderr)
    exit_code = 2
```

That is what `run` — the `soliplex-config` entry point — does, adding
`subprocess.CalledProcessError` for a soliplex-cli invocation that itself
failed. Both print without a traceback and exit **2**. Use `main(argv)` when
you want the exit code and your own error handling; use `run()` when you want
the console script's behavior.
