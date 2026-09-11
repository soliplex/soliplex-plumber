# How-to guides

Task-oriented recipes for the public modules, with worked examples. Each page
documents one module and links to its entry in the
[API reference](../reference/api.md), which stays the terse "what exists" list.

## Which module do I need?

| I want to... | Go to |
| --- | --- |
| add a room to a stack, and make the stack load it | [Install a room](rooms.md) |
| add a secret, an environment variable, a tool config, or a skill to `installation.yaml` | [Edit `installation.yaml`](installation.md) |
| run `soliplex-cli` against a stack on disk, or against a scratch copy of it | [Run `soliplex-cli`](stack.md) |
| read back what a *running* stack actually resolved | [Query a running stack](soliplex-config.md) |
| know how an *absent* `installation.yaml` section behaves | [The section catalog](sections.md) |

## Two kinds of work

The library splits along one line — whether the recipe needs Docker:

- **Pure filesystem.** [`rooms`](rooms.md), [`installation`](installation.md)
  and [`sections`](sections.md) read and rewrite files under a stack
  directory. No Docker, no running backend, stdlib only. The stack does not
  even have to be up.
- **A running stack.** [`stack`](stack.md) and
  [`soliplex_config`](soliplex-config.md) run `soliplex-cli` inside a one-off
  backend container, because that CLI ships only in the backend image. These
  need the Docker CLI on `PATH`.

The two meet in one useful place: you can make filesystem edits against a
*scratch copy* of a stack's installation tree and then point the container at
the copy, so nothing touches the deployed tree until the edit checks out. See
[Try an edit without touching the live stack](rooms.md#try-an-edit-without-touching-the-live-stack).

## Importing

There is no re-exporting package `__init__`. Import the submodule and use its
members by dotted name:

```python
from soliplex_plumber import rooms

project = rooms.resolve_project("/srv/stacks/acme-widgets")
```
