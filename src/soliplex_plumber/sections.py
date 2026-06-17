"""What plumber knows about a Soliplex ``installation.yaml``'s sections.

A declarative catalog (no logic): each :class:`Section` records the *default*
the backend applies when the section is absent, which is what the editors in
:mod:`soliplex_plumber.installation` and :mod:`soliplex_plumber.rooms` consult
to decide an absent section's behavior. It mirrors
``soliplex.config.installation`` (the source of truth) -- keep it in sync:

- discovery lists default to a directory (``room_paths`` -> ``["./rooms"]``,
  ``filesystem_skills_paths`` -> ``["./skills"]``); an entry beneath the
  default dir is therefore already *covered* when the section is absent;
- plain collections default to empty (``secrets`` -> ``[]``, ``environment`` ->
  ``{}``, ``meta.tool_configs`` -> ``[]``); an absent section must be *created*
  to add an entry;
- ``skill_configs`` is a per-``kind`` whitelist: empty/absent for a kind is
  *permissive* (every discovered skill of that kind is enabled), so adding the
  first entry of a kind would flip it restrictive (``resolve_skill_configs``).

Pure data -- stdlib only.
"""

from __future__ import annotations

import dataclasses
import enum
import pathlib


class Family(enum.Enum):
    """How a section behaves when an entry is added (see module docstring)."""

    DISCOVERY = "discovery"
    COLLECTION = "collection"
    WHITELIST = "whitelist"


@dataclasses.dataclass(frozen=True)
class Section:
    """Declarative facts about one editable ``installation.yaml`` section."""

    key: str
    family: Family
    parent: str | None = None  # nested key, e.g. ``meta`` for ``tool_configs``
    discovery_default: str | None = None  # DISCOVERY: the default dir
    kind_field: str | None = (
        None  # WHITELIST: the per-entry kind discriminator
    )


ROOM_PATHS = Section(
    "room_paths", Family.DISCOVERY, discovery_default="./rooms"
)
ENVIRONMENT = Section("environment", Family.COLLECTION)
SECRETS = Section("secrets", Family.COLLECTION)
META_TOOL_CONFIGS = Section("tool_configs", Family.COLLECTION, parent="meta")
SKILL_CONFIGS = Section("skill_configs", Family.WHITELIST, kind_field="kind")


# Stack-structure constants: the files/dirs that mark a generated stack and
# anchor the paths the editors resolve against. (Re-exported by
# ``soliplex_plumber.rooms`` under their historical names.)
COMPOSE_FILE = "docker-compose.yml"
ENVIRONMENT_DIR = pathlib.PurePosixPath("backend", "environment")
INSTALLATION_FILE = ENVIRONMENT_DIR / "installation.yaml"
ROOMS_DIR = ENVIRONMENT_DIR / ROOM_PATHS.discovery_default

# The two markers every generated stack has; consumers needing a stricter set
# (e.g. the concierge installer) extend this tuple.
STACK_MARKERS = (COMPOSE_FILE, str(INSTALLATION_FILE))
