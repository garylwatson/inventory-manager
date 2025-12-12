import sys
from pathlib import Path

from PyQt6 import QtWidgets

from .backup import BackupManager
from .config import load_config
from .db import DatabaseManager
from .gui.main_window import MainWindow
from .repositories import (
    AuditRepository,
    GlobalIdRepository,
    InventoryRepository,
    LocationRepository,
    VehicleRepository,
)


def main(config_path: Path = Path("config.yaml")) -> int:
    config = load_config(config_path)
    db = DatabaseManager(config)
    id_repo = GlobalIdRepository(db.connection)
    vehicle_repo = VehicleRepository(db.connection, id_repo)
    location_repo = LocationRepository(db.connection, id_repo)
    inventory_repo = InventoryRepository(db.connection, id_repo)
    audit_repo = AuditRepository(db.connection)

    app = QtWidgets.QApplication(sys.argv)
    backup_manager = BackupManager(Path(config.database.path), config.backup)
    window = MainWindow(
        config,
        vehicle_repo=vehicle_repo,
        location_repo=location_repo,
        inventory_repo=inventory_repo,
        audit_repo=audit_repo,
        id_repo=id_repo,
        backup_manager=backup_manager,
    )
    window.show()
    backup_manager.start()
    exit_code = app.exec()
    db.close()
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
