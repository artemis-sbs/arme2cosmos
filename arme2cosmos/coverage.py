"""Coverage model: how each 2.8 XML command/condition maps to Cosmos MAST.

This is the read-only knowledge base behind ``report``. It mirrors the mapping table
in ``A2X_MIGRATION_PLAN.md``. Status meanings:

  full     -- mechanical, high-confidence translation (no human judgement needed)
  partial  -- translatable but emits a ``# TODO`` (closest-fit AI/behaviour/property)
  manual   -- needs a human or a chosen *new path* (comms buttons, Game Master, tags)
  ignore   -- no-op / handled implicitly (e.g. bare flag variables)

Keys are ``XmlNode.kind_key()`` values, so ``create`` is split by its ``type``.
Unknown tags are reported as ``unknown`` so the corpus can surface anything missed.
"""

from __future__ import annotations

from dataclasses import dataclass

FULL = "full"
PARTIAL = "partial"
MANUAL = "manual"
IGNORE = "ignore"
UNKNOWN = "unknown"

STATUS_ORDER = [FULL, PARTIAL, MANUAL, IGNORE, UNKNOWN]


@dataclass(frozen=True)
class Coverage:
    status: str
    note: str = ""


# --- create (split by type) -------------------------------------------------
_CREATE = {
    "create:player": Coverage(FULL, "player_spawn via //shared/signal/create_player_ships"),
    "create:enemy": Coverage(FULL, "a2x.create_enemy -> npc_spawn behav_npcship"),
    "create:neutral": Coverage(FULL, "a2x.create_neutral -> npc_spawn"),
    "create:station": Coverage(FULL, "npc_spawn 'side, station' behav_station"),
    "create:nebulas": Coverage(FULL, "a2x.create_nebulas"),
    "create:asteroids": Coverage(FULL, "a2x.create_asteroids"),
    "create:mines": Coverage(FULL, "a2x.create_mines (new terrain helper)"),
    "create:blackHole": Coverage(FULL, "prefab_black_hole"),
    "create:Anomaly": Coverage(FULL, "pickup_spawn (pickupType->upgrade key)"),
    "create:anomaly": Coverage(FULL, "pickup_spawn (pickupType->upgrade key)"),
    "create:monster": Coverage(PARTIAL, "best-fit art + PLACEHOLDER; charbdis/wreck real, 1-7 placeholder"),
    "create:whale": Coverage(PARTIAL, "placeholder creature art + creature_ role"),
    "create:genericMesh": Coverage(PARTIAL, "nearest art; raw .dxs mesh has no Cosmos equivalent"),
    "create": Coverage(PARTIAL, "create with no/unknown type"),
}

