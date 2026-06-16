# `soliplex-plumber`: tools for modifying a Soliplex stack

Stdlib-only library for reading and modifying the configuration of an
*existing* Soliplex stack. It is the shared dependency for the skill projects
that operate on a generated stack — the `soliplex-template` skill's
`add_room.py` and the `soliplex-concierge` installer — so the stack-wiring
rules live in one place.

It does pure filesystem work: no Docker, no running backend.

## What it provides

- **`rooms`** — generic, template-agnostic logic for adding a room to a stack:
  resolve and validate the stack root, infer its package, and ensure
  `installation.yaml`'s `room_paths` loads the room (editing line-based, so
  comments and layout are preserved).

```python
from soliplex_plumber import rooms

project = rooms.resolve_project("/path/to/stack")
installed = rooms.install_room(project, "handbook", config_text=cfg)
```

Full documentation: <https://soliplex.github.io/soliplex-plumber/>
