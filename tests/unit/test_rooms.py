"""Unit tests for the ``soliplex_plumber.rooms`` install core (offline).

Hermetic: everything is routed through ``tmp_path`` -- pure filesystem, no
Docker/network. AAA layout, single act per test.
"""

from __future__ import annotations

import pytest

from soliplex_plumber import rooms


def _just_id_yaml(id_):
    return f'id: "{id_}"'


def _just_name_yaml(name):
    return f'name: "{name}"'


X_ID_YAML = _just_id_yaml("x")
DEMO_NAME_YAML = _just_name_yaml("demo")
STALE_ID_YAML = _just_id_yaml("stale")
FRESH_ID_YAML = _just_id_yaml("fresh")

# A stack whose room_paths enumerates a single room (no './rooms' container).
_INSTALLATION_YAML = """\
name: "demo"

# rooms loaded by this install
room_paths:
  - "./rooms/chat"

secrets:
  - foo
"""

# Path list contains only explicit valueless entry (YAML -> [None])
ROOM_PATHS_DISABLED_YAML = """\
room_paths:
  -
"""

ROOM_PATHS_EXPLICIT_DEFAULT = """\
room_paths:
  - "./rooms"
"""


def _make_stack(
    tmp_path, *, compose=True, installation=True, inst_text=_INSTALLATION_YAML
):
    """A stack directory with the bits ``resolve_project`` checks for."""
    project = tmp_path / "stack"
    (project / "backend" / "environment").mkdir(parents=True, exist_ok=True)

    if compose:
        _write_text(project / "docker-compose.yml", "services: {}")

    if installation:
        _write_text(
            project / "backend" / "environment" / "installation.yaml",
            inst_text.rstrip(),
        )

    return project


def _env(project):
    return project / "backend" / "environment"


def _installation(project):
    return _env(project) / "installation.yaml"


def _room_dir(project, room_id="handbook", parent="./rooms"):
    return _env(project) / parent / room_id


def _write_text(path, content):
    path.write_text(f"{content}\n")


def _read_text(path):
    return path.read_text().rstrip()


def _src_room(tmp_path, *, id="src", prompt="Hi."):
    """A source room template dir (room_config.yaml + prompt.txt) to copy."""
    src = tmp_path / "template"
    src.mkdir()
    _write_text(src / "room_config.yaml", _just_id_yaml(id))
    _write_text(src / "prompt.txt", f"{prompt}")
    return src


# --------------------------------------------------------------------------
# validate_room_id
# --------------------------------------------------------------------------
@pytest.mark.parametrize("room_id", ["chat", "a", "a.b_c-1", "Z9"])
def test_validate_room_id_accepts(room_id):
    rooms.validate_room_id(room_id)


@pytest.mark.parametrize("room_id", ["", ".hidden", "a/b", "a b", "../x"])
def test_validate_room_id_rejects(room_id):
    with pytest.raises(rooms.BadRoomId):
        rooms.validate_room_id(room_id)


# --------------------------------------------------------------------------
# resolve_project / resolve_package_name
# --------------------------------------------------------------------------
def test_resolve_project_ok(tmp_path):
    project = _make_stack(tmp_path)

    result = rooms.resolve_project(str(project))

    assert result == project.resolve()


def test_resolve_project_compose_not_found(tmp_path):
    project = _make_stack(tmp_path, compose=False)

    with pytest.raises(rooms.ComposeNotFound):
        rooms.resolve_project(str(project))


def test_resolve_project_not_a_stack(tmp_path):
    project = _make_stack(tmp_path, installation=False)

    with pytest.raises(rooms.NotAStack):
        rooms.resolve_project(str(project))


def test_resolve_package_name_override(tmp_path):
    project = _make_stack(tmp_path)

    result = rooms.resolve_package_name(project, "acme_pkg")

    assert result == "acme_pkg"


def test_resolve_package_name_from_src(tmp_path):
    project = _make_stack(tmp_path)
    (project / "src" / "mypkg").mkdir(parents=True)
    _write_text(project / "src" / "mypkg" / "tools.py", "def greeting(): ...")
    (project / "src" / "notpkg").mkdir()  # excluded: no tools.py
    (project / "src" / "stray.txt").write_text("x")  # excluded: not a dir

    result = rooms.resolve_package_name(project, None)

    assert result == "mypkg"