# --- other commands ---------------------------------------------------------
_COMMANDS = {
    "destroy": Coverage(FULL, ".delete_object()"),
    "destroy_near": Coverage(FULL, "query + loop delete"),
    "set_variable": Coverage(FULL, "x = ... / shared x = ..."),
    "set_timer": Coverage(FULL, "set_timer(0, name, seconds=...)"),
    "set_difficulty_level": Coverage(FULL, "DIFFICULTY assignment"),
    "set_skybox_index": Coverage(FULL, "@media/skybox (index->name table)"),
    "log": Coverage(FULL, "log(text)"),
    "end_mission": Coverage(FULL, "signal_emit('show_game_results')"),
    "big_message": Coverage(FULL, "story dialog / info panel"),
    "play_sound_now": Coverage(FULL, "sbs.play_audio_file"),
    "set_player_grid_damage": Coverage(FULL, "grid_damage_system(id, sbs.SHPSYS.*)"),
    "set_object_property": Coverage(FULL, "obj.data_set.set (property-name table)"),
    "addto_object_property": Coverage(FULL, "data_set read+add"),
    "get_object_property": Coverage(FULL, "get_data_set_value -> variable"),
    "copy_object_property": Coverage(FULL, "data_set read then set"),
    "set_side_value": Coverage(FULL, "role/side reassignment"),
    "set_relative_position": Coverage(PARTIAL, "relative placement w/ heading; verify frame"),
    "set_to_gm_position": Coverage(PARTIAL, "//point route + source_point"),
    "direct": Coverage(PARTIAL, "a2x.direct -> target_pos / target"),
    "add_ai": Coverage(PARTIAL, "brain_add closest LM brain + TODO"),
    "clear_ai": Coverage(PARTIAL, "brain reset"),
    "set_special": Coverage(PARTIAL, "elite abilities -> closest Cosmos modifiers"),
    "set_ship_text": Coverage(PARTIAL, "name/desc/scan_desc/hail -> data_set + science"),
    "set_fleet_property": Coverage(PARTIAL, "fleet spacing/radius -> fleet config"),
    "warning_popup_message": Coverage(PARTIAL, "popup / info panel to consoles"),
    "incoming_comms_text": Coverage(PARTIAL, "comms_receive / info panel"),
    "incoming_message": Coverage(PARTIAL, "comms button + play_audio_file"),
    "set_damcon_members": Coverage(PARTIAL, "damcon team size (if supported)"),
    "set_skybox": Coverage(PARTIAL, "alias"),
    # interaction-heavy -> new paths / manual (see plan 4.1)
    "set_comms_button": Coverage(MANUAL, "fold into //comms route + button (pair by text)"),
    "clear_comms_button": Coverage(MANUAL, "route/button removal"),
    "set_gm_button": Coverage(MANUAL, "GM console gui_button or LM gamemaster menu"),
    "clear_gm_button": Coverage(MANUAL, "GM button removal"),
    "start_getting_keypresses_from": Coverage(MANUAL, "console key capture (GM screen)"),
    "end_getting_keypresses_from": Coverage(MANUAL, "console key capture (GM screen)"),
    "set_monster_tag_data": Coverage(MANUAL, "monster tag metadata"),
    "set_named_object_tag_state": Coverage(MANUAL, "object tag state"),
    "set_player_carried_type": Coverage(MANUAL, "carried single-seat config"),
    "set_player_station_carried": Coverage(MANUAL, "station-stored fighters"),
    "clear_player_station_carried": Coverage(MANUAL, "station-stored fighters"),
    "spawn_external_program": Coverage(FULL, "a2x_spawn_external_program (subprocess; update the path)"),
    "gm_instructions": Coverage(MANUAL, "GM briefing text; surface in GM console or notes"),
}

# --- conditions -------------------------------------------------------------
_CONDITIONS = {
    "if_timer_finished": Coverage(FULL, "is_timer_finished(0, name)"),
    "if_exists": Coverage(FULL, "object_exists(id)"),
    "if_not_exists": Coverage(FULL, "not object_exists(id)"),
    "if_variable": Coverage(FULL, "plain python if"),
    "if_difficulty": Coverage(FULL, "plain python if"),
    "if_distance": Coverage(FULL, "await distance_less/greater / sbs.distance_id"),
    "if_inside_box": Coverage(FULL, "bounds check (corners via from2x_coord)"),
    "if_outside_box": Coverage(FULL, "bounds check"),
    "if_inside_sphere": Coverage(FULL, "distance_point_less"),
    "if_outside_sphere": Coverage(FULL, "distance_point_greater"),
    "if_object_property": Coverage(FULL, "get_data_set_value compare"),
    "if_docked": Coverage(FULL, "dock state check"),
    "if_fleet_count": Coverage(PARTIAL, "role-set count; surrender handling TODO"),
    "if_scan_level": Coverage(PARTIAL, "science scan level (side-based)"),
    "if_in_nebula": Coverage(PARTIAL, "nebula membership test"),
    "if_player_is_targeting": Coverage(PARTIAL, "weapons lock test"),
    "if_damcon_members": Coverage(PARTIAL, "damcon team count (if supported)"),
    "if_gm_button": Coverage(MANUAL, "GM console button handler"),
    "if_gm_key": Coverage(MANUAL, "GM key handler"),
    "if_client_key": Coverage(MANUAL, "console key handler"),
    "if_comms_button": Coverage(MANUAL, "fold into //comms route (pair by text)"),
    "if_monster_tag_matches": Coverage(MANUAL, "monster tag match"),
    "if_object_tag_matches": Coverage(MANUAL, "object tag match"),
}

_TABLE: dict[str, Coverage] = {**_CREATE, **_COMMANDS, **_CONDITIONS}


def classify(kind_key: str) -> Coverage:
    """Return the :class:`Coverage` for a node ``kind_key`` (unknown -> UNKNOWN)."""
    if kind_key in _TABLE:
        return _TABLE[kind_key]
    # ``create`` with an unlisted type still counts as a create attempt.
    if kind_key.startswith("create:"):
        return Coverage(PARTIAL, "create with unmapped type")
    return Coverage(UNKNOWN, "no mapping yet")


def table_size() -> int:
    return len(_TABLE)
