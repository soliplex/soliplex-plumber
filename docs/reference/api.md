# API reference

!!! note "Implemented"
    This is the library's public surface. Every member below is implemented
    and covered by the test suite (100% branch coverage); the modules under
    `src/soliplex_plumber/` are the source of truth.

There is no re-exporting package `__init__` — **client code imports the
submodule and uses its members by dotted name** (e.g. `from soliplex_plumber
import rooms` then `rooms.install_room(...)`).

## `rooms` — add a room to a Soliplex stack

Generic, template-agnostic, stdlib-only logic for wiring a room into a generated
stack. The shared core behind both the `soliplex-template` skill's `add_room.py`
and the `soliplex-concierge` installer; it edits `installation.yaml` line-based so
comments and layout are preserved.

| Member | Purpose |
| --- | --- |
| `validate_room_id(room_id)` | enforce the room-id / path-segment rule (`ROOM_ID_RE`); raises `AddRoomError` |
| `resolve_project(project_dir)` | resolve + verify the stack root (has `COMPOSE_FILE` and `INSTALLATION_FILE`) |
| `resolve_package_name(project, override)` | the stack's own package (inferred from `src/<pkg>/tools.py`) or `DEFAULT_PACKAGE_NAME` |
| `add_room_path(text, room_id) -> (text, action)` | ensure `room_paths` loads the room; action is `ADDED` / `UNCHANGED` / `COVERED` |
| `install_room(project, room_id, *, config_text, prompt_text=None, force=False, dry_run=False)` | write the room dir + config (+ optional prompt) and apply the `room_paths` edit |
| `RoomInstalled(config_path, path_action)` | the `install_room` outcome (alias `RoomInstall` kept for back-compat) |
| `AddRoomError` | user-facing error with message-factory classmethods |
| `ADDED` / `UNCHANGED` / `COVERED` / `ROOMS_PARENT_ENTRY` | the `room_paths` action constants and the `./rooms` auto-discovery entry |