def test_resolve_package_name_src_without_package(tmp_path):
    project = _make_stack(tmp_path)
    (project / "src").mkdir()

    result = rooms.resolve_package_name(project, None)

    assert result == rooms.DEFAULT_PACKAGE_NAME


def test_resolve_package_name_no_src(tmp_path):
    project = _make_stack(tmp_path)

    result = rooms.resolve_package_name(project, None)

    assert result == rooms.DEFAULT_PACKAGE_NAME


# --------------------------------------------------------------------------
# room_parent_candidates
# --------------------------------------------------------------------------
def test_room_parent_candidates_absent_defaults_to_rooms(tmp_path):
    project = _make_stack(tmp_path, inst_text=DEMO_NAME_YAML)

    result = rooms.room_parent_candidates(project)

    assert result == ["./rooms"]


def test_room_parent_candidates_returns_only_containers(tmp_path):
    inst = """\
room_paths:
  # pick a parent
  - "./custom"
  - "./rooms/chat"
"""
    project = _make_stack(tmp_path, inst_text=inst)
    chat = _env(project) / "rooms" / "chat"
    chat.mkdir(parents=True)
    _write_text(chat / "room_config.yaml", "id: chat")  # a single room

    result = rooms.room_parent_candidates(project)

    assert result == ["./custom"]  # the single-room entry is excluded


def test_room_parent_candidates_empty_when_rooms_disabled(tmp_path):
    project = _make_stack(tmp_path, inst_text=ROOM_PATHS_DISABLED_YAML)

    result = rooms.room_parent_candidates(project)

    assert result == []


# --------------------------------------------------------------------------
# install_room -- room_paths decision table
# --------------------------------------------------------------------------
def test_install_room_added_splices_individual_entry(tmp_path):
    project = _make_stack(tmp_path)  # lists './rooms/chat', no container
    handbook_id_yaml = _just_id_yaml("handbook")

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=handbook_id_yaml,
        parent_path="./rooms",
    )

    assert installed.path_action == rooms.ADDED
    assert _read_text(installed.config_path) == handbook_id_yaml
    lines = _installation(project).read_text().splitlines()
    assert '  - "./rooms/handbook"' in lines
    assert '  - "./rooms/chat"' in lines  # the enumerated room is untouched


def test_install_room_into_explicitly_disabled_rooms(tmp_path):
    project = _make_stack(tmp_path, inst_text=ROOM_PATHS_DISABLED_YAML)

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./rooms",
    )

    assert installed.path_action == rooms.ADDED
    assert installed.config_path.read_text() == X_ID_YAML
    assert (
        _installation(project).read_text()
        == """\
room_paths:
  - "./rooms/handbook"
  -
"""
    )


def test_install_room_unchanged_when_entry_listed(tmp_path):
    inst = _INSTALLATION_YAML.replace('"./rooms/chat"', '"./rooms/handbook"')
    project = _make_stack(tmp_path, inst_text=inst)
    before = _installation(project).read_text()

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./rooms",
    )

    assert installed.path_action == rooms.UNCHANGED
    assert installed.config_path.is_file()
    assert _installation(project).read_text() == before


def test_install_room_covered_by_container(tmp_path):
    project = _make_stack(tmp_path, inst_text=ROOM_PATHS_EXPLICIT_DEFAULT)
    before = _installation(project).read_text()

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./rooms",
    )

    assert installed.path_action == rooms.COVERED
    assert installed.config_path.is_file()
    assert _installation(project).read_text() == before


def test_install_room_covered_by_absent_default(tmp_path):
    project = _make_stack(tmp_path, inst_text=DEMO_NAME_YAML)
    before = _installation(project).read_text()

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./rooms",
    )

    assert installed.path_action == rooms.COVERED
    assert installed.config_path.is_file()
    assert _installation(project).read_text() == before


def test_install_room_materializes_default_for_other_parent(tmp_path):
    project = _make_stack(tmp_path, inst_text=DEMO_NAME_YAML)

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./custom",
    )

    assert installed.path_action == rooms.ADDED
    text = _installation(project).read_text()
    assert (
        """\
room_paths:
  - "./rooms"
  - "./custom/handbook"
"""
        in text
    )
    assert installed.config_path == (
        _room_dir(project, parent="./custom") / "room_config.yaml"
    )
    assert installed.config_path.read_text() == X_ID_YAML


