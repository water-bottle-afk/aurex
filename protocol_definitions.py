from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

FIELD_SEPARATOR = "|"


class ProtocolCommand(StrEnum):
    START = "START"
    LOGIN = "LOGIN"
    SIGNUP = "SIGNUP"
    SEND_CODE = "SEND_CODE"
    VERIFY_CODE = "VERIFY_CODE"
    UPDATE_PASSWORD = "UPDATE_PASSWORD"
    LOGOUT = "LOGOUT"
    UPLOAD = "UPLOAD"
    UPLOAD_INIT = "UPLOAD_INIT"
    UPLOAD_CHUNK = "UPLOAD_CHUNK"
    UPLOAD_FINISH = "UPLOAD_FINISH"
    UPLOAD_ABORT = "UPLOAD_ABORT"
    GET_ASSET_BINARY = "GET_ASSET_BINARY"
    GET_ITEMS = "GET_ITEMS"
    GET_ITEMS_PAGINATED = "GET_ITEMS_PAGINATED"
    BUY = "BUY"
    SEND = "SEND"
    GET_PROFILE = "GET_PROFILE"
    GET_TX_STATUS = "GET_TX_STATUS"
    GET_ITEMS_BY_USER = "GET_ITEMS_BY_USER"
    GET_WALLET = "GET_WALLET"
    GET_NOTIFICATIONS = "GET_NOTIFICATIONS"
    MARK_NOTIFICATIONS_READ = "MARK_NOTIFICATIONS_READ"
    REGISTER_DEVICE = "REGISTER_DEVICE"
    LIST_ITEM = "LIST_ITEM"
    UNLIST_ITEM = "UNLIST_ITEM"
    UPDATE_PUBLIC_KEY = "UPDATE_PUBLIC_KEY"


class ProtocolPrefix(StrEnum):
    OK = "OK"
    ACCEPT = "ACCPT"
    EVENT = "EVENT"
    ASSET_START = "ASSET_START"
    GOTPRT = "GOTPRT"


class DiscoveryToken(StrEnum):
    REQUEST = "WHRSRV"
    RESPONSE = "SRVRSP"


CLIENT_IDENTITY = "Client_Flet_App"
ERROR_PREFIXES = ("ERR", "PTHERR", "GRLERR")

UPLOAD_CHUNK_PREFIX = f"{ProtocolCommand.UPLOAD_CHUNK}{FIELD_SEPARATOR}".encode("utf-8")
GET_ASSET_BINARY_PREFIX = f"{ProtocolCommand.GET_ASSET_BINARY}{FIELD_SEPARATOR}".encode("utf-8")
EVENT_PREFIX = f"{ProtocolPrefix.EVENT}{FIELD_SEPARATOR}"


@dataclass(frozen=True)
class WireMessage:
    head: str
    parts: tuple[str, ...] = ()

    def to_text(self) -> str:
        return join_wire_fields(self.head, *self.parts)

    @classmethod
    def from_text(cls, payload: str) -> "WireMessage":
        head, parts = split_wire_fields(payload)
        return cls(head=head, parts=tuple(parts))


@dataclass(frozen=True)
class DiscoveryRequest:
    token: str = DiscoveryToken.REQUEST.value

    def to_bytes(self) -> bytes:
        return self.token.encode("utf-8")

    @classmethod
    def matches(cls, payload: str) -> bool:
        return payload.strip() == DiscoveryToken.REQUEST.value


@dataclass(frozen=True)
class DiscoveryResponse:
    host: str
    port: int
    token: str = DiscoveryToken.RESPONSE.value

    def to_text(self) -> str:
        return join_wire_fields(self.token, self.host, self.port)

    @classmethod
    def from_text(cls, payload: str) -> "DiscoveryResponse | None":
        head, parts = split_wire_fields(payload)
        if head != DiscoveryToken.RESPONSE.value or len(parts) < 2:
            return None
        try:
            return cls(host=parts[0], port=int(parts[1]))
        except ValueError:
            return None


def join_wire_fields(head: str | ProtocolCommand | ProtocolPrefix, *parts: Any) -> str:
    text_parts = [str(head), *(str(part) for part in parts)]
    return FIELD_SEPARATOR.join(text_parts)


def split_wire_fields(payload: str) -> tuple[str, list[str]]:
    fields = payload.split(FIELD_SEPARATOR)
    head = fields[0].strip() if fields else ""
    return head, fields[1:]


def serialize_command(command: ProtocolCommand, *parts: Any) -> str:
    return join_wire_fields(command.value, *parts)


def serialize_response(prefix: ProtocolPrefix, *parts: Any) -> str:
    return join_wire_fields(prefix.value, *parts)


def serialize_event(payload: dict[str, Any]) -> str:
    return serialize_response(ProtocolPrefix.EVENT, json.dumps(payload))


def parse_wire_message(payload: str) -> WireMessage:
    return WireMessage.from_text(payload)


def is_error_response(payload: str) -> bool:
    return payload.startswith(ERROR_PREFIXES)
