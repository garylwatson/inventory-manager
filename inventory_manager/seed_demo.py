"""
Seed the SQLite database with dummy data for testing the Inventory Manager UI.

Usage:
    python -m inventory_manager.seed_demo --items 500
"""

import argparse
import random
from pathlib import Path

from .config import load_config
from .db import DatabaseManager
from .repositories import (
    GlobalIdRepository,
    InventoryRepository,
    LocationRepository,
    VehicleRepository,
)


def _ensure_vehicle(repo: VehicleRepository, *, vehicle_number: int, **kwargs):
    existing = next(
        (v for v in repo.list_vehicles() if v.vehicle_number == vehicle_number), None
    )
    return existing or repo.create_vehicle(vehicle_number=vehicle_number, **kwargs)


def _ensure_location(
    repo: LocationRepository,
    *,
    vehicle_id: str | None,
    side: str,
    row: int,
    bin: int,
):
    for loc in repo.list_locations(vehicle_id=vehicle_id):
        if (
            loc.vehicle_id == vehicle_id
            and loc.side == side
            and loc.row == row
            and loc.bin == bin
        ):
            return loc
    return repo.create_location(
        vehicle_id=vehicle_id, side=side, row=row, bin=bin
    )


def _ensure_inventory(
    repo: InventoryRepository,
    *,
    description: str,
    location_id: str,
    serial_number: str | None = None,
    **kwargs,
):
    existing = next(
        (
            item
            for item in repo.list_inventory(location_id=location_id)
            if item.description == description
            and item.serial_number == serial_number
        ),
        None,
    )
    return existing or repo.create_inventory(
        description=description,
        location_id=location_id,
        serial_number=serial_number,
        **kwargs,
    )


def seed_demo(config_path: Path = Path("config.yaml"), items: int = 50) -> None:
    config = load_config(config_path)
    db = DatabaseManager(config)
    id_repo = GlobalIdRepository(db.connection)
    vehicle_repo = VehicleRepository(db.connection, id_repo)
    location_repo = LocationRepository(db.connection, id_repo)
    inventory_repo = InventoryRepository(db.connection, id_repo)

    # Vehicles
    truck = _ensure_vehicle(
        vehicle_repo,
        vehicle_number=101,
        vehicle_type="Truck",
        vehicle_name="Truck T-100",
        vin="VINTRUCK123",
        mileage=12500,
        last_service=7800,
    )
    trailer = _ensure_vehicle(
        vehicle_repo,
        vehicle_number=201,
        vehicle_type="Trailer",
        vehicle_name="Trailer TR-200",
        vin="VINTRAILER456",
        mileage=4200,
        last_service=1500,
    )

    # Locations
    truck_left_1 = _ensure_location(
        location_repo, vehicle_id=truck.vehicle_id, side="Left", row=1, bin=1
    )
    truck_right_1 = _ensure_location(
        location_repo, vehicle_id=truck.vehicle_id, side="Right", row=1, bin=1
    )
    truck_left_2 = _ensure_location(
        location_repo, vehicle_id=truck.vehicle_id, side="Left", row=2, bin=2
    )
    trailer_front_1 = _ensure_location(
        location_repo, vehicle_id=trailer.vehicle_id, side="Front", row=1, bin=1
    )

    # Inventory
    _ensure_inventory(
        inventory_repo,
        description="Impact Wrench",
        manufacturer="Makita",
        model="XWT08Z",
        serial_number="IMPACT-001",
        location_id=truck_left_1.location_id,
        consumable=False,
    )
    _ensure_inventory(
        inventory_repo,
        description="Oil Filter",
        manufacturer="WIX",
        model="51348",
        serial_number=None,
        location_id=truck_right_1.location_id,
        consumable=True,
    )
    _ensure_inventory(
        inventory_repo,
        description="Hydraulic Jack",
        manufacturer="Torin",
        model="T83006",
        serial_number="JACK-099",
        location_id=truck_left_2.location_id,
        consumable=False,
    )
    _ensure_inventory(
        inventory_repo,
        description="Spare Tire",
        manufacturer="Goodyear",
        model="Wrangler",
        serial_number="TIRE-SPARE-01",
        location_id=trailer_front_1.location_id,
        consumable=False,
    )
    _ensure_inventory(
        inventory_repo,
        description="Ratchet Straps (Pack of 4)",
        manufacturer="Erickson",
        model="34410",
        serial_number=None,
        location_id=trailer_front_1.location_id,
        consumable=True,
    )

    # Bulk inventory for load testing
    _bulk_inventory(inventory_repo, [truck, trailer], location_repo, count=items)

    print(f"Demo data inserted (approx {items} inventory rows).")
    db.close()


def _bulk_inventory(
    inventory_repo: InventoryRepository,
    vehicles,
    location_repo: LocationRepository,
    *,
    count: int,
) -> None:
    descriptions = [
        "Impact Wrench",
        "Socket Set",
        "Torque Wrench",
        "Hydraulic Jack",
        "Pliers",
        "Hammer Drill",
        "Safety Glasses",
        "Hi-Vis Vest",
        "Work Gloves",
        "Oil Filter",
        "Air Filter",
        "Brake Pads",
        "Ratchet Straps",
        "Spare Tire",
        "Grease Gun",
        "Seal Kit",
        "Hydraulic Hose",
        "Ball Hitch",
        "Wheel Chock",
        "LED Work Light",
    ]
    manufacturers = ["Makita", "DeWalt", "Milwaukee", "Bosch", "WIX", "Goodyear", "Torin"]
    models = ["XWT08Z", "DCD999", "M18", "GSR18V", "51348", "Wrangler", "T83006"]

    # Ensure a handful of locations for each vehicle
    vehicle_locations = []
    for vehicle in vehicles:
        locs = location_repo.list_locations(vehicle_id=vehicle.vehicle_id)
        if len(locs) < 6:
            for side in ["Left", "Right", "Front", "Rear"]:
                for row in range(1, 3):
                    locs.append(
                        _ensure_location(
                            location_repo,
                            vehicle_id=vehicle.vehicle_id,
                            side=side,
                            row=row,
                            bin=row,
                        )
                    )
        vehicle_locations.extend(locs)

    for i in range(count):
        desc = random.choice(descriptions)
        manufacturer = random.choice(manufacturers)
        model = random.choice(models)
        serial = f"{desc[:3].upper()}-{i:05d}"
        location = random.choice(vehicle_locations)
        consumable = bool(random.getrandbits(1))
        _ensure_inventory(
            inventory_repo,
            description=desc,
            manufacturer=manufacturer,
            model=model,
            serial_number=serial,
            location_id=location.location_id,
            consumable=consumable,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed inventory demo data.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument(
        "--items", type=int, default=200, help="Number of inventory rows to seed."
    )
    args = parser.parse_args()
    seed_demo(config_path=args.config, items=args.items)
