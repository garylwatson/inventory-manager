import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .config import AppConfig

logger = logging.getLogger(__name__)


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS GlobalId (
    id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS Vehicle (
    vehicle_id      TEXT PRIMARY KEY,
    vehicle_type    TEXT NOT NULL CHECK (vehicle_type IN ('Truck', 'Trailer')),
    vehicle_name    TEXT NOT NULL,
    vin             TEXT NOT NULL,
    vehicle_number  INTEGER NOT NULL,
    mileage         INTEGER NOT NULL DEFAULT 0,
    last_service    INTEGER NOT NULL DEFAULT 0,

    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vehicle_type ON Vehicle (vehicle_type);
CREATE INDEX IF NOT EXISTS idx_vehicle_number ON Vehicle (vehicle_number);
CREATE INDEX IF NOT EXISTS idx_vehicle_vin ON Vehicle (vin);

CREATE TABLE IF NOT EXISTS Location (
    location_id     TEXT PRIMARY KEY,
    vehicle_id      TEXT,
    side            TEXT NOT NULL,
    row             INTEGER NOT NULL,
    bin             INTEGER NOT NULL,

    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_audited_at TEXT,

    FOREIGN KEY (vehicle_id) REFERENCES Vehicle(vehicle_id)
        ON UPDATE CASCADE
        ON DELETE SET NULL,

    CONSTRAINT uq_location_vehicle_side_row_bin UNIQUE (vehicle_id, side, row, bin)
);

CREATE INDEX IF NOT EXISTS idx_location_vehicle ON Location (vehicle_id);
CREATE INDEX IF NOT EXISTS idx_location_side_row_bin ON Location (side, row, bin);

CREATE TABLE IF NOT EXISTS Inventory (
    asset_id        TEXT PRIMARY KEY,
    description     TEXT NOT NULL,
    location_id     TEXT NOT NULL,
    consumable      INTEGER NOT NULL DEFAULT 0,
    manufacturer    TEXT,
    model           TEXT,
    serial_number   TEXT,

    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,

    FOREIGN KEY (location_id) REFERENCES Location(location_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_inventory_location ON Inventory (location_id);
CREATE INDEX IF NOT EXISTS idx_inventory_description ON Inventory (description);
CREATE INDEX IF NOT EXISTS idx_inventory_manufacturer ON Inventory (manufacturer);
CREATE INDEX IF NOT EXISTS idx_inventory_model ON Inventory (model);
CREATE INDEX IF NOT EXISTS idx_inventory_serial ON Inventory (serial_number);

CREATE TABLE IF NOT EXISTS InventoryAudit (
    audit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id         TEXT NOT NULL,
    from_location_id TEXT,
    to_location_id   TEXT,
    action           TEXT NOT NULL,
    notes            TEXT,
    audited_at       TEXT NOT NULL,
    user             TEXT,

    FOREIGN KEY (asset_id) REFERENCES Inventory(asset_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,
    FOREIGN KEY (from_location_id) REFERENCES Location(location_id),
    FOREIGN KEY (to_location_id) REFERENCES Location(location_id)
);
"""


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class DatabaseManager:
    """
    Wraps SQLite connection setup and schema initialization.
    """

    def __init__(self, config: AppConfig):
        self.db_path = Path(config.database.path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = self._create_connection()
        self.initialize_schema()
        logger.info("Database initialized at %s", self.db_path)

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._connection.cursor()
        try:
            yield cur
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            cur.close()

    def initialize_schema(self) -> None:
        with self._connection:
            self._connection.executescript(SCHEMA_SQL)

    def close(self) -> None:
        if self._connection:
            self._connection.close()
            logger.info("Database connection closed")
