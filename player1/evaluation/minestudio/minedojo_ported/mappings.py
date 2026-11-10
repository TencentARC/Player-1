"""Versioned MineDojo 1.11.2 to MineStudio 1.16.5 identifier mappings.

The public MineDojo programmatic suite predates Minecraft's flattened item
registry.  A bare string replacement is therefore insufficient: values such
as ``log`` and ``fish`` were item families whose concrete member was encoded
by metadata.  This module keeps that lossy boundary explicit and returns an
auditable result for every conversion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

MAPPING_PROTOCOL = "minedojo_1_11_2_to_minestudio_1_16_5_v1"

EXACT = "exact"
RENAMED = "renamed"
VARIANT_FLATTENED = "variant_flattened"
CANONICALIZED = "canonicalized_without_source_variant"
UNSUPPORTED = "unsupported"


class UnsupportedIdentifierMapping(ValueError):
    """Raised when a 1.11 identifier cannot be made executable in 1.16.5."""


@dataclass(frozen=True)
class MappingResult:
    """One explicit cross-version identifier conversion."""

    kind: str
    source: str | int
    target: str | int | None
    status: str
    source_variant: int | None = None
    note: str | None = None

    @property
    def executable(self) -> bool:
        return self.target is not None and self.status != UNSUPPORTED

    def require_target(self) -> str | int:
        if not self.executable:
            detail = f": {self.note}" if self.note else ""
            raise UnsupportedIdentifierMapping(
                f"Cannot map MineDojo {self.kind} {self.source!r} "
                f"(variant={self.source_variant!r}){detail}"
            )
        assert self.target is not None
        return self.target

    def to_dict(self) -> dict[str, Any]:
        return {"protocol": MAPPING_PROTOCOL, **asdict(self), "executable": self.executable}


def _bare_identifier(value: Any, *, kind: str) -> str:
    identifier = str(value or "").strip().lower()
    if not identifier:
        raise UnsupportedIdentifierMapping(f"MineDojo {kind} identifier cannot be empty")
    if ":" in identifier:
        namespace, identifier = identifier.split(":", 1)
        if namespace != "minecraft":
            raise UnsupportedIdentifierMapping(
                f"MineDojo port only supports the minecraft namespace, got {namespace!r}"
            )
    return identifier


_COLORS = (
    "white",
    "orange",
    "magenta",
    "light_blue",
    "yellow",
    "lime",
    "pink",
    "gray",
    "light_gray",
    "cyan",
    "purple",
    "blue",
    "brown",
    "green",
    "red",
    "black",
)

# Metadata-bearing item families in 1.11.2.  The zero member is also the
# deterministic canonical target when the old task only names the family.
_ITEM_VARIANTS: dict[str, tuple[str, ...]] = {
    "stone": (
        "stone",
        "granite",
        "polished_granite",
        "diorite",
        "polished_diorite",
        "andesite",
        "polished_andesite",
    ),
    "dirt": ("dirt", "coarse_dirt", "podzol"),
    "planks": (
        "oak_planks",
        "spruce_planks",
        "birch_planks",
        "jungle_planks",
        "acacia_planks",
        "dark_oak_planks",
    ),
    "sapling": (
        "oak_sapling",
        "spruce_sapling",
        "birch_sapling",
        "jungle_sapling",
        "acacia_sapling",
        "dark_oak_sapling",
    ),
    "sand": ("sand", "red_sand"),
    "log": ("oak_log", "spruce_log", "birch_log", "jungle_log"),
    "log2": ("acacia_log", "dark_oak_log"),
    "leaves": ("oak_leaves", "spruce_leaves", "birch_leaves", "jungle_leaves"),
    "leaves2": ("acacia_leaves", "dark_oak_leaves"),
    "sponge": ("sponge", "wet_sponge"),
    "sandstone": ("sandstone", "chiseled_sandstone", "smooth_sandstone"),
    "red_sandstone": ("red_sandstone", "chiseled_red_sandstone", "smooth_red_sandstone"),
    "coal": ("coal", "charcoal"),
    "fish": ("cod", "salmon", "tropical_fish", "pufferfish"),
    "cooked_fish": ("cooked_cod", "cooked_salmon"),
    "golden_apple": ("golden_apple", "enchanted_golden_apple"),
    "wool": tuple(f"{color}_wool" for color in _COLORS),
    "carpet": tuple(f"{color}_carpet" for color in _COLORS),
    "stained_glass": tuple(f"{color}_stained_glass" for color in _COLORS),
    "stained_glass_pane": tuple(f"{color}_stained_glass_pane" for color in _COLORS),
    "stained_hardened_clay": tuple(f"{color}_terracotta" for color in _COLORS),
    "bed": tuple(f"{color}_bed" for color in _COLORS),
    "dye": (
        "ink_sac",
        "red_dye",
        "green_dye",
        "cocoa_beans",
        "lapis_lazuli",
        "purple_dye",
        "cyan_dye",
        "light_gray_dye",
        "gray_dye",
        "pink_dye",
        "lime_dye",
        "yellow_dye",
        "light_blue_dye",
        "magenta_dye",
        "orange_dye",
        "bone_meal",
    ),
    "red_flower": (
        "poppy",
        "blue_orchid",
        "allium",
        "azure_bluet",
        "red_tulip",
        "orange_tulip",
        "white_tulip",
        "pink_tulip",
        "oxeye_daisy",
    ),
    "yellow_flower": ("dandelion",),
    "monster_egg": (
        "infested_stone",
        "infested_cobblestone",
        "infested_stone_bricks",
        "infested_mossy_stone_bricks",
        "infested_cracked_stone_bricks",
        "infested_chiseled_stone_bricks",
    ),
    "skull": (
        "skeleton_skull",
        "wither_skeleton_skull",
        "zombie_head",
        "player_head",
        "creeper_head",
        "dragon_head",
    ),
}


# Non-metadata renames and deterministic choices for old generic families.
_ITEM_ALIASES = {
    "banner": "white_banner",
    "boat": "oak_boat",
    "brick_block": "bricks",
    "chorus_fruit_popped": "popped_chorus_fruit",
    "end_bricks": "end_stone_bricks",
    "ender_eye": "ender_eye",
    "fence": "oak_fence",
    "fence_gate": "oak_fence_gate",
    "grass_path": "dirt_path",
    "lit_pumpkin": "jack_o_lantern",
    "magma": "magma_block",
    "netherbrick": "nether_brick",
    "nether_brick_block": "nether_bricks",
    "noteblock": "note_block",
    "quartz_ore": "nether_quartz_ore",
    "red_nether_brick": "red_nether_bricks",
    "reeds": "sugar_cane",
    "sign": "oak_sign",
    "slime": "slime_block",
    "speckled_melon": "glistering_melon_slice",
    "stonebrick": "stone_bricks",
    "trapdoor": "oak_trapdoor",
    "web": "cobweb",
    "wooden_button": "oak_button",
    "wooden_door": "oak_door",
    "wooden_pressure_plate": "oak_pressure_plate",
}


def map_item(identifier: Any, *, variant: int | None = None) -> MappingResult:
    """Map one MineDojo item/block identifier to a 1.16.5 flattened ID."""

    source = _bare_identifier(identifier, kind="item")
    if variant is not None and (isinstance(variant, bool) or not isinstance(variant, int) or variant < 0):
        raise UnsupportedIdentifierMapping(f"Invalid MineDojo item metadata: {variant!r}")

    variants = _ITEM_VARIANTS.get(source)
    if variants is not None:
        selected = 0 if variant is None else variant
        if selected >= len(variants):
            return MappingResult(
                kind="item",
                source=source,
                target=None,
                status=UNSUPPORTED,
                source_variant=variant,
                note=f"metadata is outside the supported 0..{len(variants) - 1} range",
            )
        return MappingResult(
            kind="item",
            source=source,
            target=variants[selected],
            status=VARIANT_FLATTENED if variant is not None else CANONICALIZED,
            source_variant=variant,
            note=(
                None
                if variant is not None
                else "the 1.11 family omitted metadata; the zero/default member is used"
            ),
        )

    alias = _ITEM_ALIASES.get(source)
    if alias is not None:
        if variant not in (None, 0):
            return MappingResult(
                kind="item",
                source=source,
                target=None,
                status=UNSUPPORTED,
                source_variant=variant,
                note="non-zero metadata has no declared 1.16 mapping",
            )
        return MappingResult(
            kind="item",
            source=source,
            target=alias,
            status=RENAMED,
            source_variant=variant,
        )

    if variant not in (None, 0):
        return MappingResult(
            kind="item",
            source=source,
            target=None,
            status=UNSUPPORTED,
            source_variant=variant,
            note="1.16 uses flattened IDs and this legacy metadata value is not declared",
        )
    return MappingResult(kind="item", source=source, target=source, status=EXACT, source_variant=variant)


_ENTITY_ALIASES = {
    "evocation_illager": "evoker",
    "mushroom_cow": "mooshroom",
    "snowman": "snow_golem",
    "villager_golem": "iron_golem",
    "vindication_illager": "vindicator",
    "xp_orb": "experience_orb",
    "zombie_pigman": "zombified_piglin",
}


def map_entity(identifier: Any) -> MappingResult:
    """Map one MineDojo entity identifier to the 1.16.5 entity registry."""

    source = _bare_identifier(identifier, kind="entity")
    target = _ENTITY_ALIASES.get(source, source)
    return MappingResult(
        kind="entity",
        source=source,
        target=target,
        status=RENAMED if target != source else EXACT,
    )


# MineDojo exposes the legacy biome names below.  Minecraft retained their raw
# numeric IDs through 1.16, although many display names changed.  BiomeGenerator
# consumes the numeric registry ID rather than the display name.
MINECRAFT_1_11_BIOME_IDS: dict[str, int] = {
    "ocean": 0,
    "plains": 1,
    "desert": 2,
    "extreme_hills": 3,
    "forest": 4,
    "taiga": 5,
    "swampland": 6,
    "river": 7,
    "nether": 8,
    "the_end": 9,
    "frozen_ocean": 10,
    "frozen_river": 11,
    "ice_plains": 12,
    "ice_mountains": 13,
    "mushroom_island": 14,
    "mushroom_island_shore": 15,
    "beach": 16,
    "desert_hills": 17,
    "forest_hills": 18,
    "taiga_hills": 19,
    "extreme_hills_edge": 20,
    "jungle": 21,
    "jungle_hills": 22,
    "jungle_edge": 23,
    "deep_ocean": 24,
    "stone_beach": 25,
    "cold_beach": 26,
    "birch_forest": 27,
    "birch_forest_hills": 28,
    "roofed_forest": 29,
    "cold_taiga": 30,
    "cold_taiga_hills": 31,
    "mega_taiga": 32,
    "mega_taiga_hills": 33,
    "extreme_hills_plus": 34,
    "savanna": 35,
    "savanna_plateau": 36,
    "mesa": 37,
    "mesa_plateau_f": 38,
    "mesa_plateau": 39,
    "the_void": 127,
    "plains_m": 128,
    "sunflower_plains": 129,
    "desert_m": 130,
    "extreme_hills_m": 131,
    "flower_forest": 132,
    "taiga_m": 133,
    "swampland_m": 134,
    "ice_plains_spikes": 140,
    "jungle_m": 149,
    "jungle_edge_m": 151,
    "birch_forest_m": 155,
    "tall_birch_hills": 156,
    "roofed_forest_m": 157,
    "cold_taiga_m": 158,
    "mega_spruce_taiga": 160,
    "mega_spruce_taiga_hills": 161,
    "extreme_hills_plus_m": 162,
    "savanna_m": 163,
    "savanna_plateau_m": 164,
    "mesa_bryce": 165,
    "mesa_plateau_f_m": 166,
    "mesa_plateau_m": 167,
}


def map_biome(value: Any) -> MappingResult:
    """Map a MineDojo legacy biome name/ID to the raw 1.16.5 biome ID."""

    if isinstance(value, bool):
        raise UnsupportedIdentifierMapping(f"Invalid MineDojo biome: {value!r}")
    if isinstance(value, int):
        if value not in set(MINECRAFT_1_11_BIOME_IDS.values()):
            return MappingResult(
                kind="biome",
                source=value,
                target=None,
                status=UNSUPPORTED,
                note="not present in MineDojo's declared 1.11 biome registry",
            )
        return MappingResult(kind="biome", source=value, target=value, status=EXACT)

    source = _bare_identifier(value, kind="biome")
    try:
        target = MINECRAFT_1_11_BIOME_IDS[source]
    except KeyError:
        return MappingResult(
            kind="biome",
            source=source,
            target=None,
            status=UNSUPPORTED,
            note="not present in MineDojo's declared 1.11 biome registry",
        )
    return MappingResult(kind="biome", source=source, target=target, status=RENAMED)


MINECRAFT_INVENTORY_SLOTS: dict[str, int] = {
    "mainhand": 0,
    "main_hand": 0,
    "offhand": 40,
    "off_hand": 40,
    "head": 39,
    "chest": 38,
    "legs": 37,
    "feet": 36,
}


def map_inventory_slot(value: Any) -> int:
    """Resolve MineDojo named equipment slots or numeric inventory slots."""

    if isinstance(value, bool):
        raise ValueError(f"Invalid MineDojo inventory slot: {value!r}")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in MINECRAFT_INVENTORY_SLOTS:
            return MINECRAFT_INVENTORY_SLOTS[normalized]
        try:
            value = int(normalized)
        except ValueError as exc:
            raise ValueError(f"Unknown MineDojo inventory slot: {value!r}") from exc
    slot = int(value)
    if not 0 <= slot <= 40:
        raise ValueError(f"MineDojo inventory slot must be in 0..40, got {slot}")
    return slot


__all__ = [
    "CANONICALIZED",
    "EXACT",
    "MAPPING_PROTOCOL",
    "MINECRAFT_1_11_BIOME_IDS",
    "MINECRAFT_INVENTORY_SLOTS",
    "MappingResult",
    "RENAMED",
    "UNSUPPORTED",
    "UnsupportedIdentifierMapping",
    "VARIANT_FLATTENED",
    "map_biome",
    "map_entity",
    "map_inventory_slot",
    "map_item",
]
