"""Unit tests for the ``soliplex_plumber.installation`` editors (offline).

Plumber is stdlib-only (no YAML library), so these assert on *exact text* --
the inserted block appears verbatim, unrelated lines are byte-identical, and a
re-run is idempotent -- rather than on parsed structure.

Each test is laid out in three blank-line-separated phases -- setup, then the
single call under test (the "act"), then the assertions -- and performs that
act exactly once (cases that would repeat it are parametrized or split).
"""

from __future__ import annotations

import re

import pytest

from soliplex_plumber import installation

# A representative installation.yaml with the standard top-level sections plus
# a comment and an unrelated block, to prove comment/layout preservation.
_INSTALLATION_YAML = """\
id: "demo"

meta:
  # nothing registered yet

environment:
  - "OLLAMA_BASE_URL"

secrets:
  - secret_name: "URL_SAFE_TOKEN_SECRET"

skill_configs:
  - skill_name: "bare-bones"
    kind: "filesystem"
"""

X_ONLY_ID_YAML = """\
id: x
"""

# A populated nested meta.tool_configs block (for the nested-list editor).
_META_TOOL_CONFIGS_YAML = """\
meta:
  tool_configs:
    - "pkg.First"
"""

# A skill_configs whitelist carrying a comment among its items.
_SKILL_CONFIGS_COMMENTED_YAML = """\
skill_configs:
  # curated whitelist
  - skill_name: "bare-bones"
    kind: "filesystem"
"""

_TOOL_CONFIG = "pkg.Cfg"  # a tool-config class path, added under meta


def _literal_probe(value):
    """A probe matching ``value`` literally, not as a regex."""
    return re.compile(re.escape(value))


PROBE_OLLAMA_BASE_URL = _literal_probe("OLLAMA_BASE_URL")
PROBE__TOOL_CONFIG = _literal_probe(_TOOL_CONFIG)


# --------------------------------------------------------------------------
# scanning helpers
# --------------------------------------------------------------------------
@pytest.mark.parametrize("line", ['  - "x"\n', "key:\n"])
def test_is_item_true(line):
    assert installation.is_item(line)


@pytest.mark.parametrize("line", ["\n", "   \n", "  # comment\n"])
def test_is_item_false(line):
    assert not installation.is_item(line)


def test_section_span_stops_at_next_top_level_key():
    lines = _INSTALLATION_YAML.splitlines(keepends=True)

    start, end = installation.section_span(lines, "environment")

    assert lines[start] == "environment:\n"
    assert lines[end] == "secrets:\n"  # next column-0 key ends the block


def test_section_span_runs_to_eof_for_last_section():
    lines = _INSTALLATION_YAML.splitlines(keepends=True)

    start, end = installation.section_span(lines, "skill_configs")

    assert end == len(lines)


def test_section_span_absent():
    assert installation.section_span([X_ONLY_ID_YAML], "secrets") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", "secrets:\n  - x\n"),
        ("a: 1\n", "a: 1\n\nsecrets:\n  - x\n"),
        ("a: 1", "a: 1\n\nsecrets:\n  - x\n"),
        ("a: 1\n\n", "a: 1\n\nsecrets:\n  - x\n"),
    ],
)
def test_append_section_separators(text, expected):
    result = installation.append_section(text, "secrets", ["  - x\n"])

    assert result == expected


# --------------------------------------------------------------------------
# add_list_entry (collection)
# --------------------------------------------------------------------------
def test_add_list_entry_added_after_anchor():
    new, action = installation.add_list_entry(
        _INSTALLATION_YAML,
        section="environment",
        block=['  - "GITEA_HOST"\n'],
        probe=_literal_probe("GITEA_HOST"),
    )

    assert action == installation.TargetAction.ADDED
    lines = new.splitlines()
    anchor = lines.index("environment:")
    assert lines[anchor + 1] == '  - "GITEA_HOST"'
    assert '  - "OLLAMA_BASE_URL"' in new  # unrelated item preserved


def test_add_list_entry_unchanged_when_present_in_section():
    new, action = installation.add_list_entry(
        _INSTALLATION_YAML,
        section="environment",
        block=['  - "OLLAMA_BASE_URL"\n'],
        probe=PROBE_OLLAMA_BASE_URL,
    )

    assert action == installation.TargetAction.UNCHANGED
    assert new == _INSTALLATION_YAML