def test_install_room_writes_prompt_file(tmp_path):
    project = _make_stack(tmp_path)
    qa_id_yaml = _just_id_yaml("qa")

    installed = rooms.install_room(
        project=project,
        room_id="qa",
        config_text=qa_id_yaml,
        prompt_text="Be helpful.",
        parent_path="./rooms",
    )

    assert _read_text(installed.config_path.parent / "prompt.txt") == (
        "Be helpful."
    )


def test_install_room_dry_run_writes_nothing(tmp_path):
    project = _make_stack(tmp_path)
    before = _installation(project).read_text()

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./rooms",
        dry_run=True,
    )

    assert installed.path_action == rooms.ADDED
    assert not _room_dir(project).exists()
    assert _installation(project).read_text() == before


def test_install_room_exists_without_force(tmp_path):
    project = _make_stack(tmp_path)
    _room_dir(project).mkdir(parents=True)

    with pytest.raises(rooms.RoomExists):
        rooms.install_room(
            project=project,
            room_id="handbook",
            config_text=X_ID_YAML,
            parent_path="./rooms",
        )


def test_install_room_force_overwrites(tmp_path):
    project = _make_stack(tmp_path)
    room = _room_dir(project)
    room.mkdir(parents=True)
    _write_text(room / "room_config.yaml", STALE_ID_YAML)

    installed = rooms.install_room(
        project=project,
        room_id="handbook",
        config_text=FRESH_ID_YAML,
        parent_path="./rooms",
        force=True,
    )

    assert _read_text(room / "room_config.yaml") == FRESH_ID_YAML
    assert installed.path_action == rooms.ADDED


def test_install_room_rejects_parent_that_is_a_room(tmp_path):
    project = _make_stack(tmp_path)
    rooms_dir = _env(project) / "rooms"
    rooms_dir.mkdir(parents=True)
    rooms_id_yaml = _just_id_yaml("rooms")
    # ./rooms is a room
    _write_text(rooms_dir / "room_config.yaml", rooms_id_yaml)

    with pytest.raises(rooms.ParentIsRoom):
        rooms.install_room(
            project=project,
            room_id="handbook",
            config_text=X_ID_YAML,
            parent_path="./rooms",
        )


# --------------------------------------------------------------------------
# install_room_from
# --------------------------------------------------------------------------
def test_room_install_is_backward_compat_alias():
    assert rooms.RoomInstall is rooms.RoomInstalled


def test_install_room_from_copies_tree(tmp_path):
    project = _make_stack(tmp_path)
    src = _src_room(tmp_path)

    installed = rooms.install_room_from(
        project=project,
        room_id="handbook",
        src_dir=src,
        parent_path="./rooms",
    )

    assert installed.path_action == rooms.ADDED
    assert _read_text(installed.config_path) == 'id: "src"'
    assert _read_text(installed.config_path.parent / "prompt.txt") == "Hi."


def test_install_room_from_force_overwrites(tmp_path):
    project = _make_stack(tmp_path)
    src = _src_room(tmp_path, id="fresh")
    room = _room_dir(project)
    room.mkdir(parents=True)
    _write_text(room / "room_config.yaml", STALE_ID_YAML)

    installed = rooms.install_room_from(
        project=project,
        room_id="handbook",
        src_dir=src,
        parent_path="./rooms",
        force=True,
    )

    assert installed.path_action == rooms.ADDED
    assert _read_text(room / "room_config.yaml") == FRESH_ID_YAML


# --------------------------------------------------------------------------
# target selection: project vs environment, and the deprecated positional form
# --------------------------------------------------------------------------
def test_install_room_targets_environment_directly(tmp_path):
    project = _make_stack(tmp_path)

    installed = rooms.install_room(
        environment=_env(project),
        room_id="handbook",
        config_text=X_ID_YAML,
        parent_path="./rooms",
    )

    assert installed.config_path == _room_dir(project) / "room_config.yaml"
    assert installed.config_path.read_text() == X_ID_YAML
    assert installed.path_action == rooms.ADDED


