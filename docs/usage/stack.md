# Run `soliplex-cli`

`soliplex-cli` ships only inside the backend image, so there is no host-side
command to run against a stack directory. `stack` closes that gap: it spins up
a one-off `docker compose run --rm` container pointed at the stack and runs the
CLI inside it. The caller does not need to be *inside* a configured or running
stack — only to have the stack on disk and the Docker CLI on `PATH`.

!!! info "Reference"
    Member-by-member: [`stack` in the API
    reference](../reference/api.md#stack-run-soliplex-cli-against-a-stack-in-a-throwaway-container).

## Run a command

```python
from soliplex_plumber import stack

project = stack.resolve_project(".")
result = stack.run_cli(project, ["config"])
print(result.stdout)
```

`resolve_project` here requires only `docker-compose.yml` — running a container
does not depend on the installation tree being valid — and raises
`ComposeNotFound` otherwise. `run_cli` calls `require_docker()` first, so a
missing Docker CLI fails as `DockerMissing` rather than as a `FileNotFoundError`
from deep inside `subprocess`.

### What goes in `cli_args`

Every soliplex-cli command takes the in-container installation path as its
leaf-command positional, and `run_cli` appends it for you. So `cli_args` is the
subcommand and its options **without** that trailing path — `["config"]`
becomes `soliplex-cli config /environment`.

### Capture or stream

`capture=True` (the default) collects stdout and stderr on the returned
`CompletedProcess`, which is what you want when you are going to parse the
output. Pass `capture=False` to let the command stream straight to your own
stdout/stderr — the right choice for a CLI that is just relaying output to a
human:

```python
stack.run_cli(project, ["config"], capture=False)
```

`check=True` (the default) raises `subprocess.CalledProcessError` on a non-zero
exit. Pass `check=False` when a non-zero exit is a legitimate answer you want
to inspect rather than an error.

Long lines are a hazard when parsing: the container is run with
`COLUMNS=10000` (`stack.WIDE_COLUMNS`) so that `rich`-formatted output does not
wrap. Override it with `columns=` if you actually want terminal-width output.

The container's output is decoded as UTF-8, not in the host locale encoding.
On a Windows host that fallback is `cp1252`, which would mangle a non-ASCII
room name on its way back out of `soliplex-cli`.

## See the command without running it

`cli_command` builds the argv that `run_cli` would execute. It touches nothing
and needs no Docker, which makes it the thing to print in a `--dry-run` mode or
assert on in a test:

```python
print(" ".join(stack.cli_command(project, ["config"])))
```

```text
docker compose --project-directory /srv/stacks/acme-widgets run --rm --no-TTY \
  -e COLUMNS=10000 backend /app/.venv/bin/soliplex-cli config /environment
```

The defaults in that line are all overridable: `service` (`backend`), `cli`
(`/app/.venv/bin/soliplex-cli`), and `installation` (`/environment`), exposed as
`DEFAULT_SERVICE`, `DEFAULT_CLI` and `DEFAULT_INSTALLATION`.

## Point the container at a different tree

By default the container uses the stack's own bind mount, so the CLI sees the
deployed installation. Pass `host_environment` — a path relative to the project
— to bind that host tree onto the in-container `installation` path instead.
Only then does the argv grow a `-v <host tree>:<installation>` flag:

```python
result = stack.run_cli(project, ["config"], host_environment="alt")
```

That is the whole mechanism behind dry-running a change: build a modified tree
on the host, then ask the real backend image to resolve it.

The two context managers wrap the choice up so callers do not have to build the
path themselves. Both yield an `Environment` — the selected host tree bound to
its stack.

### Audit the live tree

`live_environment` yields an `Environment` over the stack's real
`backend/environment`. Nothing is copied; the tree is read in place:

```python
with stack.live_environment(project) as env:
    print(env.path)                  # <stack>/backend/environment
    result = env.run_cli(["config"])
```

### Work against a scratch copy

`scratch_environment` copies the installation tree into a temporary directory
**inside the project** — so the bind source stays reachable by the Docker
daemon — yields an `Environment` bound to the copy, and removes it on exit:

```python
with stack.scratch_environment(project) as env:
    (env.path / "installation.yaml").write_text(edited_text)
    result = env.run_cli(["config"])   # resolves the copy, not the stack
# the copy is gone here
```

The copy skips `*.lancedb`, so a stack whose RAG database happens to live
inside the environment tree does not make every rehearsal expensive.

This is also the target to hand to the room installers, which accept an
installation tree directly — see [Try an edit without touching the live
stack](rooms.md#try-an-edit-without-touching-the-live-stack).

### The bound runner

`Environment.run_cli` is `run_cli` with this stack's `project`, `service`,
`installation` and `host_environment=path` already applied, so call it with
just the subcommand (plus `capture` / `check` if you need them):

```python
env.run_cli(["config"], capture=False)
```

## Wire the options into your own CLI

`add_arguments` adds the five options that feed `resolve_project` and
`run_cli`, so every consumer spells them the same way:

```python
import argparse
from soliplex_plumber import stack

parser = argparse.ArgumentParser()
stack.add_arguments(parser)
args = parser.parse_args()

project = stack.resolve_project(args.project_dir)
result = stack.run_cli(
    project,
    ["config"],
    service=args.service,
    cli=args.cli,
    installation=args.installation,
    host_environment=args.host_environment,
)
```

That gives the user `--project-dir` (default `.`), `--service`, `--cli`,
`--installation` and `--host-environment`. The
[`soliplex-config`](soliplex-config.md) CLI is built exactly this way, once per
subcommand.

## Handle the errors

`DockerMissing` and `ComposeNotFound` both derive from `StackError`, which
exists so a console script can catch one class and print the message without a
traceback. A failed command surfaces separately, as
`subprocess.CalledProcessError`:

```python
import subprocess
import sys

try:
    result = stack.run_cli(project, ["config"])
except stack.StackError as exc:
    print(f"error: {exc}", file=sys.stderr)
    sys.exit(2)
except subprocess.CalledProcessError as exc:
    print(f"error: command failed ({exc})", file=sys.stderr)
    sys.exit(2)
```

`soliplex_config.run` is this handler; see
[Query a running stack](soliplex-config.md).
