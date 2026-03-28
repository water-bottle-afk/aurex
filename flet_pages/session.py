from __future__ import annotations

from dataclasses import dataclass, field
import ssl
import threading
import uuid

from .models import MarketplaceItem


@dataclass
class UserData:
    username: str
    email: str = ""


@dataclass
class UserSession:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    socket: ssl.SSLSocket | None = None
    host: str | None = None
    port: int | None = None
    user_data: UserData | None = None
    reset_token: str | None = None
    market_items: list[MarketplaceItem] = field(default_factory=list)
    last_market_cursor: str | None = None
    image_cache: dict[str, str] = field(default_factory=dict)
    loading_images: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def is_authenticated(self) -> bool:
        return self.user_data is not None

    def clear_user_state(self) -> None:
        self.user_data = None
        self.reset_token = None
        self.market_items.clear()
        self.last_market_cursor = None
        self.image_cache.clear()
        self.loading_images.clear()

    def remember(self, message: str) -> None:
        self.messages.append(message)
        if len(self.messages) > 200:
            del self.messages[: len(self.messages) - 200]
