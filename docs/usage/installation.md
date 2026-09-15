# Edit `installation.yaml`

`installation` holds the generic, comment-preserving editors for a stack's
`installation.yaml`. They are line-based rather than a YAML round-trip, so
comments, key order, quoting style and blank lines all survive an edit
verbatim — the operator's file stays the operator's file.

!!! info "Reference"
    Member-by-member: [`installation` in the API
    reference](../reference/api.md#installation-edit-a-stacks-installationyaml).

## The shape of every edit

Each editor is a pure function from text to `(new_text, action)`. It does no
I/O: you read the file, pass the text through one or more editors, and write it
back if anything changed.

```python
import pathlib

from soliplex_plumber import installation, sections

path = pathlib.Path(project) / sections.INSTALLATION_FILE
text = path.read_text(encoding="utf-8")

text, action = installation.add_secret(text, "GITEA_TOKEN")

if action is installation.TargetAction.ADDED:
    path.write_text(text, encoding="utf-8")
```

Keeping the write in the caller's hands is what makes the editors composable
(below) and trivially dry-runnable — drop the `write_text` and you have a
preview. It also puts the encoding in your hands: `installation.yaml` is UTF-8
by specification, so pass `encoding="utf-8"` rather than inheriting the host
locale encoding (`cp1252` on Windows), which would mangle a non-ASCII comment
or room description on the way through.

### What the action tells you

| Action | Meaning |
| --- | --- |
| `ADDED` | the entry was spliced in; `new_text` differs |
| `UNCHANGED` | an equivalent entry was already there; `new_text` is the input |
| `COVERED` | no edit needed — a default or a parent entry already satisfies the target, and making the edit would *narrow* the config |

`COVERED` is the interesting one, and it is why the editors consult the
[section catalog](sections.md): an absent section is not an empty section. See
[Whitelist a skill](#whitelist-a-skill) for the case where writing the
"obvious" entry would turn other things off.

## Add an environment variable

Adds a `- "NAME"` bullet under the top-level `environment:` list, creating the
section if the file does not have one:

```python
text, action = installation.add_environment(text, "GITEA_URL")
```

## Add a secret

Writes the full `env_var`-sourced secret block — the helper owns the YAML
shape, you supply the values:

```python
text, action = installation.add_secret(text, "GITEA_TOKEN")
```

```yaml
secrets:
  - secret_name: "GITEA_TOKEN"
    sources:
      - kind: "env_var"
        env_var_name: "GITEA_TOKEN"
```

The environment variable defaults to the secret name; pass `env_var_name` when
they differ:

```python
text, action = installation.add_secret(
    text, "gitea-token", env_var_name="GITEA_TOKEN"
)
```

A second call with the same `secret_name` returns `UNCHANGED` and the input
text, so re-running an installer is safe.

## Register a meta tool config

`meta.tool_configs` is nested, so this one creates the `meta:` parent and the
`tool_configs:` child as needed:

```python
text, action = installation.add_meta_tool_config(
    text, "acme_widgets.tools.WidgetTools"
)
```

```yaml
meta:
  tool_configs:
    - "acme_widgets.tools.WidgetTools"
```

## Whitelist a skill

`skill_configs` is a per-`kind` whitelist, and an *empty* whitelist for a kind
is permissive: every discovered skill of that kind is enabled. So blindly
appending your skill is the one edit here that can turn other things off — it
flips the kind from "everything" to "only what is listed". `add_skill_config`
refuses to do that silently:

```python
try:
    text, action = installation.add_skill_config(text, "soliplex-concierge-room")
except installation.WhitelistActive as exc:
    print(f"{exc.kind} skills already whitelisted: {', '.join(exc.entries)}")
    text, action = installation.add_skill_config(
        text, "soliplex-concierge-room", confirm=True
    )
```

The three outcomes:

- the skill is already listed → `UNCHANGED`;
- the kind has **no** entries, including an absent section → `COVERED`; the
  skill is already enabled, and adding it would disable the stack's other
  skills of that kind;
- the kind has an explicit whitelist and your skill is not in it → raise
  `WhitelistActive`, unless `confirm=True`, in which case it is appended →
  `ADDED`.

`WhitelistActive` carries `.kind` and `.entries` so a CLI can show the operator
exactly what is currently whitelisted before asking them to confirm. `kind`
defaults to `"filesystem"`.

## Compose several edits

Because each editor threads the text through, a multi-part installer is a
straight sequence, and a single write at the end:

```python
actions = {}

text, actions["env"] = installation.add_environment(text, "GITEA_URL")
text, actions["secret"] = installation.add_secret(text, "GITEA_TOKEN")
text, actions["tool"] = installation.add_meta_tool_config(
    text, "acme_widgets.tools.WidgetTools"
)

if any(action is installation.TargetAction.ADDED for action in actions.values()):
    path.write_text(text, encoding="utf-8")
```

Nothing is written unless at least one edit changed something, and re-running
the installer is a no-op.

## Add an entry to a section with no named helper

The named helpers are thin wrappers over two primitives, which you can call
directly for a section they do not cover. Supply the fully rendered, already
indented block and a `probe` regex that recognizes an equivalent entry — the
probe is what makes the edit idempotent, and it is searched only *within* the
target section, skipping comments:

```python
text, action = installation.add_list_entry(
    text,
    section="my_section",
    block=['  - "value"\n'],
    probe=installation.BULLET_VALUE_RE("value"),
)
```

For a nested list, `add_nested_list_entry` takes the `parent` and `section`
keys and a bare `item`:

```python
text, action = installation.add_nested_list_entry(
    text,
    parent="meta",
    section="tool_configs",
    item='- "acme_widgets.tools.WidgetTools"',
    probe=installation.LITERAL_RE("acme_widgets.tools.WidgetTools"),
)
```

The matcher factories — `BULLET_VALUE_RE`, `FIELD_VALUE_RE`, `LITERAL_RE` —
build the probes the named helpers use, and handle the optional quoting that
shows up in hand-edited files.

!!! warning "These primitives assume a collection section"
    `add_list_entry` creates the section when it is absent, which is right for
    a *collection* (default empty) and wrong for a *discovery* list or a
    *whitelist*. Check the [section catalog](sections.md) before reaching for
    it; for `room_paths` in particular, use
    [`rooms.install_room`](rooms.md), which knows the default-covering rules.

## Resolve a stack with your own markers

`resolve_stack` is the generic form of the stack-root check, for consumers that
need a stricter set of markers than the two every generated stack has. You
supply the marker files and the exception to raise, so your project keeps its
own error type and wording:

```python
from soliplex_plumber import installation, sections


class NotAStack(Exception):
    pass


MARKERS = (*sections.STACK_MARKERS, "backend/environment/haiku.rag.yaml")

stack_root = installation.resolve_stack(
    ".",
    MARKERS,
    lambda stack, marker: NotAStack(f"{stack} is not a stack: missing {marker}"),
)
```

Every marker must be a **file**; the first missing one raises. The returned
path is resolved (absolute, symlinks followed).
