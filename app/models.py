"""Domain records. Repos return these; handlers do not speak raw mappings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class User:
    id: int
    max_user_id: int
    name: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> User:
        return cls(id=int(row["id"]), max_user_id=int(row["max_user_id"]), name=str(row["name"] or ""))


@dataclass(frozen=True)
class Overlay:
    position: str = "se"
    width_pct: int = 30
    opacity: int = 100
    rotation_deg: int = 0
    pad_x: int = 0
    pad_y: int = 0


@dataclass(frozen=True)
class DayStats:
    photos: int
    videos: int
    bytes_out: int


@dataclass(frozen=True)
class Template:
    id: int
    user_id: int
    name: str
    file_path: str
    position: str = "se"
    width_pct: int = 30
    opacity: int = 100
    rotation_deg: int = 0
    pad_x: int = 0
    pad_y: int = 0
    is_default: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Template:
        return cls(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            file_path=str(row["file_path"]),
            position=str(row["position"]),
            width_pct=int(row["width_pct"]),
            opacity=int(row["opacity"]),
            rotation_deg=int(row["rotation_deg"]),
            pad_x=int(row["pad_x"]),
            pad_y=int(row["pad_y"]),
            is_default=bool(row["is_default"]),
        )

    def overlay(self) -> Overlay:
        return Overlay(
            position=self.position,
            width_pct=self.width_pct,
            opacity=self.opacity,
            rotation_deg=self.rotation_deg,
            pad_x=self.pad_x,
            pad_y=self.pad_y,
        )


@dataclass(frozen=True)
class Tail:
    id: int
    user_id: int
    name: str
    file_path: str
    placement: str = "end"
    is_default: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Tail:
        return cls(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            file_path=str(row["file_path"]),
            placement=str(row["placement"]),
            is_default=bool(row["is_default"]),
        )


@dataclass(frozen=True)
class Channel:
    id: int
    user_id: int
    chat_id: int
    title: str
    template_id: Optional[int] = None
    use_tail: bool = False
    enabled: bool = True

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Channel:
        tid = row["template_id"]
        return cls(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            chat_id=int(row["chat_id"]),
            title=str(row["title"] or ""),
            template_id=int(tid) if tid is not None else None,
            use_tail=bool(row["use_tail"]),
            enabled=bool(row["enabled"]),
        )
