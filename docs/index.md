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
  comments and layout are preserved). See the
  [API reference](reference/api.md).
- **`stack`** -- shared plumbing to run `soliplex-cli` against a stack in a
  throwaway `docker compose run --rm` container (validate the stack, build the
  argv, capture or stream output), optionally binding an alternative
  installation tree to dry-run against. Needs Docker.
- **`soliplex_config`** -- query a *running* stack's resolved installation
  config via `soliplex-cli config` in a one-off backend container (`show` /
  `get` / `rooms` / `room`); installs the `soliplex-config` console script.
  Builds on `stack`.

There is no re-exporting package `__init__`; client code imports the submodule
and uses its members by dotted name:

```python
from soliplex_plumber import rooms

project = rooms.resolve_project("/path/to/stack")
installed = rooms.install_room(project, "handbook", config_text=cfg)
```
