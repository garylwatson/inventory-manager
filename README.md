# Inventory Manager

PyQt-based desktop inventory manager with SQLite backend, scheduled backups, and a GUI for vehicles, locations, and assets.

## Features
- SQLite schema with vehicles, locations, inventory items, audit history, and globally unique IDs.
- Configurable via `config.yaml` (DB path, backup schedule, logging).
- Scheduled backups using SQLite backup API with pruning (keeps latest 3 backups by default).
- Manage tab for vehicles and inventory CRUD (with barcode/QR preview, manual code data, custom label lines, size/layout/font/DPI controls, and export to PNG/SVG/EPS).
- View tab with joined inventory/location/vehicle data and filtering.
- Audit tab scaffold for comparing expected vs observed items.
- Vehicles overview with mileage color coding and item counts.
- Dockerfile for reproducible runs.

## Getting Started
### Local (no Docker)
1) Install dependencies (Python 3.11+ recommended):
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Configure `config.yaml` (paths are relative to the repo by default).

3) Run the app:
```bash
python -m inventory_manager
```

Backups run automatically when enabled; use the Tools → Manual Backup menu to trigger one immediately.

## Configuration
`config.yaml` controls core paths and behavior:
```yaml
database:
  path: "./data/inventory.db"
backup:
  enabled: true
  interval_seconds: 300
  directory: "./backups"
  max_backups: 3
logging:
  level: "INFO"
  file: "./logs/app.log"
ui:
  theme: "light"
```
- Directories are created on startup.
- Backups prune to the latest `max_backups` files.
- Logging writes to file if `file` is set, otherwise stdout.

## UI Walkthrough
- **Manage → Inventory**: List and edit assets. Fields for description/manufacturer/model/serial/consumable and location ID. New/Save/Delete/Refresh controls. Barcode and QR previews (Code 39 / QR) with toggles to include description/location/ID; export PNG/SVG/EPS (barcode) or PNG/EPS (QR).
- Label options: choose layout (below/right of code), font size, DPI, barcode text visibility, and module width/height/quiet zone; exports default to `./backups/labels` (mount this volume to keep labels outside the container).
- Manual label editing: override barcode/QR data, add custom label lines, toggle showing barcode text, and tune module width/height/quiet zone for the barcode.
- **Manage → Vehicles**: List and edit vehicles (type/name/VIN/number/mileage/last_service) with the same barcode/QR/export controls as Inventory. Color cues appear in Vehicles tab.
- **View**: Read-only joined view (inventory + location + vehicle) with global search, column-level filters for all fields (including location_id), and CSV/PDF export of the current view.
- **Audit**: Scaffold to load a location, enter observed asset IDs, and compare expected vs observed (missing/extra summary). Apply Fixes is a stub to be extended.
- **Vehicles**: Overview with stored item counts and mileage status coloring (green/yellow/red).
- Status bar shows DB path; Tools menu includes manual backup trigger and CSV export placeholder.

## Seeding Demo Data
Populate test data (vehicles/locations/hundreds of inventory items):
```bash
python -m inventory_manager.seed_demo --items 500
```
Or inside Docker:
```bash
docker run --rm \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config.yaml:/app/config.yaml \
  inventory-manager \
  python -m inventory_manager.seed_demo --items 500
```

### Docker
Build and run with mounted volumes for persistence:
```bash
docker build -t inventory-manager .
docker run --rm -e QT_QPA_PLATFORM=xcb \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/backups:/app/backups \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config.yaml:/app/config.yaml \
  inventory-manager
```

- For headless/CI runs use `-e QT_QPA_PLATFORM=offscreen`.
- On macOS with XQuartz, allow network clients (`xhost +127.0.0.1`), set `DISPLAY=host.docker.internal:0`.
- On Linux with X11, set `DISPLAY` and mount `/tmp/.X11-unix` if needed.

## Notes and Next Steps
- Audit “Apply Fixes” is a stub; wire it to update locations and write `InventoryAudit` rows.
- CSV export is stubbed; extend Tools → Export.
- Barcode/QR export outputs PNG; adjust label composition as needed.
