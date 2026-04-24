"""
Server-side protocol facade.

Canonical protocol definitions live in `protocol_definitions.py`.
"""

from protocol_definitions import (
    CLIENT_IDENTITY,
    ERROR_PREFIXES,
    EVENT_PREFIX,
    FIELD_SEPARATOR,
    GET_ASSET_BINARY_PREFIX,
    UPLOAD_CHUNK_PREFIX,
    DiscoveryRequest,
    DiscoveryResponse,
    DiscoveryToken,
    ProtocolCommand,
    ProtocolPrefix,
    WireMessage,
    is_error_response,
    join_wire_fields,
    parse_wire_message,
    serialize_command,
    serialize_event,
    serialize_response,
    split_wire_fields,
)

__all__ = [
    "FIELD_SEPARATOR",
    "CLIENT_IDENTITY",
    "ERROR_PREFIXES",
    "EVENT_PREFIX",
    "UPLOAD_CHUNK_PREFIX",
    "GET_ASSET_BINARY_PREFIX",
    "ProtocolCommand",
    "ProtocolPrefix",
    "DiscoveryToken",
    "WireMessage",
    "DiscoveryRequest",
    "DiscoveryResponse",
    "join_wire_fields",
    "split_wire_fields",
    "serialize_command",
    "serialize_response",
    "serialize_event",
    "parse_wire_message",
    "is_error_response",
]

