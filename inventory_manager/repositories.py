import logging
import random
import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .db import iso_now

logger = logging.getLogger(__name__)


class GlobalIdRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def generate_global_id(self) -> str:
        while True:
            id_str = f"{random.randint(1, 99999999):08d}"
            try:
                self.conn.execute("INSERT INTO GlobalId (id) VALUES (?)", (id_str,))
                self.conn.commit()
                return id_str
            except sqlite3.IntegrityError:
                self.conn.rollback()
                continue


@dataclass
class Vehicle:
    vehicle_id: str
    vehicle_type: str
    vehicle_name: str
    vin: str
    vehicle_number: int
    mileage: int
    last_service: int
    created_at: str
    updated_at: str


class VehicleRepository:
    def __init__(self, conn: sqlite3.Connection, id_repo: GlobalIdRepository):
        self.conn = conn
        self.id_repo = id_repo

    def create_vehicle(
        self,
        vehicle_type: str,
        vehicle_name: str,
        vin: str,
        vehicle_number: int,
        mileage: int = 0,
        last_service: int = 0,
    ) -> Vehicle:
        now = iso_now()
        vehicle_id = self.id_repo.generate_global_id()
        self.conn.execute(
            """
            INSERT INTO Vehicle (
                vehicle_id, vehicle_type, vehicle_name, vin, vehicle_number,
                mileage, last_service, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle_id,
                vehicle_type,
                vehicle_name,
                vin,
                vehicle_number,
                mileage,
                last_service,
                now,
                now,
            ),
        )
        self.conn.commit()
        logger.info("Created vehicle %s (%s)", vehicle_name, vehicle_id)
        return Vehicle(
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            vehicle_name=vehicle_name,
            vin=vin,
            vehicle_number=vehicle_number,
            mileage=mileage,
            last_service=last_service,
            created_at=now,
            updated_at=now,
        )

    def list_vehicles(self) -> List[Vehicle]:
        rows = self.conn.execute(
            """
            SELECT vehicle_id, vehicle_type, vehicle_name, vin,
                   vehicle_number, mileage, last_service,
                   created_at, updated_at
            FROM Vehicle
            ORDER BY vehicle_name
            """
        ).fetchall()
        return [Vehicle(**dict(row)) for row in rows]

    def update_vehicle(
        self,
        vehicle_id: str,
        *,
        vehicle_type: Optional[str] = None,
        vehicle_name: Optional[str] = None,
        vin: Optional[str] = None,
        vehicle_number: Optional[int] = None,
        mileage: Optional[int] = None,
        last_service: Optional[int] = None,
    ) -> None:
        fields = []
        params = []
        mapping = {
            "vehicle_type": vehicle_type,
            "vehicle_name": vehicle_name,
            "vin": vin,
            "vehicle_number": vehicle_number,
            "mileage": mileage,
            "last_service": last_service,
        }
        for key, value in mapping.items():
            if value is not None:
                fields.append(f"{key} = ?")
                params.append(value)
        if not fields:
            return
        params.extend([iso_now(), vehicle_id])
        self.conn.execute(
            f"UPDATE Vehicle SET {', '.join(fields)}, updated_at = ? WHERE vehicle_id = ?",
            params,
        )
        self.conn.commit()

    def delete_vehicle(self, vehicle_id: str) -> None:
        self.conn.execute("DELETE FROM Vehicle WHERE vehicle_id = ?", (vehicle_id,))
        self.conn.commit()

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        row = self.conn.execute(
            """
            SELECT vehicle_id, vehicle_type, vehicle_name, vin,
                   vehicle_number, mileage, last_service,
                   created_at, updated_at
            FROM Vehicle WHERE vehicle_id = ?
            """,
            (vehicle_id,),
        ).fetchone()
        return Vehicle(**dict(row)) if row else None

    def overview_with_counts(self) -> List[dict]:
        rows = self.conn.execute(
            """
            SELECT v.vehicle_id, v.vehicle_name, v.vehicle_type, v.vin,
                   v.vehicle_number, v.mileage, v.last_service,
                   v.created_at, v.updated_at,
                   COALESCE(COUNT(inv.asset_id), 0) AS items_stored_count
            FROM Vehicle AS v
            LEFT JOIN Location AS loc ON loc.vehicle_id = v.vehicle_id
            LEFT JOIN Inventory AS inv ON inv.location_id = loc.location_id
            GROUP BY v.vehicle_id
            ORDER BY v.vehicle_name
            """
        ).fetchall()
        return [dict(row) for row in rows]


@dataclass
class Location:
    location_id: str
    vehicle_id: Optional[str]
    side: str
    row: int
    bin: int
    created_at: str
    updated_at: str
    last_audited_at: Optional[str]


class LocationRepository:
    def __init__(self, conn: sqlite3.Connection, id_repo: GlobalIdRepository):
        self.conn = conn
        self.id_repo = id_repo

    def create_location(
        self,
        side: str,
        row: int,
        bin: int,
        vehicle_id: Optional[str] = None,
    ) -> Location:
        now = iso_now()
        location_id = self.id_repo.generate_global_id()
        self.conn.execute(
            """
            INSERT INTO Location (
                location_id, vehicle_id, side, row, bin,
                created_at, updated_at, last_audited_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (location_id, vehicle_id, side, row, bin, now, now, None),
        )
        self.conn.commit()
        logger.info("Created location %s (vehicle %s)", location_id, vehicle_id or "N/A")
        return Location(
            location_id=location_id,
            vehicle_id=vehicle_id,
            side=side,
            row=row,
            bin=bin,
            created_at=now,
            updated_at=now,
            last_audited_at=None,
        )

    def list_locations(self, vehicle_id: Optional[str] = None) -> List[Location]:
        if vehicle_id:
            rows = self.conn.execute(
                """
                SELECT * FROM Location
                WHERE vehicle_id = ?
                ORDER BY side, row, bin
                """,
                (vehicle_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM Location ORDER BY vehicle_id, side, row, bin"
            ).fetchall()
        return [Location(**dict(row)) for row in rows]

    def get_location(self, location_id: str) -> Optional[Location]:
        row = self.conn.execute(
            "SELECT * FROM Location WHERE location_id = ?", (location_id,)
        ).fetchone()
        return Location(**dict(row)) if row else None

    def update_location(
        self,
        location_id: str,
        *,
        side: Optional[str] = None,
        row: Optional[int] = None,
        bin: Optional[int] = None,
        vehicle_id: Optional[str] = None,
        last_audited_at: Optional[str] = None,
    ) -> None:
        fields = []
        params = []
        mapping = {
            "side": side,
            "row": row,
            "bin": bin,
            "vehicle_id": vehicle_id,
            "last_audited_at": last_audited_at,
        }
        for key, value in mapping.items():
            if value is not None:
                fields.append(f"{key} = ?")
                params.append(value)
        if not fields:
            return
        params.extend([iso_now(), location_id])
        self.conn.execute(
            f"UPDATE Location SET {', '.join(fields)}, updated_at = ? WHERE location_id = ?",
            params,
        )
        self.conn.commit()

    def delete_location(self, location_id: str) -> None:
        self.conn.execute("DELETE FROM Location WHERE location_id = ?", (location_id,))
        self.conn.commit()


@dataclass
class InventoryItem:
    asset_id: str
    description: str
    location_id: str
    consumable: int
    manufacturer: Optional[str]
    model: Optional[str]
    serial_number: Optional[str]
    created_at: str
    updated_at: str


class InventoryRepository:
    def __init__(self, conn: sqlite3.Connection, id_repo: GlobalIdRepository):
        self.conn = conn
        self.id_repo = id_repo

    def create_inventory(
        self,
        description: str,
        location_id: str,
        consumable: bool = False,
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        serial_number: Optional[str] = None,
    ) -> InventoryItem:
        now = iso_now()
        asset_id = self.id_repo.generate_global_id()
        self.conn.execute(
            """
            INSERT INTO Inventory (
                asset_id, description, location_id, consumable,
                manufacturer, model, serial_number,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                description,
                location_id,
                1 if consumable else 0,
                manufacturer,
                model,
                serial_number,
                now,
                now,
            ),
        )
        self.conn.commit()
        logger.info("Created inventory item %s (%s)", description, asset_id)
        return InventoryItem(
            asset_id=asset_id,
            description=description,
            location_id=location_id,
            consumable=1 if consumable else 0,
            manufacturer=manufacturer,
            model=model,
            serial_number=serial_number,
            created_at=now,
            updated_at=now,
        )

    def update_inventory(
        self,
        asset_id: str,
        *,
        description: Optional[str] = None,
        location_id: Optional[str] = None,
        consumable: Optional[bool] = None,
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        serial_number: Optional[str] = None,
    ) -> None:
        fields = []
        params = []
        consumable_value: Optional[int]
        if consumable is True:
            consumable_value = 1
        elif consumable is False:
            consumable_value = 0
        else:
            consumable_value = None
        mapping = {
            "description": description,
            "location_id": location_id,
            "consumable": consumable_value,
            "manufacturer": manufacturer,
            "model": model,
            "serial_number": serial_number,
        }
        for key, value in mapping.items():
            if value is not None:
                fields.append(f"{key} = ?")
                params.append(value)
        if not fields:
            return
        params.extend([iso_now(), asset_id])
        self.conn.execute(
            f"UPDATE Inventory SET {', '.join(fields)}, updated_at = ? WHERE asset_id = ?",
            params,
        )
        self.conn.commit()

    def delete_inventory(self, asset_id: str) -> None:
        self.conn.execute("DELETE FROM Inventory WHERE asset_id = ?", (asset_id,))
        self.conn.commit()

    def list_inventory(self, location_id: Optional[str] = None) -> List[InventoryItem]:
        if location_id:
            rows = self.conn.execute(
                "SELECT * FROM Inventory WHERE location_id = ? ORDER BY description",
                (location_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM Inventory ORDER BY description"
            ).fetchall()
        return [InventoryItem(**dict(row)) for row in rows]

    def get_inventory(self, asset_id: str) -> Optional[InventoryItem]:
        row = self.conn.execute(
            "SELECT * FROM Inventory WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        return InventoryItem(**dict(row)) if row else None

    def list_inventory_filtered(
        self,
        search: str = "",
        limit: int = 500,
        offset: int = 0,
        order_by: str = "description",
        order_dir: str = "ASC",
    ) -> tuple[List[InventoryItem], int]:
        where = []
        params: list = []
        if search:
            like = f"%{search}%"
            where.append(
                "(asset_id LIKE ? OR description LIKE ? OR manufacturer LIKE ? OR model LIKE ? OR serial_number LIKE ? OR location_id LIKE ?)"
            )
            params.extend([like] * 6)
        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        order_dir_sql = "DESC" if order_dir.upper() == "DESC" else "ASC"
        order_col = order_by if order_by in {"description", "asset_id", "location_id"} else "description"
        count_sql = f"SELECT COUNT(*) FROM Inventory {where_clause}"
        total = self.conn.execute(count_sql, params).fetchone()[0]
        data_sql = f"""
            SELECT * FROM Inventory
            {where_clause}
            ORDER BY {order_col} {order_dir_sql}
            LIMIT ? OFFSET ?
        """
        rows = self.conn.execute(data_sql, params + [limit, offset]).fetchall()
        return [InventoryItem(**dict(row)) for row in rows], total

    def list_inventory_view(self) -> List[dict]:
        rows = self.conn.execute(
            """
            SELECT inv.asset_id, inv.location_id, inv.description, inv.consumable,
                   inv.manufacturer, inv.model, inv.serial_number,
                   veh.vehicle_name, veh.vehicle_type,
                   loc.side, loc.row, loc.bin, loc.last_audited_at
            FROM Inventory AS inv
            JOIN Location AS loc ON inv.location_id = loc.location_id
            LEFT JOIN Vehicle AS veh ON loc.vehicle_id = veh.vehicle_id
            ORDER BY inv.description
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_inventory_view_filtered(
        self,
        filters: dict,
        *,
        order_by: str = "description",
        order_dir: str = "ASC",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        columns = {
            "asset_id": "inv.asset_id",
            "location_id": "inv.location_id",
            "description": "inv.description",
            "consumable": "inv.consumable",
            "manufacturer": "inv.manufacturer",
            "model": "inv.model",
            "serial_number": "inv.serial_number",
            "vehicle_name": "veh.vehicle_name",
            "vehicle_type": "veh.vehicle_type",
            "side": "loc.side",
            "row": "loc.row",
            "bin": "loc.bin",
            "last_audited_at": "loc.last_audited_at",
        }
        where = []
        params: list = []
        global_term = filters.pop("global", None) or filters.pop("__global__", None)
        if global_term:
            like_value = f"%{global_term}%"
            where.append(
                "("
                "inv.asset_id LIKE ? OR inv.location_id LIKE ? OR inv.description LIKE ? OR "
                "inv.manufacturer LIKE ? OR inv.model LIKE ? OR inv.serial_number LIKE ? OR "
                "veh.vehicle_name LIKE ? OR veh.vehicle_type LIKE ? OR loc.side LIKE ?"
                ")"
            )
            params.extend([like_value] * 9)

        for key, value in filters.items():
            if not value:
                continue
            col = columns.get(key)
            if not col:
                continue
            if key in ("row", "bin"):
                where.append(f"{col} = ?")
                params.append(value)
            elif key == "consumable":
                where.append(f"{col} = ?")
                params.append(1 if str(value).lower() == "yes" else 0)
            else:
                where.append(f"{col} LIKE ?")
                params.append(f"%{value}%")
        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        order_col = columns.get(order_by, "inv.description")
        order_dir_sql = "DESC" if order_dir.upper() == "DESC" else "ASC"

        count_sql = f"""
            SELECT COUNT(*) FROM Inventory AS inv
            JOIN Location AS loc ON inv.location_id = loc.location_id
            LEFT JOIN Vehicle AS veh ON loc.vehicle_id = veh.vehicle_id
            {where_clause}
        """
        total = self.conn.execute(count_sql, params).fetchone()[0]

        data_sql = f"""
            SELECT inv.asset_id, inv.location_id, inv.description, inv.consumable,
                   inv.manufacturer, inv.model, inv.serial_number,
                   veh.vehicle_name, veh.vehicle_type,
                   loc.side, loc.row, loc.bin, loc.last_audited_at
            FROM Inventory AS inv
            JOIN Location AS loc ON inv.location_id = loc.location_id
            LEFT JOIN Vehicle AS veh ON loc.vehicle_id = veh.vehicle_id
            {where_clause}
            ORDER BY {order_col} {order_dir_sql}
            LIMIT ? OFFSET ?
        """
        rows = self.conn.execute(data_sql, params + [limit, offset]).fetchall()
        return [dict(row) for row in rows], total


class AuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record_audit(
        self,
        asset_id: str,
        action: str,
        *,
        from_location_id: Optional[str] = None,
        to_location_id: Optional[str] = None,
        notes: Optional[str] = None,
        user: Optional[str] = None,
        audited_at: Optional[str] = None,
    ) -> int:
        timestamp = audited_at or iso_now()
        cursor = self.conn.execute(
            """
            INSERT INTO InventoryAudit (
                asset_id, from_location_id, to_location_id,
                action, notes, audited_at, user
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (asset_id, from_location_id, to_location_id, action, notes, timestamp, user),
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_audits_for_asset(self, asset_id: str) -> Sequence[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT audit_id, asset_id, from_location_id, to_location_id,
                   action, notes, audited_at, user
            FROM InventoryAudit
            WHERE asset_id = ?
            ORDER BY audit_id DESC
            """,
            (asset_id,),
        ).fetchall()
