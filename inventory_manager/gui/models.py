from typing import Any, Dict, List, Sequence

from PyQt6 import QtCore, QtGui


class DictTableModel(QtCore.QAbstractTableModel):
    def __init__(self, headers: Sequence[str], rows: List[Dict[str, Any]] | None = None):
        super().__init__()
        self.headers = list(headers)
        self._rows: List[Dict[str, Any]] = rows or []

    def rowCount(self, parent: QtCore.QModelIndex | None = None) -> int:  # noqa: N802
        return len(self._rows)

    def columnCount(self, parent: QtCore.QModelIndex | None = None) -> int:  # noqa: N802
        return len(self.headers)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = self.headers[index.column()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return str(row.get(key, ""))
        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ):
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == QtCore.Qt.Orientation.Horizontal:
            return self.headers[section]
        return section + 1

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        return (
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
        )

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class VehicleTableModel(DictTableModel):
    def __init__(self):
        headers = [
            "vehicle_id",
            "vehicle_name",
            "vehicle_type",
            "vin",
            "vehicle_number",
            "mileage",
            "last_service",
        ]
        super().__init__(headers=headers)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        value = super().data(index, role)
        if role == QtCore.Qt.ItemDataRole.BackgroundRole and index.isValid():
            mileage = int(self._rows[index.row()].get("mileage", 0) or 0)
            last_service = int(self._rows[index.row()].get("last_service", 0) or 0)
            delta = mileage - last_service
            if delta > 5000:
                return QtGui.QColor("#ffcccc")
            if 4900 <= delta <= 5000:
                return QtGui.QColor("#fff4cc")
            return QtGui.QColor("#e8ffed")
        return value


class InventoryTableModel(DictTableModel):
    def __init__(self):
        headers = [
            "asset_id",
            "description",
            "location_id",
            "consumable",
            "manufacturer",
            "model",
            "serial_number",
        ]
        super().__init__(headers=headers)
