"""Generic, comment-preserving edits to a stack's ``installation.yaml``.

Each editor is a pure ``text -> (new_text, action)`` function that splices a
list item into a section, line-based, so comments and unrelated layout survive
verbatim.

- Scanning is **section-scoped** (only the target section's block is
  searched, not the whole file)

- Scanning is **comment-skipping**, fixing two classes of false positive
  in the older whole-file probes.

The edtiros are **default-aware** (see :mod:`soliplex_plumber.sections`):

- an absent *collection* section is created

- a *whitelist* (``skill_configs``) that is permissive for a kind is left
  alone (``COVERED``) rather than flipped restrictive.

The named helpers own the *shape* of each section; the caller
supplies the values.

Pure text work -- stdlib only.
"""

from __future__ import annotations

import enum
import pathlib
import re

from soliplex_plumber import sections

# The line "grammar" the scanners tokenize against -- fixed-token patterns
# (ALL_CAPS constants) plus parameterized matchers (ALL_CAPS factories taking
# the value to interpolate). The names double as chunking cues during review.

# A column-0 key (no leading space, not a comment) -- ends a section's block.
TOP_KEY_RE = re.compile(r"^[^\s#]")

# A 'skill_name: <value>' field, capturing its (optionally quoted) value.
SKILL_NAME_RE = re.compile(r'skill_name:\s*["\']?([^"\'\s]+)')

# A 'kind: <value>' field, capturing its (optionally quoted) value.
KIND_RE = re.compile(r'kind:\s*["\']?([^"\'\s]+)')


def SECTION_ANCHOR_RE(section: str) -> re.Pattern:
    """A top-level ``{section}:`` anchor line."""
    return re.compile(rf"^{re.escape(section)}:\s*$")


def NESTED_KEY_RE(key: str) -> re.Pattern:
    """An indented ``{key}:`` line, capturing its leading indent."""
    return re.compile(rf"^(\s+){re.escape(key)}:\s*$")


def BULLET_VALUE_RE(value: str) -> re.Pattern:
    """A list bullet whose whole (optionally quoted) scalar is ``value``."""
    return re.compile(r'^\s*-\s*["\']?' + re.escape(value) + r'["\']?\s*$')


def FIELD_VALUE_RE(field: str, value: str) -> re.Pattern:
    """A ``{field}:`` mapping entry set to ``value`` (optionally quoted)."""
    return re.compile(rf'{re.escape(field)}:\s*["\']?' + re.escape(value))


def LITERAL_RE(value: str) -> re.Pattern:
    """The literal text ``value`` occurring anywhere on a line."""
    return re.compile(re.escape(value))


class TargetAction(enum.StrEnum):
    ADDED = "added"
    UNCHANGED = "unchanged"

    # The target is already satisfied without an edit -- a discovery default
    # or parent covers it, or a whitelist is permissive for its kind.
    COVERED = "covered"


class WhitelistActive(Exception):
    """A ``skill_configs`` kind already has an explicit whitelist.

    Adding our skill is safe (append-only) but narrows operator-curated config,
    so plumber refuses unless the caller passes ``confirm=True``. Carries the
    ``kind`` and the skills currently whitelisted for it, for a CLI to render.
    """

    def __init__(self, kind: str, entries: list[str]):
        self.kind = kind
        self.entries = list(entries)
        listed = ", ".join(self.entries) or "(none)"
        super().__init__(
            f"skill_configs already whitelists {kind!r} skills ({listed}); "
            "pass confirm=True to add to that whitelist"
        )


# --- low-level, comment-aware section scanning (shared with rooms) ---------


def is_item(line: str) -> bool:
    """True for a content line within a block (not blank, not a comment)."""
    stripped = line.strip()
    return stripped and not stripped.startswith("#")


def section_span(lines: list[str], section: str) -> tuple[int, int] | None:
    """``(anchor_idx, end_idx)`` for a top-level ``section:`` block.

    ``end_idx`` is exclusive -- the next column-0 key or end of file. Returns
    ``None`` when there is no top-level ``section:`` line.
    """
    anchor = SECTION_ANCHOR_RE(section)
    start = end = None

    for i_line, line in enumerate(lines):
        if start is None:
            if anchor.match(line):
                start = i_line
        else:
            if TOP_KEY_RE.match(line):
                end = i_line
                break

    if start is None:
        return None

    if end is None:
        end = len(lines)

    return start, end


def append_section(text: str, section: str, block: list[str]) -> str:
    """Append a fresh top-level ``section:`` + ``block`` at end of file.

    Ensures a single blank-line separator before the new section (unless the
    text is empty), so a created section never abuts the previous one.
    """
    prefix = text.rstrip()
    section_block = f"{section}:\n" + "".join(block)
    return f"{prefix}\n\n" + section_block if prefix else section_block


# --- generic primitives ----------------------------------------------------


def add_list_entry(
    text: str,
    *,
    section: str,
    block: list[str],
    probe: re.Pattern,
) -> tuple[str, TargetAction]:
    """Add ``block`` under a top-level *collection* ``section:``.

    ``probe`` matches an item *within the section* (comments skipped) ⇒
    ``UNCHANGED``. Section present ⇒ splice ``block`` after the anchor ⇒
    ``ADDED``. Section absent ⇒ create it (its empty default) with ``block`` ⇒
    ``ADDED``. ``block`` is fully-rendered, already-indented, newline-ended
    lines.
    """
    lines = text.splitlines(keepends=True)
    span = section_span(lines, section)

    if span is None:
        return append_section(text, section, block), TargetAction.ADDED

    start, end = span

    if any(
        probe.search(line) for line in lines[start + 1 : end] if is_item(line)
    ):
        return text, TargetAction.UNCHANGED

    lines[start + 1 : start + 1] = block

    return "".join(lines), TargetAction.ADDED


