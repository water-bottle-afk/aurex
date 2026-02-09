# Where Dart Asks the Server for Assets (e.g. 10) and How They Show in the App

## 1. Flutter (lib) – Who asks and where

### Entry: Marketplace page loads / scrolls

- **File:** `lib/pages/marketplace_page.dart`
- **What happens:** On init and when the user scrolls near the bottom, the page calls `AssetsProvider.loadNextPage()`.
- **Init (first 10):** Around lines 28–34, a microtask runs: if `assetsProvider.assets.isEmpty`, it calls `assetsProvider.loadNextPage()`.
- **Scroll (next 10, etc.):** In `_onScroll()` (lines 45–52), when the user is within 500px of the bottom and `hasMoreAssets` and not `isLoading`, it calls `assetsProvider.loadNextPage()` again.

### Provider: Builds the request and talks to the client

- **File:** `lib/providers/assets_provider.dart`
- **What happens:** `loadNextPage()` (lines 23–82) uses the shared `Client` to request one page of assets.
- **Request:** It calls `client.getMarketplaceItemsPaginated(limit: _itemsPerPage, lastTimestamp: _lastTimestamp)` where `_itemsPerPage` is 10 (line 12). So the first time it’s “give me 10 assets”; next time it’s “give me 10 after this timestamp”.
- **Response:** The server returns a list of item maps. The provider maps each to `ItemOffering` (id, title, imageUrl, author, price, etc.) and appends to `_assets`, and updates `_lastTimestamp` from the last item for the next page.

### Client: Sends the protocol message to the server

- **File:** `lib/client_class.dart`
- **What happens:** `getMarketplaceItemsPaginated()` (lines 657–701) builds the message and sends it over the TLS socket.
- **Message sent:** `GET_ITEMS_PAGINATED|10` for the first page, or `GET_ITEMS_PAGINATED|10|<lastTimestamp>` for the next (e.g. next 10 after that timestamp).
- **Response:** It reads the reply, parses `OK|<json array>`, decodes the JSON list of items, and returns it to the provider.

So in **lib/pages** and **lib/providers**, the place that “asks the server for 10 assets” is:

- **Pages:** `lib/pages/marketplace_page.dart` (init + scroll) → calls `AssetsProvider.loadNextPage()`.
- **Provider:** `lib/providers/assets_provider.dart` → `loadNextPage()` calls `client.getMarketplaceItemsPaginated(limit: 10, ...)`.
- **Client:** `lib/client_class.dart` → `getMarketplaceItemsPaginated()` sends `GET_ITEMS_PAGINATED|10` (or with timestamp) and returns the decoded list.

---

## 2. Server – Reads from `marketplace_items` and returns them

- **File:** `python_files/server_moudle.py`
- **Handler:** `handle_get_items_paginated()` (around lines 453–490).
- **What happens:** It parses `GET_ITEMS_PAGINATED|limit|lastTimestamp`, then uses the ORM (`DB_ORM.MarketplaceDB`) to read from the **marketplace_items** table:
  - First page: `db.get_latest_items(limit)` (e.g. 10).
  - Next pages: `db.get_items_before_timestamp(lastTimestamp, limit)`.
- **Response:** It builds a list of dicts (id, asset_name, username, url, file_type, cost, timestamp, created_at) and returns `OK|<json list>` to the client.

---

## 3. ORM – Actual DB read from `marketplace_items`

- **File:** `python_files/DB_ORM.py`
- **Class:** `MarketplaceDB`
- **Methods:** `get_latest_items(limit)` and `get_items_before_timestamp(timestamp, limit)` both use `get_items_paginated()`, which runs a `SELECT` on the **marketplace_items** table (ordered by `created_at DESC`, with optional `WHERE created_at < ?` and `LIMIT ?`).

So the server **only** reads/writes the DB through this ORM (e.g. login, signup, get user by email, fetch assets from `marketplace_items`).

---

## 4. How the app shows the assets

- **File:** `lib/pages/marketplace_page.dart`
- **UI:** A `GridView.builder` (around lines 246–352) whose `itemCount` is `assetsProvider.assets.length + (loading ? 1 : 0)` and whose `itemBuilder` uses `assetsProvider.assets[index]` as `ItemOffering`: card with image (from `item.imageUrl`), title, price, author. Tapping goes to `/marketplace/asset/:id` with that item.

End-to-end: **MarketplacePage** → **AssetsProvider.loadNextPage()** → **Client.getMarketplaceItemsPaginated(10, …)** → server **handle_get_items_paginated** → **MarketplaceDB** (marketplace_items) → **OK|json** → client → provider converts to **ItemOffering** and notifies → **MarketplacePage** grid shows them.