def test_add_list_entry_scoped_to_its_section():
    # 'OLLAMA_BASE_URL' lives under 'environment', NOT 'secrets'; adding it to
    # 'secrets' must not be fooled into UNCHANGED by the other section.
    new, action = installation.add_list_entry(
        _INSTALLATION_YAML,
        section="secrets",
        block=['  - "OLLAMA_BASE_URL"\n'],
        probe=PROBE_OLLAMA_BASE_URL,
    )

    assert action == installation.TargetAction.ADDED


def test_add_list_entry_skips_commented_match():
    text = """\
secrets:
  # - "GITEA"
"""

    new, action = installation.add_list_entry(
        text,
        section="secrets",
        block=['  - "GITEA"\n'],
        probe=_literal_probe("GITEA"),
    )

    # the comment did not count as present
    assert action == installation.TargetAction.ADDED


def test_add_list_entry_creates_absent_section():
    new, action = installation.add_list_entry(
        X_ONLY_ID_YAML,
        section="secrets",
        block=['  - "S"\n'],
        probe=_literal_probe("S"),
    )

    assert action == installation.TargetAction.ADDED
    assert (
        new
        == """\
id: x

secrets:
  - "S"
"""
    )


# --------------------------------------------------------------------------
# add_nested_list_entry
# --------------------------------------------------------------------------
def test_add_nested_appends_to_existing_child():
    new, action = installation.add_nested_list_entry(
        _META_TOOL_CONFIGS_YAML,
        parent="meta",
        section="tool_configs",
        item='- "pkg.Second"',
        probe=_literal_probe("pkg.Second"),
    )

    assert action == installation.TargetAction.ADDED
    lines = new.splitlines()
    tc = lines.index("  tool_configs:")
    assert lines[tc + 1] == '    - "pkg.Second"'
    assert lines[tc + 2] == '    - "pkg.First"'


def test_add_nested_creates_child_when_parent_present():
    new, action = installation.add_nested_list_entry(
        _INSTALLATION_YAML,
        parent="meta",
        section="tool_configs",
        item=f'- "{_TOOL_CONFIG}"',
        probe=PROBE__TOOL_CONFIG,
    )

    assert action == installation.TargetAction.ADDED
    lines = new.splitlines()
    meta = lines.index("meta:")
    assert lines[meta + 1] == "  tool_configs:"
    assert lines[meta + 2] == f'    - "{_TOOL_CONFIG}"'


def test_add_nested_creates_parent_when_absent():
    new, action = installation.add_nested_list_entry(
        X_ONLY_ID_YAML,
        parent="meta",
        section="tool_configs",
        item=f'- "{_TOOL_CONFIG}"',
        probe=PROBE__TOOL_CONFIG,
    )

    assert action == installation.TargetAction.ADDED
    assert (
        new
        == """\
id: x

meta:
  tool_configs:
    - "pkg.Cfg"
"""
    )


def test_add_nested_unchanged_when_present():
    text = """\
meta:
  tool_configs:
    - "pkg.Cfg"
"""

    new, action = installation.add_nested_list_entry(
        text,
        parent="meta",
        section="tool_configs",
        item=f'- "{_TOOL_CONFIG}"',
        probe=PROBE__TOOL_CONFIG,
    )

    assert action == installation.TargetAction.UNCHANGED
    assert new == text


# --------------------------------------------------------------------------
# named collection helpers
# --------------------------------------------------------------------------
def test_add_environment_added():
    new, action = installation.add_environment(
        _INSTALLATION_YAML, "GITEA_HOST"
    )

    assert action == installation.TargetAction.ADDED
    assert '  - "GITEA_HOST"\n' in new


def test_add_environment_unchanged():
    once, _ = installation.add_environment(_INSTALLATION_YAML, "GITEA_HOST")

    twice, action = installation.add_environment(once, "GITEA_HOST")

    assert action == installation.TargetAction.UNCHANGED
    assert twice == once


@pytest.mark.parametrize(
    "env_var_name,expected",
    [(None, "GITEA_TOKEN"), ("OTHER_VAR", "OTHER_VAR")],
)
def test_add_secret_added(env_var_name, expected):
    new, action = installation.add_secret(
        _INSTALLATION_YAML, "GITEA_TOKEN", env_var_name=env_var_name
    )

    assert action == installation.TargetAction.ADDED
    assert '  - secret_name: "GITEA_TOKEN"\n' in new
    assert "    sources:\n" in new
    assert '      - kind: "env_var"\n' in new
    assert f'        env_var_name: "{expected}"\n' in new