def add_nested_list_entry(
    text: str,
    *,
    parent: str,
    section: str,
    item: str,
    probe: re.Pattern,
) -> tuple[str, TargetAction]:
    """Add ``item`` under ``{parent}:`` then ``{section}:`` (a nested list).

    Appends to an existing ``{section}:`` within the ``{parent}:`` block, or
    creates that child block right after ``{parent}:``; creates ``{parent}:``
    itself when absent. ``item`` is the bare entry (e.g. ``- "x"``).
    """
    lines = text.splitlines(keepends=True)
    pspan = section_span(lines, parent)

    if pspan is None:
        block = [f"  {section}:\n", f"    {item}\n"]
        return append_section(text, parent, block), TargetAction.ADDED

    pstart, pend = pspan
    section_lines = lines[pstart + 1 : pend]

    if any(probe.search(line) for line in section_lines if is_item(line)):
        return text, TargetAction.UNCHANGED

    before_lines = lines[: pstart + 1]
    after_lines = lines[pend:]
    child_anchor = NESTED_KEY_RE(section)

    for i, line in enumerate(section_lines):
        match = child_anchor.match(line)
        if match:
            section_lines[i + 1 : i + 1] = [f"{match.group(1)}  {item}\n"]
            break
    else:
        section_lines[0:0] = [f"  {section}:\n", f"    {item}\n"]

    return "".join(
        before_lines + section_lines + after_lines
    ), TargetAction.ADDED


# --- named section helpers (own the YAML shape; values are the caller's) ---


def add_environment(text: str, var_name: str) -> tuple[str, str]:
    """Add ``var_name`` to the top-level ``environment:`` list."""
    return add_list_entry(
        text,
        section=sections.ENVIRONMENT.key,
        block=[f'  - "{var_name}"\n'],
        probe=BULLET_VALUE_RE(var_name),
    )


def add_secret(
    text: str, secret_name: str, *, env_var_name: str | None = None
) -> tuple[str, str]:
    """Add an ``env_var`` secret to ``secrets:`` (env var defaults to name)."""
    env_var_name = env_var_name or secret_name
    block = [
        f'  - secret_name: "{secret_name}"\n',
        "    sources:\n",
        '      - kind: "env_var"\n',
        f'        env_var_name: "{env_var_name}"\n',
    ]
    return add_list_entry(
        text,
        section=sections.SECRETS.key,
        block=block,
        probe=FIELD_VALUE_RE("secret_name", secret_name),
    )


def add_meta_tool_config(text: str, class_path: str) -> tuple[str, str]:
    """Register ``class_path`` under the nested ``meta.tool_configs:`` list."""
    return add_nested_list_entry(
        text,
        parent=sections.META_TOOL_CONFIGS.parent,
        section=sections.META_TOOL_CONFIGS.key,
        item=f'- "{class_path}"',
        probe=LITERAL_RE(class_path),
    )


def _skill_entries(
    lines: list[str], lo: int, hi: int
) -> list[tuple[str, str | None]]:
    """Parse ``(skill_name, kind)`` pairs from a ``skill_configs`` block."""
    entries: list[list[str | None]] = []

    for line in lines[lo:hi]:
        if is_item(line):
            name = SKILL_NAME_RE.search(line)
            if name:
                entries.append([name.group(1), None])

            kind = KIND_RE.search(line)
            if kind and entries:
                entries[-1][1] = kind.group(1)

    return [(name, kind) for name, kind in entries]


def add_skill_config(
    text: str,
    skill_name: str,
    *,
    kind: str = "filesystem",
    confirm: bool = False,
) -> tuple[str, TargetAction]:
    """Whitelist ``skill_name`` (of ``kind``) in ``skill_configs:``.

    ``skill_configs`` is a per-kind whitelist that is *permissive* when a kind
    has no entries (every discovered skill of that kind is enabled). So:

    - the exact ``skill_name`` is already listed ⇒ ``UNCHANGED``;

    - the kind has no entries (incl. an absent section) ⇒ ``COVERED`` -- the
      skill is already enabled, and adding it would flip the kind restrictive
      and disable the stack's other skills of that kind;

    - the kind has an explicit whitelist and our skill is missing ⇒ raise
      :class:`WhitelistActive` (unless ``confirm``), else append ⇒ ``ADDED``.
    """
    lines = text.splitlines(keepends=True)
    span = section_span(lines, sections.SKILL_CONFIGS.key)
    entries = (
        [] if span is None else _skill_entries(lines, span[0] + 1, span[1])
    )
    if any(name == skill_name for name, _ in entries):
        return text, TargetAction.UNCHANGED

    same_kind = [name for name, entry_kind in entries if entry_kind == kind]

    if not same_kind:
        return text, TargetAction.COVERED

    if not confirm:
        raise WhitelistActive(kind, same_kind)

    block = [
        f'  - skill_name: "{skill_name}"\n',
        f'    kind: "{kind}"\n',
    ]
    start = span[0]
    lines[start + 1 : start + 1] = block
    return "".join(lines), TargetAction.ADDED


# --- stack resolution ------------------------------------------------------


def resolve_stack(stack_dir, markers, error):
    """Resolve a stack root that must contain every marker in ``markers``.

    ``error(stack, marker)`` builds the exception raised for the first missing
    marker, so callers keep their own error type and wording. Returns the
    resolved stack ``Path``.
    """
    stack = pathlib.Path(stack_dir).resolve()

    for marker in markers:
        if not (stack / marker).is_file():
            raise error(stack, marker)

    return stack
