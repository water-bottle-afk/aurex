from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


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


@dataclass(frozen=True)
class ItemOffering:
    id: str
    title: str
    description: str
    image_url: str
    author: str
    price: float
    is_listed: bool = True
    token: str | None = None
    asset_hash: str | None = None

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "ItemOffering":
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
            token=raw_id or None,
            asset_hash=(
                str(payload["asset_hash"]) if payload.get("asset_hash") is not None else None
            ),
        )


@dataclass(frozen=True)
class NotificationItem:
    id: int
    username: str
    title: str
    body: str
    type: str
    is_read: bool
    created_at: datetime
    asset_id: str | None = None
    tx_id: str | None = None

    @classmethod
    def from_map(cls, payload: Mapping[str, Any]) -> "NotificationItem":
        raw_id = payload.get("id")
        raw_read = payload.get("is_read")
        created_raw = payload.get("created_at")
        created_at = datetime.fromisoformat(str(created_raw)) if created_raw else datetime.utcnow()
        return cls(
            id=int(raw_id) if raw_id is not None and str(raw_id).isdigit() else 0,
            username=str(payload.get("username") or ""),
            title=str(payload.get("title") or "Notification"),
            body=str(payload.get("body") or ""),
            type=str(payload.get("type") or "system"),
            is_read=raw_read in (1, "1", True),
            created_at=created_at,
            asset_id=str(payload.get("asset_id")) if payload.get("asset_id") is not None else None,
            tx_id=str(payload.get("tx_id")) if payload.get("tx_id") is not None else None,
        )


@dataclass(frozen=True)
class ServerEvent:
    event: str
    payload: dict[str, Any]

    @classmethod
    def from_json(cls, json_str: str) -> "ServerEvent":
        import json

        decoded = json.loads(json_str)
        if not isinstance(decoded, dict):
            raise ValueError(f"Invalid ServerEvent JSON: {json_str}")
        payload = decoded.get("payload") or {}
        return cls(
            event=str(decoded.get("event") or ""),
            payload=dict(payload) if isinstance(payload, dict) else {},
        )
