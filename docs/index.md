# Soliplex Plumber

`soliplex-plumber` is the shared library for reading and
modifying the configuration of an *existing* Soliplex stack. It is the common
dependency for the skill projects that operate on a generated stack -- the
`soliplex-template` skill's `add_room.py` and the `soliplex-concierge`
installer -- so the stack-wiring rules live in one place.

!!! note "Status"
    The library is implemented and tested (100% branch coverage). The core
    (`rooms` / `installation` / `sections`) does pure filesystem work -- no
    Docker, no running backend. The `soliplex_config` module is the
    exception: it queries a *running* stack, so it needs Docker.

## What it provides

- **`rooms`** -- generic, template-agnostic logic for adding a room to a stack:
  resolve and validate the stack root, infer its package, and ensure
  `installation.yaml`'s `room_paths` loads the room (editing line-based, so
  comments and layout are preserved). See [Install a room](usage/rooms.md).
- **`installation`** -- the section-aware, comment-preserving
  `installation.yaml` editors (secrets, environment variables, tool configs,
  skills), and **`sections`**, the catalog of section defaults they consult.
  See [Edit `installation.yaml`](usage/installation.md) and
  [The section catalog](usage/sections.md).
- **`stack`** -- shared plumbing to run `soliplex-cli` against a stack in a
  throwaway `docker compose run --rm` container (validate the stack, build the
  argv, capture or stream output), optionally binding an alternative
  installation tree to dry-run against. Needs Docker. See
  [Run `soliplex-cli`](usage/stack.md).
- **`soliplex_config`** -- query a *running* stack's resolved installation
  config via `soliplex-cli config` in a one-off backend container (`show` /
  `get` / `rooms` / `room`); installs the `soliplex-config` console script.
  Builds on `stack`. See [Query a running stack](usage/soliplex-config.md).

There is no re-exporting package `__init__`; client code imports the submodule
and uses its members by dotted name:

```python
from soliplex_plumber import rooms

project = rooms.resolve_project("/path/to/stack")
installed = rooms.install_room(
    project=project,
    room_id="handbook",
    config_text=cfg,
    parent_path="./rooms",
)
```

Start with the [how-to guides](usage/index.md) for worked examples of each
module, or the [API reference](reference/api.md) for the member-by-member list.