def test_add_secret_unchanged():
    once, _ = installation.add_secret(_INSTALLATION_YAML, "GITEA_TOKEN")

    twice, action = installation.add_secret(once, "GITEA_TOKEN")

    assert action == installation.TargetAction.UNCHANGED
    assert twice == once


def test_add_meta_tool_config_added():
    new, action = installation.add_meta_tool_config(
        _INSTALLATION_YAML, _TOOL_CONFIG
    )

    assert action == installation.TargetAction.ADDED
    assert "  tool_configs:\n" in new
    assert f'    - "{_TOOL_CONFIG}"\n' in new


def test_add_meta_tool_config_unchanged():
    once, _ = installation.add_meta_tool_config(
        _INSTALLATION_YAML, _TOOL_CONFIG
    )

    twice, action = installation.add_meta_tool_config(once, _TOOL_CONFIG)

    assert action == installation.TargetAction.UNCHANGED
    assert twice == once


# --------------------------------------------------------------------------
# add_skill_config (per-kind whitelist)
# --------------------------------------------------------------------------
def test_add_skill_config_unchanged_when_present():
    new, action = installation.add_skill_config(
        _INSTALLATION_YAML, "bare-bones", kind="filesystem"
    )

    assert action == installation.TargetAction.UNCHANGED
    assert new == _INSTALLATION_YAML


def test_add_skill_config_covered_when_kind_permissive():
    # An absent section is permissive for every kind -> the skill is already
    # enabled by discovery; adding it would flip the kind restrictive.
    new, action = installation.add_skill_config(
        X_ONLY_ID_YAML, "soliplex-docs", kind="filesystem"
    )

    assert action == installation.TargetAction.COVERED
    assert new == X_ONLY_ID_YAML


def test_add_skill_config_covered_when_other_kind_active():
    # 'bare-bones' is a filesystem entry; the entrypoint kind has none, so an
    # entrypoint skill is still permissively covered.
    new, action = installation.add_skill_config(
        _INSTALLATION_YAML, "some-ep-skill", kind="entrypoint"
    )

    assert action == installation.TargetAction.COVERED


def test_add_skill_config_skips_comments_in_block():
    new, action = installation.add_skill_config(
        _SKILL_CONFIGS_COMMENTED_YAML, "bare-bones", kind="filesystem"
    )

    assert action == installation.TargetAction.UNCHANGED
    assert new == _SKILL_CONFIGS_COMMENTED_YAML


def test_add_skill_config_aborts_on_active_whitelist():
    with pytest.raises(installation.WhitelistActive) as exc:
        installation.add_skill_config(
            _INSTALLATION_YAML, "soliplex-docs", kind="filesystem"
        )

    assert exc.value.kind == "filesystem"
    assert exc.value.entries == ["bare-bones"]


def test_add_skill_config_appends_with_confirm():
    new, action = installation.add_skill_config(
        _INSTALLATION_YAML, "soliplex-docs", kind="filesystem", confirm=True
    )

    assert action == installation.TargetAction.ADDED
    assert '  - skill_name: "soliplex-docs"\n' in new
    assert '  - skill_name: "bare-bones"\n' in new  # existing entry preserved


# --------------------------------------------------------------------------
# resolve_stack
# --------------------------------------------------------------------------
class _StubError(Exception):
    """A caller-supplied error factory for resolve_stack."""

    def __init__(self, stack, marker):
        super().__init__(f"missing {marker} under {stack}")


def _make_stack(tmp_path, *, markers=installation.sections.STACK_MARKERS):
    project = tmp_path / "stack"
    for marker in markers:
        target = project / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
    return project


def test_resolve_stack_ok(tmp_path):
    project = _make_stack(tmp_path)

    result = installation.resolve_stack(
        str(project), installation.sections.STACK_MARKERS, _StubError
    )

    assert result == project.resolve()


def test_resolve_stack_missing_marker(tmp_path):
    project = _make_stack(tmp_path)
    (project / installation.sections.COMPOSE_FILE).unlink()

    with pytest.raises(_StubError, match=installation.sections.COMPOSE_FILE):
        installation.resolve_stack(
            str(project), installation.sections.STACK_MARKERS, _StubError
        )
