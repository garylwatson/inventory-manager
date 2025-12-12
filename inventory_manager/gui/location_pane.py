import logging
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Optional

import barcode
from barcode.writer import ImageWriter
from PyQt6 import QtCore, QtGui, QtWidgets

from ..repositories import GlobalIdRepository, Location, LocationRepository, VehicleRepository
from .models import DictTableModel

logger = logging.getLogger(__name__)


def install_copy_shortcut(view: QtWidgets.QTableView) -> None:
    def copy():
        indexes = view.selectionModel().selectedIndexes()
        if not indexes:
            return
        indexes = sorted(indexes, key=lambda i: (i.row(), i.column()))
        rows = {}
        for idx in indexes:
            rows.setdefault(idx.row(), {})[idx.column()] = idx.data() or ""
        lines = []
        for row in sorted(rows):
            cols = rows[row]
            lines.append("\t".join(cols.get(c, "") for c in range(max(cols) + 1)))
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    shortcut = QtGui.QShortcut(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Copy), view)
    shortcut.activated.connect(copy)


class LocationPane(QtWidgets.QWidget):
    def __init__(
        self,
        location_repo: LocationRepository,
        vehicle_repo: VehicleRepository,
        id_repo: GlobalIdRepository,
        save_dir: Path,
    ):
        super().__init__()
        self.location_repo = location_repo
        self.vehicle_repo = vehicle_repo
        self.id_repo = id_repo
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.current_location_id: Optional[str] = None
        self._barcode_image = None
        self._qr_image = None
        self._label_dpi = 300
        self._label_font_size = 11
        self._default_module_width = 0.15
        self._default_module_height = 8
        self._default_quiet_zone = 1.5
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self.table_model = DictTableModel(
            headers=["location_id", "vehicle_id", "side", "row", "bin", "last_audited_at"]
        )
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search any column")
        self.search_input.textChanged.connect(self._filter_rows)

        self.table = QtWidgets.QTableView()
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        install_copy_shortcut(self.table)

        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        top_controls = QtWidgets.QHBoxLayout()
        top_controls.addWidget(QtWidgets.QLabel("Search:"))
        top_controls.addWidget(self.search_input)
        self.toggle_details_btn = QtWidgets.QPushButton("Hide Details")
        self.toggle_details_btn.setCheckable(True)
        self.toggle_details_btn.toggled.connect(lambda checked: self._toggle_details(checked, splitter))
        self.new_btn = QtWidgets.QPushButton("New Location")
        self.new_btn.clicked.connect(self._clear_form)
        top_controls.addWidget(self.toggle_details_btn)
        top_controls.addWidget(self.new_btn)
        left_layout.addLayout(top_controls)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)

        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QFormLayout(form_widget)
        self.location_id_label = QtWidgets.QLabel("-")
        self.vehicle_id_input = QtWidgets.QLineEdit()
        self.side_input = QtWidgets.QLineEdit()
        self.row_input = QtWidgets.QSpinBox()
        self.row_input.setRange(0, 9999)
        self.bin_input = QtWidgets.QSpinBox()
        self.bin_input.setRange(0, 9999)
        self.last_audited_label = QtWidgets.QLabel("-")

        form_layout.addRow("Location ID:", self.location_id_label)
        form_layout.addRow("Vehicle ID (optional):", self.vehicle_id_input)
        form_layout.addRow("Side:", self.side_input)
        form_layout.addRow("Row:", self.row_input)
        form_layout.addRow("Bin:", self.bin_input)
        form_layout.addRow("Last audited:", self.last_audited_label)

        button_row = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.delete_btn)
        button_row.addWidget(self.refresh_btn)
        form_layout.addRow(button_row)

        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        self.refresh_btn.clicked.connect(self.refresh_table)

        # Minimal label controls for locations
        export_row = QtWidgets.QHBoxLayout()
        self.barcode_format_combo = QtWidgets.QComboBox()
        self.barcode_format_combo.addItems(["PNG", "SVG", "EPS"])
        self.qr_format_combo = QtWidgets.QComboBox()
        self.qr_format_combo.addItems(["PNG", "EPS"])
        self.save_barcode_btn = QtWidgets.QPushButton("Save Barcode")
        self.save_qr_btn = QtWidgets.QPushButton("Save QR")
        export_row.addWidget(QtWidgets.QLabel("Barcode format"))
        export_row.addWidget(self.barcode_format_combo)
        export_row.addWidget(self.save_barcode_btn)
        export_row.addWidget(QtWidgets.QLabel("QR format"))
        export_row.addWidget(self.qr_format_combo)
        export_row.addWidget(self.save_qr_btn)
        form_layout.addRow(export_row)
        self.save_barcode_btn.clicked.connect(lambda: self._save_image("barcode"))
        self.save_qr_btn.clicked.connect(lambda: self._save_image("qr"))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        self.detail_panel = scroll
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    def refresh_table(self) -> None:
        rows = [asdict(loc) for loc in self.location_repo.list_locations()]
        self.table_model.set_rows(rows)
        self._filter_rows()

    def _filter_rows(self) -> None:
        term = self.search_input.text().strip().lower()
        if not term:
            self.table_model.set_rows(self.table_model._rows)  # type: ignore[attr-defined]
            return
        filtered = [
            row for row in self.table_model._rows  # type: ignore[attr-defined]
            if term in str(row.get("location_id", "")).lower()
            or term in str(row.get("vehicle_id", "")).lower()
            or term in str(row.get("side", "")).lower()
        ]
        self.table_model.set_rows(filtered)

    def _clear_form(self) -> None:
        self.current_location_id = None
        self.location_id_label.setText("-")
        self.vehicle_id_input.clear()
        self.side_input.clear()
        self.row_input.setValue(0)
        self.bin_input.setValue(0)
        self.last_audited_label.setText("-")

    def _on_selection(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return
        row = self.table_model._rows[indexes[0].row()]  # type: ignore[attr-defined]
        self.current_location_id = row.get("location_id")
        self.location_id_label.setText(row.get("location_id", "-"))
        self.vehicle_id_input.setText(row.get("vehicle_id") or "")
        self.side_input.setText(row.get("side") or "")
        self.row_input.setValue(int(row.get("row", 0) or 0))
        self.bin_input.setValue(int(row.get("bin", 0) or 0))
        self.last_audited_label.setText(row.get("last_audited_at") or "-")

    def _save(self) -> None:
        side = self.side_input.text().strip()
        if not side:
            QtWidgets.QMessageBox.warning(self, "Missing data", "Side is required.")
            return
        try:
            if self.current_location_id:
                self.location_repo.update_location(
                    self.current_location_id,
                    side=side,
                    row=self.row_input.value(),
                    bin=self.bin_input.value(),
                    vehicle_id=self.vehicle_id_input.text().strip() or None,
                )
            else:
                loc = self.location_repo.create_location(
                    side=side,
                    row=self.row_input.value(),
                    bin=self.bin_input.value(),
                    vehicle_id=self.vehicle_id_input.text().strip() or None,
                )
                self.current_location_id = loc.location_id
                self.location_id_label.setText(loc.location_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unable to save location: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Error", str(exc))
            return
        self.refresh_table()

    def _delete(self) -> None:
        if not self.current_location_id:
            return
        resp = QtWidgets.QMessageBox.question(
            self,
            "Delete location",
            f"Delete location {self.current_location_id}?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if resp != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.location_repo.delete_location(self.current_location_id)
            self._clear_form()
            self.refresh_table()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unable to delete location: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Error", str(exc))

    def _toggle_details(self, hide: bool, splitter: QtWidgets.QSplitter) -> None:
        self.detail_panel.setVisible(not hide)
        self.toggle_details_btn.setText("Show Details" if hide else "Hide Details")
        if hide:
            splitter.setSizes([1, 0])
        else:
            splitter.setSizes([2, 1])

    def _save_image(self, kind: str) -> None:
        if kind == "barcode":
            image = self._barcode_image
            title = "Save Barcode"
            fmt = self.barcode_format_combo.currentText().lower()
        else:
            image = self._qr_image
            title = "Save QR Code"
            fmt = self.qr_format_combo.currentText().lower()
        if image is None:
            QtWidgets.QMessageBox.information(
                self, "No image", f"No {kind} to save yet."
            )
            return
        base_label = self.location_id_label.text() or "location"
        default_name = f"{base_label}_{fmt}"
        default_path = str(self.save_dir / default_name)
        filters = {
            "barcode": ";;".join(
                ["PNG (*.png)", "SVG (*.svg)", "EPS (*.eps)", "All Files (*)"]
            ),
            "qr": ";;".join(["PNG (*.png)", "EPS (*.eps)", "All Files (*)"]),
        }
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, title, default_path, filters["barcode" if kind == "barcode" else "qr"]
        )
        if not path:
            return
        ext = Path(path).suffix.lower() or f".{fmt}"
        if not path.endswith(ext):
            path = f"{path}{ext}"
        try:
            if kind == "barcode" and ext == ".svg":
                from barcode.writer import SVGWriter

                code39_cls = barcode.get_barcode_class("code39")
                code39 = code39_cls(base_label, writer=SVGWriter(), add_checksum=False)
                code39.save(path, options=self._barcode_writer_options())
            else:
                fmt_param = "PNG"
                if ext == ".eps":
                    fmt_param = "EPS"
                image.save(path, format=fmt_param, dpi=(self._label_dpi, self._label_dpi))
        except Exception as exc:  # pylint: disable=broad-except
            QtWidgets.QMessageBox.warning(self, "Save failed", str(exc))
        else:
            QtWidgets.QMessageBox.information(
                self, "Saved", f"{kind.capitalize()} saved to {path}"
            )

    def _barcode_writer_options(self) -> dict:
        return {
            "quiet_zone": float(self._default_quiet_zone),
            "module_height": int(self._default_module_height),
            "module_width": float(self._default_module_width),
            "write_text": True,
            "dpi": int(self._label_dpi),
        }