def test_install_room_from_targets_environment_directly(tmp_path):
    project = _make_stack(tmp_path)
    src = _src_room(tmp_path)

    installed = rooms.install_room_from(
        environment=_env(project),
        room_id="handbook",
        src_dir=src,
        parent_path="./rooms",
    )

    assert installed.config_path == _room_dir(project) / "room_config.yaml"
    assert _read_text(installed.config_path) == 'id: "src"'


def test_install_room_deprecated_positional_warns(tmp_path):
    project = _make_stack(tmp_path)

    with pytest.warns(
        DeprecationWarning,
        match=rooms.INSTALL_ROOM_POS_ARGS_DEPRECATION,
    ):
        installed = rooms.install_room(
            project,
            "handbook",
            config_text=X_ID_YAML,
            parent_path="./rooms",
        )

    assert installed.config_path == _room_dir(project) / "room_config.yaml"
    assert installed.config_path.read_text() == X_ID_YAML


def test_install_room_from_deprecated_positional_warns(tmp_path):
    project = _make_stack(tmp_path)
    src = _src_room(tmp_path)

    with pytest.warns(
        DeprecationWarning,
        match=rooms.INSTALL_ROOM_FROM_POS_ARGS_DEPRECATION,
    ):
        installed = rooms.install_room_from(
            project, "handbook", src, parent_path="./rooms"
        )

    assert _read_text(installed.config_path) == 'id: "src"'


def test_install_room_requires_a_target(tmp_path):
    with pytest.raises(TypeError):
        rooms.install_room(
            room_id="handbook", config_text=X_ID_YAML, parent_path="./rooms"
        )


def test_install_room_rejects_both_targets(tmp_path):
    project = _make_stack(tmp_path)

    with pytest.raises(TypeError):
        rooms.install_room(
            project=project,
            environment=_env(project),
            room_id="handbook",
            config_text=X_ID_YAML,
            parent_path="./rooms",
        )


def test_install_room_requires_room_id(tmp_path):
    project = _make_stack(tmp_path)

    with pytest.raises(TypeError):
        rooms.install_room(
            project=project, config_text=X_ID_YAML, parent_path="./rooms"
        )


def test_install_room_rejects_positional_with_keyword_room_id(tmp_path):
    project = _make_stack(tmp_path)

    with (
        pytest.warns(
            DeprecationWarning,
            match=rooms.INSTALL_ROOM_POS_ARGS_DEPRECATION,
        ),
        pytest.raises(TypeError),
    ):
        rooms.install_room(
            project,
            room_id="handbook",
            config_text=X_ID_YAML,
            parent_path="./rooms",
        )


def test_install_room_rejects_incomplete_positional_pair(tmp_path):
    project = _make_stack(tmp_path)

    with (
        pytest.warns(
            DeprecationWarning,
            match=rooms.INSTALL_ROOM_POS_ARGS_DEPRECATION,
        ),
        pytest.raises(TypeError),
    ):
        rooms.install_room(
            project, config_text=X_ID_YAML, parent_path="./rooms"
        )


def test_install_room_from_requires_src_dir(tmp_path):
    project = _make_stack(tmp_path)

    with pytest.raises(TypeError):
        rooms.install_room_from(
            project=project, room_id="handbook", parent_path="./rooms"
        )


def test_install_room_from_rejects_positional_and_keyword_src_dir(tmp_path):
    project = _make_stack(tmp_path)
    src = _src_room(tmp_path)

    with (
        pytest.warns(
            DeprecationWarning,
            match=rooms.INSTALL_ROOM_FROM_POS_ARGS_DEPRECATION,
        ),
        pytest.raises(TypeError),
    ):
        rooms.install_room_from(
            project, "handbook", src, src_dir=src, parent_path="./rooms"
        )


def test_install_room_from_rejects_incomplete_positional_form(tmp_path):
    project = _make_stack(tmp_path)

    with (
        pytest.warns(
            DeprecationWarning,
            match=rooms.INSTALL_ROOM_FROM_POS_ARGS_DEPRECATION,
        ),
        pytest.raises(TypeError),
    ):
        rooms.install_room_from(project, "handbook", parent_path="./rooms")
