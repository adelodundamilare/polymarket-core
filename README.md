# Polymarket Core Library

Standalone infrastructure for building and running Polymarket trading bots. This library centralizes API clients, database models, and core trading services.

---

## 1. Modular Architecture

This repository is designed to be imported as a dependency in individual strategy branches (`martingale`, `funding-rate`, etc.), ensuring all bots share the same production-grade infrastructure.

- **`polymarket_core.services`**: Centralized logic for `execute_entry` and `resolve_trade`.
- **`polymarket_core.db`**: Shared SQLAlchemy models and repositories (`TradeRepository`, `OrderRepository`).
- **`polymarket_core.external`**: Robust wrappers for Polymarket Gamma/CLOB APIs and Binance WebSockets.
- **`polymarket_core.core`**: Shared constants, enums, and utility functions.

---

## 2. Installation

### Development (Local)
In your strategy branch, install the library in editable mode:
```bash
pip install -e /path/to/polymarket-core
```

### Production (Git)
Add the following to your `requirements.txt`:
```text
polymarket-core @ git+https://github.com/USER/polymarket-core.git
```

---

## 3. Quick Start

```python
from polymarket_core import initialize_library, get_trading_service
from polymarket_core.db.database import get_session

# 1. Initialize DB and Clients
session = next(get_session())
client = PolymarketClient()
await client.open()

# 2. Setup Core Services
initialize_library(client, trade_repo, order_repo)
trading = get_trading_service()

# 3. Use in Strategy
await trading.execute_entry(trade, order, price, shares)
```

---

## 4. Maintenance

When a core bug is fixed (e.g. resolution client initialization):
1.  Update the logic in this repository.
2.  Push to `core-main` (or your private library repo).
3.  In all strategy bots, run: `pip install --upgrade polymarket-core`.
