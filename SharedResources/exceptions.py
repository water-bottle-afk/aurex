"""
exceptions.py — Custom exception hierarchy for the Aurex marketplace.

All domain errors inherit from AurexError so callers can do a single
except AurexError clause without losing specificity.  Every exception
carries error_type so server/gateway handlers can map it to a protocol
response without string parsing.
"""
from __future__ import annotations


class AurexError(Exception):
    """Base for all Aurex domain errors."""
    error_type: str = "ERROR"

    def __init__(self, msg: str):
        super().__init__(msg)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


class ValidationError(AurexError):
    """Bad input — missing field, wrong format, out-of-range value."""
    error_type = "VALIDATION_ERROR"


class AuthError(AurexError):
    """Authentication or authorization failure."""
    error_type = "AUTH_ERROR"


class NotFoundError(AurexError):
    """Requested resource does not exist."""
    error_type = "NOT_FOUND"


class DuplicateError(AurexError):
    """Resource or transaction already exists / already processed."""
    error_type = "DUPLICATE_ERROR"


class GatewayError(AurexError):
    """Gateway is offline or refused the request."""
    error_type = "GATEWAY_ERROR"


class TransferError(AurexError):
    """Asset ownership transfer failed (race condition, already sold, etc.)."""
    error_type = "TRANSFER_ERROR"


class BlockchainError(AurexError):
    """Mining / blockchain validation failure."""
    error_type = "BLOCKCHAIN_ERROR"


class UploadError(AurexError):
    """File upload or sanitization failure."""
    error_type = "UPLOAD_ERROR"


class SessionError(AurexError):
    """Upload session not found or expired."""
    error_type = "SESSION_ERROR"
