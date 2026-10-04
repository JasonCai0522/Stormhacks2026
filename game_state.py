"""Typed SF6 snapshots and JSON loading, independent of controller output."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal, get_args


GAME_STATE_PATH = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Street Fighter 6\reframework\data\p1_character.json"
)

Direction = Literal["left", "right"]
CharacterName = Literal[
    "Ryu", "Luke", "Kimberly", "Chun-Li", "Manon", "Zangief", "JP",
    "Dhalsim", "Cammy", "Ken", "Dee Jay", "Lily", "A.K.I.", "Rashid",
    "Blanka", "Juri", "Marisa", "Guile", "Ed", "E. Honda", "Jamie", "Akuma",
    "M. Bison", "Terry", "Mai", "Elena", "Sagat", "C. Viper", "Alex", "Ingrid",
]
CHARACTER_NAMES = frozenset(get_args(CharacterName))


@dataclass(frozen=True, slots=True)
class GameState:
    """Player-one snapshot. Missing legacy health/name values remain unknown."""

    p1_facing: Direction = "right"
    p1_health: int | None = None
    p1_health_old: int | None = None
    p1_name: CharacterName | None = None
    p1_side: Direction | None = None
    p1_take_damage: bool = False

    def __post_init__(self):
        if self.p1_facing not in ("left", "right"):
            raise ValueError("p1_facing must be left or right")
        if self.p1_side is not None and self.p1_side not in ("left", "right"):
            raise ValueError("p1_side must be left or right")
        for field in ("p1_health", "p1_health_old"):
            value = getattr(self, field)
            if value is not None and (type(value) is not int or not 0 <= value <= 10000):
                raise ValueError(f"{field} must be an integer between 0 and 10000")
        if self.p1_name is not None and self.p1_name not in CHARACTER_NAMES:
            raise ValueError("p1_name must be a recognized SF6 character name")
        if type(self.p1_take_damage) is not bool:
            raise ValueError("p1_take_damage must be a boolean")

    @property
    def facing(self) -> Direction:
        """Prefer the earlier side signal, preserving existing facing behavior."""
        if self.p1_side is not None:
            return "right" if self.p1_side == "left" else "left"
        return self.p1_facing

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        if not isinstance(data, dict):
            raise ValueError("Game state must be a JSON object")
        # The existing Lua exporter emits empty strings outside a match and
        # omits health/damage fields. Do not invent health values for it.
        name = data.get("p1_name")
        if name == "C.Viper":
            name = "C. Viper"
        facing = data.get("p1_facing", "right")
        side = data.get("p1_side")
        return cls(
            p1_facing="right" if facing == "" else facing,
            p1_health=data.get("p1_health"),
            p1_health_old=data.get("p1_health_old"),
            p1_name=None if name == "" else name,
            p1_side=None if side == "" else side,
            p1_take_damage=data.get("p1_take_damage", False),
        )


def read_game_state(path: str | Path = GAME_STATE_PATH) -> GameState | None:
    """Read one snapshot; unavailable/partial/invalid files return None."""
    try:
        with open(path, encoding="utf-8") as file:
            return GameState.from_dict(json.load(file))
    except (OSError, ValueError, TypeError):
        return None
