"""Unit tests for the ``soliplex_plumber.sections`` catalog (offline).

The catalog is declarative data mirroring ``soliplex.config.installation``;
these tests pin the facts the editors rely on so a drift from the backend
defaults is caught here.
"""

from __future__ import annotations

from soliplex_plumber import sections


def test_room_paths_is_a_discovery_section():
    section = sections.ROOM_PATHS

    assert section.family is sections.Family.DISCOVERY
    assert section.discovery_default == "./rooms"


def test_skill_configs_is_a_per_kind_whitelist():
    section = sections.SKILL_CONFIGS

    assert section.family is sections.Family.WHITELIST
    assert section.kind_field == "kind"


def test_collection_sections():
    families = {
        sections.ENVIRONMENT.family,
        sections.SECRETS.family,
        sections.META_TOOL_CONFIGS.family,
    }

    assert families == {sections.Family.COLLECTION}


def test_meta_tool_configs_is_nested_under_meta():
    assert sections.META_TOOL_CONFIGS.parent == "meta"
    assert sections.META_TOOL_CONFIGS.key == "tool_configs"


def test_stack_structure_constants():
    assert sections.COMPOSE_FILE == "docker-compose.yml"
    assert (
        str(sections.INSTALLATION_FILE)
        == "backend/environment/installation.yaml"
    )
    assert str(sections.ROOMS_DIR) == "backend/environment/rooms"
    assert sections.STACK_MARKERS == (
        "docker-compose.yml",
        "backend/environment/installation.yaml",
    )
