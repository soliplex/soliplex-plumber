# The section catalog

`sections` is pure data: what plumber knows about each editable
`installation.yaml` section, plus the constants that locate a stack's files. It
has no logic of its own — the [editors](installation.md) and the [room
installer](rooms.md) consult it to decide how an **absent** section behaves.

!!! info "Reference"
    Member-by-member: [`sections` in the API
    reference](../reference/api.md#sections-the-installationyaml-section-catalog).

## Why an absent section is not an empty one

This is the whole point of the catalog. "The section isn't there, so add it"
is right for some sections and actively harmful for others, because the backend
applies a different default to each:

| Family | Default when absent | So adding an entry... |
| --- | --- | --- |
| `DISCOVERY` | a directory (`room_paths` → `["./rooms"]`) | is already `COVERED` if it lives under that directory; writing the section must first materialize the default, or rooms already being discovered would stop being |
| `COLLECTION` | empty (`secrets` → `[]`) | means creating the section — nothing is lost |
| `WHITELIST` | permissive per `kind` (every discovered skill is enabled) | would flip that kind restrictive and disable everything not listed, so the editors report `COVERED` instead |

The catalog records which family each section belongs to, so that rule lives in
one place instead of being re-derived by every caller.

## Read a section's facts

```python
from soliplex_plumber import sections

sections.ROOM_PATHS.key                 # 'room_paths'
sections.ROOM_PATHS.family              # <Family.DISCOVERY: 'discovery'>
sections.ROOM_PATHS.discovery_default   # './rooms'

sections.META_TOOL_CONFIGS.key          # 'tool_configs'
sections.META_TOOL_CONFIGS.parent       # 'meta'

sections.SKILL_CONFIGS.kind_field       # 'kind'
```

The catalog entries are `ROOM_PATHS`, `ENVIRONMENT`, `SECRETS`,
`META_TOOL_CONFIGS` and `SKILL_CONFIGS`. `Section` is a frozen dataclass, so
the facts are read-only; the fields that do not apply to a family are `None`
(only `DISCOVERY` sections have a `discovery_default`, only `WHITELIST`
sections a `kind_field`, and only nested sections a `parent`).

Using the catalog rather than a string literal keeps a consumer honest if a
section is ever renamed:

```python
text, action = installation.add_list_entry(
    text,
    section=sections.SECRETS.key,
    block=['  - secret_name: "GITEA_TOKEN"\n'],
    probe=installation.FIELD_VALUE_RE("secret_name", "GITEA_TOKEN"),
)
```

## Locate a stack's files

The same module carries the stack-structure constants — the files and
directories that mark a generated stack and anchor every path the editors
resolve against:

```python
sections.COMPOSE_FILE        # 'docker-compose.yml'
sections.ENVIRONMENT_DIR     # PurePosixPath('backend/environment')
sections.INSTALLATION_FILE   # PurePosixPath('backend/environment/installation.yaml')
sections.ROOMS_DIR           # PurePosixPath('backend/environment/rooms')
sections.STACK_MARKERS       # ('docker-compose.yml', 'backend/environment/installation.yaml')
```

They are `PurePosixPath`s, so join them onto a resolved project root:

```python
installation_path = project / sections.INSTALLATION_FILE
```

`STACK_MARKERS` is the two markers every generated stack has. A consumer
needing a stricter check extends the tuple and hands it to
[`installation.resolve_stack`](installation.md#resolve-a-stack-with-your-own-markers).

!!! note "Re-exported by `rooms`"
    `rooms` re-exports `COMPOSE_FILE`, `ENVIRONMENT_DIR`, `INSTALLATION_FILE`
    and `ROOMS_DIR` under their historical names, so existing consumers keep
    working. New code should import them from `sections`, which is where they
    are defined.

## Keeping it in sync

The catalog mirrors `soliplex.config.installation` in the backend, which is the
actual source of truth for these defaults. It is a deliberate, reviewed copy —
plumber is stdlib-only and does not import the backend — so when the backend
changes a default, this module has to be updated to match.
