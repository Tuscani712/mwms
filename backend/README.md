# WMS Backend

FastAPI + SQLAlchemy 2.0 + SQLite (Postgres-portable) backend for the Warehouse Management System.

## Quick start

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Seed mock data (drops + recreates tables)
python -m wms.seeders.seed

# Run the API
uvicorn wms.main:app --reload --port 8000
```

Open http://localhost:8000/docs for interactive Swagger UI.

## Project layout

```
backend/
├── pyproject.toml            # deps + tool config (ruff, pytest)
├── .env.example              # copy to .env, never commit
├── wms/
│   ├── main.py               # FastAPI app + CORS + router wiring
│   ├── core/
│   │   ├── config.py         # Settings (env-driven)
│   │   ├── security.py       # bcrypt + JWT
│   │   └── deps.py           # FastAPI DI (DB session, current user)
│   ├── db/
│   │   ├── base.py           # Declarative Base + naming convention
│   │   └── session.py        # Engine + SessionLocal
│   ├── models/               # SQLAlchemy ORM models
│   │   ├── core.py           # Site, User
│   │   ├── inventory.py      # SKU, Lot, Location, LotGenealogy
│   │   └── ops.py            # ASN, Receipt, Order, Pick, Shipment, QCHold
│   ├── schemas/              # Pydantic request/response shapes
│   ├── services/             # Business logic (receiving, shipping)
│   ├── api/v1/               # Routers (auth, health, sites, receiving, shipping)
│   └── seeders/seed.py       # Idempotent mock data
└── tests/                    # pytest test suite
```

## Endpoints (v1)

### Auth
- `POST /api/v1/auth/login` — `{employee_code, password, site_id}` → JWT
- `GET  /api/v1/auth/me` — current user

### Sites
- `GET /api/v1/sites` — list all sites (for login picker)

### Health
- `GET /api/v1/health/ping` — `{ok: true}` (latency probe)
- `GET /api/v1/health` — `{status, build, boot_time, uptime_seconds}`

### Receiving
- `GET  /api/v1/receiving/inbound` — open ASNs
- `POST /api/v1/receiving/check-in` — assign dock door, set status=receiving
- `POST /api/v1/receiving/receipts` — record receipt with QC + variance, creates Lots
- `GET  /api/v1/receiving/putaway-suggestions/{asn_id}` — FIFO primary + overflow

### Shipping
- `GET  /api/v1/shipping/orders?status=open` — orders list
- `GET  /api/v1/shipping/consolidation/{order_id}/{order_line_id}` — FIFO/FEFO plan
- `POST /api/v1/shipping/picks` — assign picks across lots (FIFO/FEFO)
- `POST /api/v1/shipping/truck-load` — load picked order onto a shipment
- `GET  /api/v1/shipping/packing-slip/{order_id}` — generate slip

## Auth model

Every JWT carries `{sub: employee_code, site_id, role}`. The `get_current_user`
dependency loads the user **only** when both `employee_code` and `site_id` match
an active row — a stolen token from WHS-001 cannot authenticate against WHS-002.

## Testing

```bash
pytest -v                # full suite (in-memory SQLite, no fixtures persist)
ruff check .             # lint
ruff format .            # format
```

## Mock data

`wms.seeders.seed` populates:
- 5 sites (MCS + 4 warehouses; WHS-004 simulated offline)
- ~140 users across roles (operator/lead/supervisor/manager/admin)
- ~150 SKUs (12 templates × 4 sites, plus 20 generic per site)
- ~900 lots, ~50 locations, ~50 ASNs, ~60 orders, 12 shipments, ~25 QC holds

Login as `MCS-ADMIN` / `admin1234` or any `WHS-00X-001` / `password123`.
