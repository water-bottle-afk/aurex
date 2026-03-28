from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MarketplaceItem:
    id: str
    title: str
    description: str
    image_url: str
    author: str
    price: float
    is_listed: bool = True
    asset_hash: str | None = None

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "MarketplaceItem":
        raw_id = str(payload.get("id", ""))
        return cls(
            id=raw_id,
            title=str(payload.get("asset_name") or "Unnamed Asset"),
            description=str(
                payload.get("description")
                or payload.get("file_type")
                or "No description provided."
            ),
            image_url=str(payload.get("url") or ""),
            author=str(payload.get("username") or "Unknown"),
            price=float(payload.get("cost") or 0.0),
            is_listed=str(payload.get("is_listed", "1")) == "1",
            asset_hash=(
                str(payload["asset_hash"]) if payload.get("asset_hash") is not None else None
            ),
        )
