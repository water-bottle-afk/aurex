# Server Folder Overview

This folder contains the marketplace backend and persistence layer.

- `server_module.py`: main WSS server, protocol handlers, upload pipeline, tx queue.
- `DB_ORM.py`: SQLite access for users, assets, wallets, notifications.
- `config.py`: runtime configuration, TLS paths, logging setup (`DEBUG_MODE`).
- `classes.py`: protocol/logging helper classes.
- `protocol_server.py`: facade over shared protocol definitions.
- `../protocol_definitions.py`: single source of truth for protocol commands/messages.
- `../aurex_logging.py`: shared logging class (`AurexLogger`) and configuration.

Run options:

- From repo root: `python -m Server.server_module`
- From this folder: `python server_module.py`

TLS files default to `HTTPS/server.crt` and `HTTPS/server.key`.
