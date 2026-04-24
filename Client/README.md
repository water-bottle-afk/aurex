# Client Folder Overview

This folder contains the Flet UI and the secure WSS client protocol layer.

- `app.py`: app lifecycle, routing, and session-driven UI refresh.
- `protocol_client.py`: WSS transport, CA validation, request/response protocol.
- `../protocol_definitions.py`: shared command/message schema used by client and server.
- `../aurex_logging.py`: shared logging class (`AurexLogger`).
- `login.py`, `signup.py`, `forgot.py`: auth flows.
- `marketplace.py`, `my_assets.py`, `upload.py`, `notifications.py`: product features.
- `wallet.py`: local Ed25519 key management and signing.
- `session.py`, `models.py`: state and DTO models.
- `theme.py`: shared design tokens.

Logging is centralized via `Server/config.py` (`AUREX_DEBUG_MODE` / `DEBUG_MODE`).
