import logging
from datetime import datetime
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Optional

import barcode
from barcode.writer import ImageWriter
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QSettings

from ..backup import BackupManager
from ..config import AppConfig
from ..repositories import (
    AuditRepository,
    GlobalIdRepository,
    InventoryItem,
    InventoryRepository,
    LocationRepository,
    Vehicle,
    VehicleRepository,
)
from .location_pane import LocationPane
from .models import DictTableModel, InventoryTableModel, VehicleTableModel

logger = logging.getLogger(__name__)


def install_copy_shortcut(view: QtWidgets.QTableView) -> None:
    """
    Enable Ctrl/Cmd+C to copy selected cells as tab-separated text.
    """
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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        config: AppConfig,
        vehicle_repo: VehicleRepository,
        location_repo: LocationRepository,
        inventory_repo: InventoryRepository,
        audit_repo: AuditRepository,
        id_repo: GlobalIdRepository,
        backup_manager: BackupManager,
    ):
        super().__init__()
        self.config = config
        self.vehicle_repo = vehicle_repo
        self.location_repo = location_repo
        self.inventory_repo = inventory_repo
        self.audit_repo = audit_repo
        self.id_repo = id_repo
        self.backup_manager = backup_manager
        self.last_backup_path: Optional[str] = None
        self.settings = QSettings("inventory_manager", "app")

        self.setWindowTitle("Inventory Manager")
        self.resize(1200, 800)
        self._restore_geometry()
        self._build_menu()
        self._build_tabs()
        self._connect_backup_signals()
        self._init_status()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        exit_action = QtGui.QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = self.menuBar().addMenu("&Tools")
        backup_action = QtGui.QAction("Manual Backup Now", self)
        backup_action.triggered.connect(self.backup_manager.manual_backup)
        tools_menu.addAction(backup_action)
        export_action = QtGui.QAction("Export Data (CSV)", self)
        export_action.triggered.connect(self._export_placeholder)
        tools_menu.addAction(export_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QtGui.QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_tabs(self) -> None:
        self.tabs = QtWidgets.QTabWidget()
        self.manage_tab = ManageTab(
            self.vehicle_repo,
            self.location_repo,
            self.inventory_repo,
            self.id_repo,
            save_dir=Path(self.config.backup.directory) / "labels",
        )
        exports_dir = Path(self.config.backup.directory) / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        self.view_tab = ViewTab(self.inventory_repo, exports_dir)
        self.audit_tab = AuditTab(
            self.location_repo, self.inventory_repo, self.audit_repo
        )

        self.tabs.addTab(self.manage_tab, "Manage")
        self.tabs.addTab(self.view_tab, "View")
        self.tabs.addTab(self.audit_tab, "Audit")
        self.setCentralWidget(self.tabs)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        super().closeEvent(event)

    def _restore_geometry(self) -> None:
        geom = self.settings.value("window/geometry")
        state = self.settings.value("window/state")
        if geom:
            self.restoreGeometry(geom)
        if state:
            self.restoreState(state)

    def _connect_backup_signals(self) -> None:
        self.backup_manager.backup_started.connect(
            lambda: self.statusBar().showMessage("Backup in progress...")
        )
        self.backup_manager.backup_finished.connect(self._on_backup_finished)
        self.backup_manager.backup_failed.connect(self._on_backup_failed)

    def _init_status(self) -> None:
        self.statusBar().showMessage(f"DB: {self.config.database.path}")

    def _on_backup_finished(self, path: str) -> None:
        self.last_backup_path = path
        self.statusBar().showMessage(f"Last backup: {Path(path).name}")

    def _on_backup_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"Backup failed: {message}")
        QtWidgets.QMessageBox.warning(self, "Backup failed", message)

    def _export_placeholder(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Export",
            "Export to CSV is not implemented yet. Use the View tab to filter and export.",
        )

    def _show_about(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About Inventory Manager",
            "Inventory Manager\n\nPyQt-based desktop app with SQLite backend and scheduled backups.",
        )


class ManageTab(QtWidgets.QWidget):
    def __init__(
        self,
        vehicle_repo: VehicleRepository,
        location_repo: LocationRepository,
        inventory_repo: InventoryRepository,
        id_repo: GlobalIdRepository,
        save_dir: Path,
    ):
        super().__init__()
        # Shared base paths for label exports to keep persistence outside the container.
        label_root = Path(save_dir) / "labels"
        self.asset_label_dir = label_root / "assets"
        self.vehicle_label_dir = label_root / "vehicles"
        self.location_label_dir = label_root / "locations"
        for d in [self.asset_label_dir, self.vehicle_label_dir, self.location_label_dir]:
            d.mkdir(parents=True, exist_ok=True)
        layout = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(
            InventoryPane(inventory_repo, location_repo, vehicle_repo, id_repo, self.asset_label_dir),
            "Inventory",
        )
        tabs.addTab(VehiclePane(vehicle_repo, self.vehicle_label_dir), "Vehicles")
        tabs.addTab(LocationPane(location_repo, vehicle_repo, id_repo, self.location_label_dir), "Locations")
        layout.addWidget(tabs)


class InventoryPane(QtWidgets.QWidget):
    def __init__(
        self,
        inventory_repo: InventoryRepository,
        location_repo: LocationRepository,
        vehicle_repo: VehicleRepository,
        id_repo: GlobalIdRepository,
        save_dir: Path,
    ):
        super().__init__()
        self.inventory_repo = inventory_repo
        self.location_repo = location_repo
        self.vehicle_repo = vehicle_repo
        self.id_repo = id_repo
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.current_asset_id: Optional[str] = None
        self._barcode_pixmap: Optional[QtGui.QPixmap] = None
        self._qr_pixmap: Optional[QtGui.QPixmap] = None
        self._barcode_image = None
        self._qr_image = None
        self._label_font_size = 11
        self._label_dpi = 300
        self._default_module_width = 0.15
        self._default_module_height = 8
        self._default_quiet_zone = 1.5
        self._completers: list[QtWidgets.QCompleter] = []
        self._dirty = False
        self._last_selection: Optional[QtCore.QModelIndex] = None
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # Table on the left
        self.table_model = InventoryTableModel()
        self.table_proxy = QtCore.QSortFilterProxyModel()
        self.table_proxy.setSourceModel(self.table_model)
        self.table_proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.table_proxy.setFilterKeyColumn(-1)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search any column")
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_table)
        self.search_input.textChanged.connect(lambda _: self.search_timer.start())
        self.search_input.textEdited.connect(lambda _: self._mark_dirty())

        self.table = QtWidgets.QTableView()
        self.table.setModel(self.table_proxy)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.table.setToolTip("Inventory list. Select an item to edit and render labels.")
        install_copy_shortcut(self.table)

        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        top_controls = QtWidgets.QHBoxLayout()
        top_controls.addWidget(QtWidgets.QLabel("Search:"))
        top_controls.addWidget(self.search_input)
        self.toggle_details_btn = QtWidgets.QPushButton("Hide Details")
        self.toggle_details_btn.setCheckable(True)
        self.toggle_details_btn.toggled.connect(lambda checked: self._toggle_details(checked, splitter))
        self.new_btn = QtWidgets.QPushButton("New Item")
        self.new_btn.setToolTip("Create a new inventory item with a new ID")
        self.new_btn.clicked.connect(self._clear_form)
        top_controls.addWidget(self.toggle_details_btn)
        top_controls.addWidget(self.new_btn)
        left_layout.addLayout(top_controls)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)

        # Form on the right
        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QFormLayout(form_widget)

        self.asset_id_label = QtWidgets.QLabel("-")
        self.description_input = QtWidgets.QLineEdit()
        self.manufacturer_input = QtWidgets.QLineEdit()
        self.model_input = QtWidgets.QLineEdit()
        self.serial_input = QtWidgets.QLineEdit()
        self.location_input = QtWidgets.QLineEdit()
        self.consumable_checkbox = QtWidgets.QCheckBox("Consumable")
        self.created_label = QtWidgets.QLabel("-")
        self.updated_label = QtWidgets.QLabel("-")
        for widget in [
            self.description_input,
            self.manufacturer_input,
            self.model_input,
            self.serial_input,
            self.location_input,
        ]:
            widget.textEdited.connect(self._mark_dirty)
        self.consumable_checkbox.toggled.connect(self._mark_dirty)

        form_layout.addRow("Asset ID:", self.asset_id_label)
        form_layout.addRow("Description:", self.description_input)
        form_layout.addRow("Manufacturer:", self.manufacturer_input)
        form_layout.addRow("Model:", self.model_input)
        form_layout.addRow("Serial Number:", self.serial_input)
        form_layout.addRow("Location ID:", self.location_input)
        form_layout.addRow("", self.consumable_checkbox)
        form_layout.addRow("Created:", self.created_label)
        form_layout.addRow("Updated:", self.updated_label)

        button_row = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.delete_btn)
        button_row.addWidget(self.refresh_btn)
        form_layout.addRow(button_row)
        self.save_btn.setToolTip("Save current item (insert or update)")
        self.delete_btn.setToolTip("Delete current item")
        self.refresh_btn.setToolTip("Reload inventory list from the database")

        # Barcode / QR display controls
        toggles_row = QtWidgets.QHBoxLayout()
        self.include_id_cb = QtWidgets.QCheckBox("Include ID")
        self.include_id_cb.setChecked(True)
        self.include_id_cb.setToolTip("Include the asset ID as the first label line")
        self.include_desc_cb = QtWidgets.QCheckBox("Include description")
        self.include_desc_cb.setChecked(True)
        self.include_desc_cb.setToolTip("Include the description text on the label")
        self.include_location_cb = QtWidgets.QCheckBox("Include location")
        self.include_location_cb.setChecked(True)
        self.include_location_cb.setToolTip("Include vehicle/side/Row/Bin on the label")
        self.font_size_spin = QtWidgets.QSpinBox()
        self.font_size_spin.setRange(8, 32)
        self.font_size_spin.setValue(self._label_font_size)
        self.layout_combo = QtWidgets.QComboBox()
        self.layout_combo.addItems(["Below code", "Right of code"])
        self.show_text_cb = QtWidgets.QCheckBox("Show barcode text")
        self.show_text_cb.setChecked(True)
        self.show_text_cb.setToolTip("Toggle human-readable text under the barcode")
        self.text_font_size_spin = QtWidgets.QSpinBox()
        self.text_font_size_spin.setRange(6, 24)
        self.text_font_size_spin.setValue(10)
        self.text_font_size_spin.setToolTip("Font size for barcode text (PNG/EPS)")
        toggles_row.addWidget(self.include_id_cb)
        toggles_row.addWidget(self.include_desc_cb)
        toggles_row.addWidget(self.include_location_cb)
        toggles_row.addWidget(QtWidgets.QLabel("Font size"))
        toggles_row.addWidget(self.font_size_spin)
        toggles_row.addWidget(QtWidgets.QLabel("Layout"))
        toggles_row.addWidget(self.layout_combo)
        toggles_row.addWidget(self.show_text_cb)
        toggles_row.addWidget(QtWidgets.QLabel("Barcode text size"))
        toggles_row.addWidget(self.text_font_size_spin)
        form_layout.addRow("Label options:", toggles_row)

        # Code customization controls
        self.custom_code_input = QtWidgets.QLineEdit()
        self.custom_code_input.setPlaceholderText("Defaults to asset ID if blank")
        self.custom_code_input.setToolTip("Override code content; leave blank to use asset ID")
        form_layout.addRow("Barcode/QR data:", self.custom_code_input)

        self.custom_label_text = QtWidgets.QPlainTextEdit()
        self.custom_label_text.setPlaceholderText("Additional label lines (one per line)")
        self.custom_label_text.setFixedHeight(70)
        self.custom_label_text.setToolTip("Freeform lines appended to the label")
        form_layout.addRow("Custom label lines:", self.custom_label_text)

        options_row = QtWidgets.QHBoxLayout()
        self.module_width_spin = QtWidgets.QDoubleSpinBox()
        self.module_width_spin.setRange(0.05, 1.0)
        self.module_width_spin.setSingleStep(0.05)
        self.module_width_spin.setValue(self._default_module_width)
        self.module_width_spin.setToolTip("Barcode module width (mm). Smaller for compact labels.")
        self.module_height_spin = QtWidgets.QSpinBox()
        self.module_height_spin.setRange(5, 80)
        self.module_height_spin.setValue(self._default_module_height)
        self.module_height_spin.setToolTip("Barcode module height (px). Lower for compact labels.")
        self.quiet_zone_spin = QtWidgets.QDoubleSpinBox()
        self.quiet_zone_spin.setRange(0.0, 20.0)
        self.quiet_zone_spin.setSingleStep(0.5)
        self.quiet_zone_spin.setValue(self._default_quiet_zone)
        self.quiet_zone_spin.setToolTip("Quiet zone padding around the barcode (mm)")
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(self._label_dpi)
        self.dpi_spin.setToolTip("Raster export DPI. 300 is a good default for Brother P-Touch.")
        options_row.addWidget(QtWidgets.QLabel("Module width"))
        options_row.addWidget(self.module_width_spin)
        options_row.addWidget(QtWidgets.QLabel("Module height"))
        options_row.addWidget(self.module_height_spin)
        options_row.addWidget(QtWidgets.QLabel("Quiet zone"))
        options_row.addWidget(self.quiet_zone_spin)
        options_row.addWidget(QtWidgets.QLabel("DPI"))
        options_row.addWidget(self.dpi_spin)
        form_layout.addRow("Barcode tuning:", options_row)

        previews = QtWidgets.QHBoxLayout()
        self.barcode_label = QtWidgets.QLabel("Barcode preview")
        self.barcode_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.barcode_label.setMinimumHeight(160)
        self.barcode_label.setStyleSheet("border: 1px solid #ccc; padding: 4px;")
        self.qr_label = QtWidgets.QLabel("QR code preview")
        self.qr_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(160)
        self.qr_label.setStyleSheet("border: 1px solid #ccc; padding: 4px;")
        previews.addWidget(self.barcode_label)
        previews.addWidget(self.qr_label)
        form_layout.addRow(previews)

        export_row = QtWidgets.QHBoxLayout()
        self.barcode_format_combo = QtWidgets.QComboBox()
        self.barcode_format_combo.addItems(["PNG", "SVG", "EPS"])
        self.barcode_format_combo.setToolTip("Select barcode export format")
        self.qr_format_combo = QtWidgets.QComboBox()
        self.qr_format_combo.addItems(["PNG", "EPS"])
        self.qr_format_combo.setToolTip("Select QR export format")
        self.save_barcode_btn = QtWidgets.QPushButton("Save Barcode")
        self.save_qr_btn = QtWidgets.QPushButton("Save QR")
        export_row.addWidget(QtWidgets.QLabel("Barcode format"))
        export_row.addWidget(self.barcode_format_combo)
        export_row.addWidget(self.save_barcode_btn)
        export_row.addWidget(QtWidgets.QLabel("QR format"))
        export_row.addWidget(self.qr_format_combo)
        export_row.addWidget(self.save_qr_btn)
        form_layout.addRow(export_row)

        self.new_btn.clicked.connect(self._clear_form)
        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        self.refresh_btn.clicked.connect(self.refresh_table)
        self.include_desc_cb.toggled.connect(self._rerender_codes)
        self.include_location_cb.toggled.connect(self._rerender_codes)
        self.font_size_spin.valueChanged.connect(self._update_font_size)
        self.layout_combo.currentIndexChanged.connect(self._rerender_codes)
        self.show_text_cb.toggled.connect(self._rerender_codes)
        self.include_id_cb.toggled.connect(self._rerender_codes)
        self.custom_code_input.editingFinished.connect(self._rerender_codes)
        self.custom_label_text.textChanged.connect(self._rerender_codes)
        self.module_width_spin.valueChanged.connect(self._rerender_codes)
        self.module_height_spin.valueChanged.connect(self._rerender_codes)
        self.quiet_zone_spin.valueChanged.connect(self._rerender_codes)
        self.dpi_spin.valueChanged.connect(self._update_dpi)
        self.text_font_size_spin.valueChanged.connect(self._rerender_codes)
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
        search = self.search_input.text().strip()
        items, _ = self.inventory_repo.list_inventory_filtered(search=search, limit=500, offset=0)
        self.table_model.set_rows([asdict(item) for item in items])
        self._update_completers(items)
        self.table_proxy.invalidate()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _clear_form(self) -> None:
        self._dirty = False
        self.current_asset_id = None
        self.asset_id_label.setText("-")
        for widget in [
            self.description_input,
            self.manufacturer_input,
            self.model_input,
            self.serial_input,
            self.location_input,
        ]:
            widget.clear()
        self.consumable_checkbox.setChecked(False)
        self.created_label.setText("-")
        self.updated_label.setText("-")
        self._barcode_pixmap = None
        self._qr_pixmap = None
        self._barcode_image = None
        self._qr_image = None
        self.barcode_label.setText("Barcode preview")
        self.barcode_label.setPixmap(QtGui.QPixmap())
        self.qr_label.setText("QR code preview")
        self.qr_label.setPixmap(QtGui.QPixmap())

    def _toggle_details(self, hide: bool, splitter: QtWidgets.QSplitter) -> None:
        self.detail_panel.setVisible(not hide)
        self.toggle_details_btn.setText("Show Details" if hide else "Hide Details")
        if hide:
            splitter.setSizes([1, 0])
        else:
            splitter.setSizes([2, 1])

    def _on_selection(self) -> None:
        sel_model = self.table.selectionModel()
        if not sel_model:
            return
        indexes = sel_model.selectedRows()
        if not indexes:
            return
        if self._dirty:
            choice = QtWidgets.QMessageBox.question(
                self,
                "Unsaved changes",
                "You have unsaved changes. Keep editing the current item?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            )
            if choice == QtWidgets.QMessageBox.StandardButton.Yes:
                # revert selection
                if self._last_selection and self._last_selection.isValid():
                    sel_model.blockSignals(True)
                    sel_model.select(self._last_selection, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
                    sel_model.blockSignals(False)
                return
            self._dirty = False
        proxy_index = indexes[0]
        source_index = self.table_proxy.mapToSource(proxy_index)
        if not source_index.isValid() or source_index.row() >= len(self.table_model._rows):  # type: ignore[attr-defined]
            return
        row = self.table_model._rows[source_index.row()]  # type: ignore[attr-defined]
        self._last_selection = proxy_index
        self.current_asset_id = row.get("asset_id")
        self.asset_id_label.setText(row.get("asset_id", "-"))
        self.description_input.setText(row.get("description", ""))
        self.manufacturer_input.setText(row.get("manufacturer") or "")
        self.model_input.setText(row.get("model") or "")
        self.serial_input.setText(row.get("serial_number") or "")
        self.location_input.setText(row.get("location_id") or "")
        self.consumable_checkbox.setChecked(bool(row.get("consumable")))
        self.created_label.setText(row.get("created_at") or "-")
        self.updated_label.setText(row.get("updated_at") or "-")
        self._render_codes(self.current_asset_id)

    def _save(self) -> None:
        description = self.description_input.text().strip()
        location_id = self.location_input.text().strip()
        if not description or not location_id:
            QtWidgets.QMessageBox.warning(
                self, "Missing data", "Description and Location ID are required."
            )
            return
        if not self.location_repo.get_location(location_id):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid location",
                f"Location ID '{location_id}' was not found. Please create or choose a valid location.",
            )
            return
        try:
            if self.current_asset_id:
                self.inventory_repo.update_inventory(
                    self.current_asset_id,
                    description=description,
                    location_id=location_id,
                    consumable=self.consumable_checkbox.isChecked(),
                    manufacturer=self.manufacturer_input.text().strip() or None,
                    model=self.model_input.text().strip() or None,
                    serial_number=self.serial_input.text().strip() or None,
                )
            else:
                item = self.inventory_repo.create_inventory(
                    description=description,
                    location_id=location_id,
                    consumable=self.consumable_checkbox.isChecked(),
                    manufacturer=self.manufacturer_input.text().strip() or None,
                    model=self.model_input.text().strip() or None,
                    serial_number=self.serial_input.text().strip() or None,
                )
                self.current_asset_id = item.asset_id
                self.asset_id_label.setText(item.asset_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unable to save inventory item: %s", exc)
            QtWidgets.QMessageBox.warning(
                self,
                "Save failed",
                "Could not save the inventory item. Check that all fields are valid and try again.\n\n"
                f"Details: {exc}",
            )
            return
        self._dirty = False
        self.refresh_table()
        if self.current_asset_id:
            self._render_codes(self.current_asset_id)

    def _delete(self) -> None:
        if not self.current_asset_id:
            return
        resp = QtWidgets.QMessageBox.question(
            self,
            "Delete item",
            f"Delete asset {self.current_asset_id}?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if resp != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.inventory_repo.delete_inventory(self.current_asset_id)
            self._clear_form()
            self.refresh_table()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unable to delete inventory item: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Error", str(exc))

    def _render_codes(self, asset_id: Optional[str]) -> None:
        """
        Render barcode and QR previews for the selected asset, optionally including
        description and location labels.
        """
        if not asset_id:
            self.barcode_label.setText("Barcode preview")
            self.barcode_label.setPixmap(QtGui.QPixmap())
            self.qr_label.setText("QR code preview")
            self.qr_label.setPixmap(QtGui.QPixmap())
            self._barcode_image = None
            self._qr_image = None
            return

        code_data = self.custom_code_input.text().strip() or asset_id
        info_lines = []
        if self.include_id_cb.isChecked():
            info_lines.append(f"ID: {asset_id}")
            if code_data != asset_id:
                info_lines.append(code_data)
        elif code_data != asset_id:
            info_lines.append(code_data)
        if self.include_desc_cb.isChecked():
            desc = self.description_input.text().strip()
            if desc:
                info_lines.append(desc)
        if self.include_location_cb.isChecked():
            loc_text = self._location_text(self.location_input.text().strip())
            if loc_text:
                info_lines.append(loc_text)
        custom_lines = [
            line.strip() for line in self.custom_label_text.toPlainText().splitlines() if line.strip()
        ]
        info_lines.extend(custom_lines)

        # Barcode
        try:
            code39_cls = barcode.get_barcode_class("code39")
            code39 = code39_cls(code_data, writer=ImageWriter(), add_checksum=False)
            buffer = BytesIO()
            code39.write(
                buffer,
                options=self._barcode_writer_options(),
            )
            self._barcode_image = self._attach_label(
                buffer.getvalue(),
                info_lines,
                layout=self.layout_combo.currentText(),
                font_size=self._label_font_size,
            )
            self._barcode_pixmap = self._pil_to_pixmap(self._barcode_image)
            scaled = self._barcode_pixmap.scaled(
                200,
                120,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.barcode_label.setPixmap(scaled)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to render barcode: %s", exc)
            self.barcode_label.setText("Barcode unavailable")

        # QR code
        try:
            qr_data = "\n".join(info_lines)
            qr_img = self._generate_qr(qr_data)
            self._qr_image = self._attach_label_from_image(
                qr_img,
                info_lines,
                layout=self.layout_combo.currentText(),
                font_size=self._label_font_size,
            )
            self._qr_pixmap = self._pil_to_pixmap(self._qr_image)
            scaled_qr = self._qr_pixmap.scaled(
                160,
                160,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.qr_label.setPixmap(scaled_qr)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to render QR: %s", exc)
            self.qr_label.setText("QR unavailable")

    def _location_text(self, location_id: str) -> str:
        if not location_id:
            return ""
        loc = self.location_repo.get_location(location_id)
        if not loc:
            return f"Loc: {location_id}"
        vehicle_name = ""
        if loc.vehicle_id:
            vehicle = self.vehicle_repo.get_vehicle(loc.vehicle_id)
            vehicle_name = vehicle.vehicle_name if vehicle else loc.vehicle_id
        vehicle_part = f"{vehicle_name} " if vehicle_name else ""
        return f"{vehicle_part}{loc.side} Row {loc.row} Bin {loc.bin}"

    def _attach_label(self, base_bytes: bytes, lines, *, layout: str, font_size: int) -> "Image.Image":
        from PIL import Image, ImageDraw, ImageFont

        base = Image.open(BytesIO(base_bytes)).convert("RGB")
        return self._attach_label_from_image(base, lines, layout=layout, font_size=font_size)

    def _attach_label_from_image(self, base, lines, *, layout: str, font_size: int) -> "Image.Image":
        from PIL import Image, ImageDraw, ImageFont

        if not lines:
            return base
        font = ImageFont.load_default()
        # Use DejaVuSans if available to honor font size changes.
        try:
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
        padding = 4
        line_height = font.getbbox("Ag")[3]
        text_width = max(font.getbbox(line)[2] for line in lines) + padding * 2

        if layout == "Right of code":
            width = base.width + text_width
            height = max(base.height, (line_height + 4) * len(lines) + padding * 2)
            canvas = Image.new("RGB", (width, height), "white")
            canvas.paste(base, (0, (height - base.height) // 2))
            draw = ImageDraw.Draw(canvas)
            x_text = base.width + padding
            y_start = (height - (line_height + 4) * len(lines)) // 2
            for i, line in enumerate(lines):
                draw.text((x_text, y_start + i * (line_height + 4)), line, fill="black", font=font)
        else:  # Below code
            width = max(base.width, text_width)
            height = base.height + padding + (line_height + 4) * len(lines)
            canvas = Image.new("RGB", (width, height), "white")
            canvas.paste(base, ((width - base.width) // 2, 0))
            draw = ImageDraw.Draw(canvas)
            y_start = base.height + padding
            for i, line in enumerate(lines):
                draw.text((padding, y_start + i * (line_height + 4)), line, fill="black", font=font)
        return canvas

    def _generate_qr(self, data: str):
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img

    def _pil_to_pixmap(self, image) -> QtGui.QPixmap:
        buf = BytesIO()
        image.save(buf, format="PNG")
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(buf.getvalue())
        return pixmap

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
        base_label = self.description_input.text().strip() or "asset"
        default_name = self._default_filename(base_label, self.current_asset_id or "id", fmt)
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
                code_data = self.custom_code_input.text().strip() or (self.current_asset_id or "")
                code39 = code39_cls(code_data, writer=SVGWriter(), add_checksum=False)
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

    def _rerender_codes(self) -> None:
        if self.current_asset_id:
            self._render_codes(self.current_asset_id)

    def _update_font_size(self, value: int) -> None:
        self._label_font_size = value
        self._rerender_codes()

    def _barcode_writer_options(self) -> dict:
        return {
            "quiet_zone": float(self.quiet_zone_spin.value()),
            "module_height": int(self.module_height_spin.value()),
            "module_width": float(self.module_width_spin.value()),
            "write_text": self.show_text_cb.isChecked(),
            "dpi": int(self.dpi_spin.value()),
            "font_size": int(self.text_font_size_spin.value()),
        }

    def _update_dpi(self, value: int) -> None:
        self._label_dpi = value
        self._rerender_codes()

    def _default_filename(self, name: str, ident: str, fmt: str) -> str:
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in name)[:40] or "label"
        safe_id = "".join(ch if ch.isalnum() else "_" for ch in ident)[:20] or "id"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{safe_name}_{safe_id}_{ts}.{fmt}"

    def _update_completers(self, items: list[InventoryItem]) -> None:
        def completer(values: set[str]) -> QtWidgets.QCompleter:
            model = QtGui.QStandardItemModel()
            for val in sorted(values):
                item = QtGui.QStandardItem(val)
                model.appendRow(item)
            comp = QtWidgets.QCompleter(model, self)
            comp.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
            comp.setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
            comp.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            comp.setModelSorting(QtWidgets.QCompleter.ModelSorting.UnsortedModel)
            self._completers.append(comp)
            return comp

        descs = {i.description for i in items if i.description}
        mans = {i.manufacturer for i in items if i.manufacturer}
        models = {i.model for i in items if i.model}
        serials = {i.serial_number for i in items if i.serial_number}
        locs = {i.location_id for i in items if i.location_id}

        self.description_input.setCompleter(completer(descs))
        self.manufacturer_input.setCompleter(completer(mans))
        self.model_input.setCompleter(completer(models))
        self.serial_input.setCompleter(completer(serials))
        self.location_input.setCompleter(completer(locs))


class VehiclePane(QtWidgets.QWidget):
    def __init__(self, vehicle_repo: VehicleRepository, save_dir: Path):
        super().__init__()
        self.vehicle_repo = vehicle_repo
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.current_vehicle_id: Optional[str] = None
        self._barcode_image = None
        self._qr_image = None
        self._barcode_pixmap: Optional[QtGui.QPixmap] = None
        self._qr_pixmap: Optional[QtGui.QPixmap] = None
        self._label_font_size = 11
        self._label_dpi = 300
        self._default_module_width = 0.15
        self._default_module_height = 8
        self._default_quiet_zone = 1.5
        self._build_ui()
        self.refresh_table()

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        self.table_model = VehicleTableModel()
        self.table_proxy = QtCore.QSortFilterProxyModel()
        self.table_proxy.setSourceModel(self.table_model)
        self.table_proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.table_proxy.setFilterKeyColumn(-1)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.table_proxy)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.table.setToolTip("Vehicle list. Select a vehicle to edit and render labels.")
        install_copy_shortcut(self.table)
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        top_controls = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Search any column")
        self.search_input.textChanged.connect(self.table_proxy.setFilterFixedString)
        self.toggle_details_btn = QtWidgets.QPushButton("Hide Details")
        self.toggle_details_btn.setCheckable(True)
        self.toggle_details_btn.toggled.connect(lambda checked: self._toggle_details(checked, splitter))
        self.new_btn = QtWidgets.QPushButton("New Vehicle")
        self.new_btn.clicked.connect(self._clear_form)
        self.new_btn.setToolTip("Create a new vehicle with a new ID")
        top_controls.addWidget(QtWidgets.QLabel("Search:"))
        top_controls.addWidget(self.search_input)
        top_controls.addWidget(self.toggle_details_btn)
        top_controls.addWidget(self.new_btn)
        left_layout.addLayout(top_controls)
        left_layout.addWidget(self.table)
        splitter.addWidget(left_widget)

        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QFormLayout(form_widget)
        self.vehicle_id_label = QtWidgets.QLabel("-")
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(["Truck", "Trailer"])
        self.name_input = QtWidgets.QLineEdit()
        self.vin_input = QtWidgets.QLineEdit()
        self.number_input = QtWidgets.QSpinBox()
        self.number_input.setMaximum(999999)
        self.mileage_input = QtWidgets.QSpinBox()
        self.mileage_input.setMaximum(10_000_000)
        self.last_service_input = QtWidgets.QSpinBox()
        self.last_service_input.setMaximum(10_000_000)
        self.created_label = QtWidgets.QLabel("-")
        self.updated_label = QtWidgets.QLabel("-")

        form_layout.addRow("Vehicle ID:", self.vehicle_id_label)
        form_layout.addRow("Type:", self.type_combo)
        form_layout.addRow("Name:", self.name_input)
        form_layout.addRow("VIN:", self.vin_input)
        form_layout.addRow("Number:", self.number_input)
        form_layout.addRow("Mileage:", self.mileage_input)
        form_layout.addRow("Last Service:", self.last_service_input)
        form_layout.addRow("Created:", self.created_label)
        form_layout.addRow("Updated:", self.updated_label)

        button_row = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.service_btn = QtWidgets.QPushButton("Set last_service = mileage")
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        for btn in [self.save_btn, self.delete_btn, self.service_btn, self.refresh_btn]:
            button_row.addWidget(btn)
        form_layout.addRow(button_row)

        # Label controls (same as inventory pane)
        toggles_row = QtWidgets.QHBoxLayout()
        self.include_id_cb = QtWidgets.QCheckBox("Include ID")
        self.include_id_cb.setChecked(True)
        self.include_name_cb = QtWidgets.QCheckBox("Include name")
        self.include_name_cb.setChecked(True)
        self.include_meta_cb = QtWidgets.QCheckBox("Include meta")
        self.include_meta_cb.setChecked(True)
        self.text_font_size_spin = QtWidgets.QSpinBox()
        self.text_font_size_spin.setRange(6, 24)
        self.text_font_size_spin.setValue(10)
        self.font_size_spin = QtWidgets.QSpinBox()
        self.font_size_spin.setRange(8, 32)
        self.font_size_spin.setValue(self._label_font_size)
        self.layout_combo = QtWidgets.QComboBox()
        self.layout_combo.addItems(["Below code", "Right of code"])
        self.show_text_cb = QtWidgets.QCheckBox("Show barcode text")
        self.show_text_cb.setChecked(True)
        toggles_row.addWidget(self.include_id_cb)
        toggles_row.addWidget(self.include_name_cb)
        toggles_row.addWidget(self.include_meta_cb)
        toggles_row.addWidget(QtWidgets.QLabel("Font size"))
        toggles_row.addWidget(self.font_size_spin)
        toggles_row.addWidget(QtWidgets.QLabel("Layout"))
        toggles_row.addWidget(self.layout_combo)
        toggles_row.addWidget(self.show_text_cb)
        toggles_row.addWidget(QtWidgets.QLabel("Barcode text size"))
        toggles_row.addWidget(self.text_font_size_spin)
        form_layout.addRow("Label options:", toggles_row)

        self.custom_code_input = QtWidgets.QLineEdit()
        self.custom_code_input.setPlaceholderText("Defaults to vehicle ID if blank")
        form_layout.addRow("Barcode/QR data:", self.custom_code_input)

        self.custom_label_text = QtWidgets.QPlainTextEdit()
        self.custom_label_text.setPlaceholderText("Additional label lines (one per line)")
        self.custom_label_text.setFixedHeight(70)
        form_layout.addRow("Custom label lines:", self.custom_label_text)

        options_row = QtWidgets.QHBoxLayout()
        self.module_width_spin = QtWidgets.QDoubleSpinBox()
        self.module_width_spin.setRange(0.05, 1.0)
        self.module_width_spin.setSingleStep(0.05)
        self.module_width_spin.setValue(self._default_module_width)
        self.module_height_spin = QtWidgets.QSpinBox()
        self.module_height_spin.setRange(5, 80)
        self.module_height_spin.setValue(self._default_module_height)
        self.quiet_zone_spin = QtWidgets.QDoubleSpinBox()
        self.quiet_zone_spin.setRange(0.0, 20.0)
        self.quiet_zone_spin.setSingleStep(0.5)
        self.quiet_zone_spin.setValue(self._default_quiet_zone)
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(self._label_dpi)
        options_row.addWidget(QtWidgets.QLabel("Module width"))
        options_row.addWidget(self.module_width_spin)
        options_row.addWidget(QtWidgets.QLabel("Module height"))
        options_row.addWidget(self.module_height_spin)
        options_row.addWidget(QtWidgets.QLabel("Quiet zone"))
        options_row.addWidget(self.quiet_zone_spin)
        options_row.addWidget(QtWidgets.QLabel("DPI"))
        options_row.addWidget(self.dpi_spin)
        form_layout.addRow("Barcode tuning:", options_row)

        previews = QtWidgets.QHBoxLayout()
        self.barcode_label = QtWidgets.QLabel("Barcode preview")
        self.barcode_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.barcode_label.setMinimumHeight(160)
        self.barcode_label.setStyleSheet("border: 1px solid #ccc; padding: 4px;")
        self.qr_label = QtWidgets.QLabel("QR code preview")
        self.qr_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(160)
        self.qr_label.setStyleSheet("border: 1px solid #ccc; padding: 4px;")
        previews.addWidget(self.barcode_label)
        previews.addWidget(self.qr_label)
        form_layout.addRow(previews)

        export_row = QtWidgets.QHBoxLayout()
        self.barcode_format_combo = QtWidgets.QComboBox()
        self.barcode_format_combo.addItems(["PNG", "SVG", "EPS"])
        self.barcode_format_combo.setToolTip("Select barcode export format")
        self.qr_format_combo = QtWidgets.QComboBox()
        self.qr_format_combo.addItems(["PNG", "EPS"])
        self.qr_format_combo.setToolTip("Select QR export format")
        self.save_barcode_btn = QtWidgets.QPushButton("Save Barcode")
        self.save_qr_btn = QtWidgets.QPushButton("Save QR")
        export_row.addWidget(QtWidgets.QLabel("Barcode format"))
        export_row.addWidget(self.barcode_format_combo)
        export_row.addWidget(self.save_barcode_btn)
        export_row.addWidget(QtWidgets.QLabel("QR format"))
        export_row.addWidget(self.qr_format_combo)
        export_row.addWidget(self.save_qr_btn)
        form_layout.addRow(export_row)
        self.save_barcode_btn.setToolTip("Export barcode as PNG/SVG/EPS (Brother-friendly PNG recommended)")
        self.save_qr_btn.setToolTip("Export QR as PNG/EPS")

        self.new_btn.clicked.connect(self._clear_form)
        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        self.service_btn.clicked.connect(self._set_last_service)
        self.refresh_btn.clicked.connect(self.refresh_table)
        self.include_id_cb.toggled.connect(self._rerender_codes)
        self.include_name_cb.toggled.connect(self._rerender_codes)
        self.include_meta_cb.toggled.connect(self._rerender_codes)
        self.font_size_spin.valueChanged.connect(self._update_font_size)
        self.layout_combo.currentIndexChanged.connect(self._rerender_codes)
        self.show_text_cb.toggled.connect(self._rerender_codes)
        self.custom_code_input.editingFinished.connect(self._rerender_codes)
        self.custom_label_text.textChanged.connect(self._rerender_codes)
        self.module_width_spin.valueChanged.connect(self._rerender_codes)
        self.module_height_spin.valueChanged.connect(self._rerender_codes)
        self.quiet_zone_spin.valueChanged.connect(self._rerender_codes)
        self.dpi_spin.valueChanged.connect(self._update_dpi)
        self.save_barcode_btn.clicked.connect(lambda: self._save_image("barcode"))
        self.save_qr_btn.clicked.connect(lambda: self._save_image("qr"))
        self.text_font_size_spin.valueChanged.connect(self._rerender_codes)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        self.detail_panel = scroll
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

    def refresh_table(self) -> None:
        vehicles = self.vehicle_repo.list_vehicles()
        self.table_model.set_rows([asdict(v) for v in vehicles])

    def _clear_form(self) -> None:
        self.current_vehicle_id = None
        self.vehicle_id_label.setText("-")
        self.name_input.clear()
        self.vin_input.clear()
        self.number_input.setValue(0)
        self.mileage_input.setValue(0)
        self.last_service_input.setValue(0)
        self.created_label.setText("-")
        self.updated_label.setText("-")
        self._barcode_image = None
        self._qr_image = None
        self.barcode_label.setPixmap(QtGui.QPixmap())
        self.qr_label.setPixmap(QtGui.QPixmap())
        self._barcode_image = None
        self._qr_image = None
        self.barcode_label.setPixmap(QtGui.QPixmap())
        self.qr_label.setPixmap(QtGui.QPixmap())

    def _on_selection(self) -> None:
        sel_model = self.table.selectionModel()
        if not sel_model:
            return
        indexes = sel_model.selectedRows()
        if not indexes:
            return
        proxy_index = indexes[0]
        source_index = self.table_proxy.mapToSource(proxy_index)
        if not source_index.isValid() or source_index.row() >= len(self.table_model._rows):  # type: ignore[attr-defined]
            return
        row = self.table_model._rows[source_index.row()]  # type: ignore[attr-defined]
        self.current_vehicle_id = row.get("vehicle_id")
        self.vehicle_id_label.setText(row.get("vehicle_id", "-"))
        self.type_combo.setCurrentText(row.get("vehicle_type", "Truck"))
        self.name_input.setText(row.get("vehicle_name", ""))
        self.vin_input.setText(row.get("vin", ""))
        self.number_input.setValue(int(row.get("vehicle_number", 0) or 0))
        self.mileage_input.setValue(int(row.get("mileage", 0) or 0))
        self.last_service_input.setValue(int(row.get("last_service", 0) or 0))
        self.created_label.setText(row.get("created_at", "-"))
        self.updated_label.setText(row.get("updated_at", "-"))
        self._render_codes()

    def _save(self) -> None:
        name = self.name_input.text().strip()
        vin = self.vin_input.text().strip()
        if not name or not vin:
            QtWidgets.QMessageBox.warning(self, "Missing data", "Name and VIN are required.")
            return
        try:
            if self.current_vehicle_id:
                self.vehicle_repo.update_vehicle(
                    self.current_vehicle_id,
                    vehicle_type=self.type_combo.currentText(),
                    vehicle_name=name,
                    vin=vin,
                    vehicle_number=self.number_input.value(),
                    mileage=self.mileage_input.value(),
                    last_service=self.last_service_input.value(),
                )
            else:
                vehicle = self.vehicle_repo.create_vehicle(
                    vehicle_type=self.type_combo.currentText(),
                    vehicle_name=name,
                    vin=vin,
                    vehicle_number=self.number_input.value(),
                    mileage=self.mileage_input.value(),
                    last_service=self.last_service_input.value(),
                )
                self.current_vehicle_id = vehicle.vehicle_id
                self.vehicle_id_label.setText(vehicle.vehicle_id)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unable to save vehicle: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Error", str(exc))
            return
        self.refresh_table()

    def _delete(self) -> None:
        if not self.current_vehicle_id:
            return
        resp = QtWidgets.QMessageBox.question(
            self,
            "Delete vehicle",
            f"Delete vehicle {self.current_vehicle_id}?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if resp != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.vehicle_repo.delete_vehicle(self.current_vehicle_id)
            self._clear_form()
            self.refresh_table()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unable to delete vehicle: %s", exc)
            QtWidgets.QMessageBox.warning(self, "Error", str(exc))

    def _set_last_service(self) -> None:
        self.last_service_input.setValue(self.mileage_input.value())

    def _render_codes(self) -> None:
        if not self.current_vehicle_id:
            self.barcode_label.setText("Barcode preview")
            self.barcode_label.setPixmap(QtGui.QPixmap())
            self.qr_label.setText("QR code preview")
            self.qr_label.setPixmap(QtGui.QPixmap())
            self._barcode_image = None
            self._qr_image = None
            return

        code_data = self.custom_code_input.text().strip() or self.current_vehicle_id
        info_lines = []
        if self.include_id_cb.isChecked():
            info_lines.append(f"ID: {self.current_vehicle_id}")
        if code_data != self.current_vehicle_id or not self.include_id_cb.isChecked():
            info_lines.append(code_data)
        if self.include_name_cb.isChecked():
            name = self.name_input.text().strip()
            if name:
                info_lines.append(name)
        if self.include_meta_cb.isChecked():
            meta_parts = []
            if self.type_combo.currentText():
                meta_parts.append(self.type_combo.currentText())
            if self.number_input.value():
                meta_parts.append(f"No. {self.number_input.value()}")
            if meta_parts:
                info_lines.append(" ".join(meta_parts))
        custom_lines = [
            line.strip() for line in self.custom_label_text.toPlainText().splitlines() if line.strip()
        ]
        info_lines.extend(custom_lines)

        try:
            code39_cls = barcode.get_barcode_class("code39")
            code39 = code39_cls(code_data, writer=ImageWriter(), add_checksum=False)
            buffer = BytesIO()
            code39.write(buffer, options=self._barcode_writer_options())
            self._barcode_image = self._attach_label(
                buffer.getvalue(),
                info_lines,
                layout=self.layout_combo.currentText(),
                font_size=self._label_font_size,
            )
            self._barcode_pixmap = self._pil_to_pixmap(self._barcode_image)
            scaled = self._barcode_pixmap.scaled(
                200,
                120,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.barcode_label.setPixmap(scaled)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to render vehicle barcode: %s", exc)
            self.barcode_label.setText("Barcode unavailable")

        try:
            qr_data = "\n".join(info_lines)
            qr_img = self._generate_qr(qr_data)
            self._qr_image = self._attach_label_from_image(
                qr_img,
                info_lines,
                layout=self.layout_combo.currentText(),
                font_size=self._label_font_size,
            )
            self._qr_pixmap = self._pil_to_pixmap(self._qr_image)
            scaled_qr = self._qr_pixmap.scaled(
                160,
                160,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.qr_label.setPixmap(scaled_qr)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to render vehicle QR: %s", exc)
            self.qr_label.setText("QR unavailable")

    def _barcode_writer_options(self) -> dict:
        return {
            "quiet_zone": float(self.quiet_zone_spin.value()),
            "module_height": int(self.module_height_spin.value()),
            "module_width": float(self.module_width_spin.value()),
            "write_text": self.show_text_cb.isChecked(),
            "dpi": int(self.dpi_spin.value()),
            "font_size": int(self.text_font_size_spin.value()),
        }

    def _attach_label(self, base_bytes: bytes, lines, *, layout: str, font_size: int) -> "Image.Image":
        from PIL import Image, ImageDraw, ImageFont

        base = Image.open(BytesIO(base_bytes)).convert("RGB")
        return self._attach_label_from_image(base, lines, layout=layout, font_size=font_size)

    def _attach_label_from_image(self, base, lines, *, layout: str, font_size: int) -> "Image.Image":
        from PIL import Image, ImageDraw, ImageFont

        if not lines:
            return base
        font = ImageFont.load_default()
        try:
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()
        padding = 4
        line_height = font.getbbox("Ag")[3]
        text_width = max(font.getbbox(line)[2] for line in lines) + padding * 2

        if layout == "Right of code":
            width = base.width + text_width
            height = max(base.height, (line_height + 4) * len(lines) + padding * 2)
            canvas = Image.new("RGB", (width, height), "white")
            canvas.paste(base, (0, (height - base.height) // 2))
            draw = ImageDraw.Draw(canvas)
            x_text = base.width + padding
            y_start = (height - (line_height + 4) * len(lines)) // 2
            for i, line in enumerate(lines):
                draw.text((x_text, y_start + i * (line_height + 4)), line, fill="black", font=font)
        else:
            width = max(base.width, text_width)
            height = base.height + padding + (line_height + 4) * len(lines)
            canvas = Image.new("RGB", (width, height), "white")
            canvas.paste(base, ((width - base.width) // 2, 0))
            draw = ImageDraw.Draw(canvas)
            y_start = base.height + padding
            for i, line in enumerate(lines):
                draw.text((padding, y_start + i * (line_height + 4)), line, fill="black", font=font)
        return canvas

    def _generate_qr(self, data: str):
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img

    def _pil_to_pixmap(self, image) -> QtGui.QPixmap:
        buf = BytesIO()
        image.save(buf, format="PNG")
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(buf.getvalue())
        return pixmap

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
        base_label = self.name_input.text().strip() or "vehicle"
        default_name = self._default_filename(base_label, self.current_vehicle_id or "id", fmt)
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
                code_data = self.custom_code_input.text().strip() or (self.current_vehicle_id or "")
                code39 = code39_cls(code_data, writer=SVGWriter(), add_checksum=False)
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

    def _rerender_codes(self) -> None:
        if self.current_vehicle_id:
            self._render_codes()

    def _update_font_size(self, value: int) -> None:
        self._label_font_size = value
        self._rerender_codes()

    def _update_dpi(self, value: int) -> None:
        self._label_dpi = value
        self._rerender_codes()

    def _toggle_details(self, hide: bool, splitter: QtWidgets.QSplitter) -> None:
        self.detail_panel.setVisible(not hide)
        self.toggle_details_btn.setText("Show Details" if hide else "Hide Details")
        if hide:
            splitter.setSizes([1, 0])
        else:
            splitter.setSizes([2, 1])

    def _default_filename(self, name: str, ident: str, fmt: str) -> str:
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in name)[:40] or "label"
        safe_id = "".join(ch if ch.isalnum() else "_" for ch in ident)[:20] or "id"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{safe_name}_{safe_id}_{ts}.{fmt}"


class ViewTab(QtWidgets.QWidget):
    def __init__(self, inventory_repo: InventoryRepository, export_dir: Path):
        super().__init__()
        self.inventory_repo = inventory_repo
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.headers = [
            "asset_id",
            "location_id",
            "description",
            "consumable",
            "manufacturer",
            "model",
            "serial_number",
            "vehicle_name",
            "vehicle_type",
            "side",
            "row",
            "bin",
            "last_audited_at",
        ]
        self.model = DictTableModel(headers=self.headers)
        self.current_sort = ("description", QtCore.Qt.SortOrder.AscendingOrder)
        self.page_size = 50
        self.page = 0
        self.total = 0

        layout = QtWidgets.QVBoxLayout(self)

        # Global search
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Global search (any column)")
        layout.addWidget(self.search_input)

        # Column filters
        filters_widget = QtWidgets.QWidget()
        filters_layout = QtWidgets.QGridLayout(filters_widget)
        self.filter_inputs = {}

        def add_filter(label: str, widget: QtWidgets.QWidget, col: int, row: int) -> None:
            filters_layout.addWidget(QtWidgets.QLabel(label), row, col * 2)
            filters_layout.addWidget(widget, row, col * 2 + 1)

        self.filter_inputs["asset_id"] = QtWidgets.QLineEdit()
        add_filter("Asset ID", self.filter_inputs["asset_id"], 0, 0)

        self.filter_inputs["location_id"] = QtWidgets.QLineEdit()
        add_filter("Location ID", self.filter_inputs["location_id"], 1, 0)

        self.filter_inputs["description"] = QtWidgets.QLineEdit()
        add_filter("Description", self.filter_inputs["description"], 2, 0)

        self.filter_inputs["manufacturer"] = QtWidgets.QLineEdit()
        add_filter("Manufacturer", self.filter_inputs["manufacturer"], 3, 0)

        self.filter_inputs["model"] = QtWidgets.QLineEdit()
        add_filter("Model", self.filter_inputs["model"], 0, 1)

        self.filter_inputs["serial_number"] = QtWidgets.QLineEdit()
        add_filter("Serial", self.filter_inputs["serial_number"], 1, 1)

        self.filter_inputs["vehicle_name"] = QtWidgets.QLineEdit()
        add_filter("Vehicle", self.filter_inputs["vehicle_name"], 2, 1)

        self.filter_inputs["vehicle_type"] = QtWidgets.QComboBox()
        self.filter_inputs["vehicle_type"].addItems(["", "Truck", "Trailer"])
        add_filter("Vehicle Type", self.filter_inputs["vehicle_type"], 3, 1)

        self.filter_inputs["side"] = QtWidgets.QLineEdit()
        add_filter("Side", self.filter_inputs["side"], 0, 2)

        self.filter_inputs["row"] = QtWidgets.QLineEdit()
        add_filter("Row", self.filter_inputs["row"], 1, 2)

        self.filter_inputs["bin"] = QtWidgets.QLineEdit()
        add_filter("Bin", self.filter_inputs["bin"], 2, 2)

        self.filter_inputs["consumable"] = QtWidgets.QComboBox()
        self.filter_inputs["consumable"].addItems(["", "Yes", "No"])
        add_filter("Consumable", self.filter_inputs["consumable"], 3, 2)

        layout.addWidget(filters_widget)

        # Table
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalHeader().setStretchLastSection(True)
        install_copy_shortcut(self.table)
        layout.addWidget(self.table)

        # Pagination and exports
        controls_row = QtWidgets.QHBoxLayout()
        self.export_csv_btn = QtWidgets.QPushButton("Export CSV")
        self.export_pdf_btn = QtWidgets.QPushButton("Export PDF")
        self.reset_filters_btn = QtWidgets.QPushButton("Reset Filters")
        self.page_size_spin = QtWidgets.QSpinBox()
        self.page_size_spin.setRange(10, 5000)
        self.page_size_spin.setValue(self.page_size)
        self.show_all_cb = QtWidgets.QCheckBox("Show all")
        self.show_all_cb.toggled.connect(self._toggle_show_all)
        self.prev_btn = QtWidgets.QPushButton("Prev")
        self.next_btn = QtWidgets.QPushButton("Next")
        self.page_label = QtWidgets.QLabel("Page 1")
        controls_row.addWidget(self.export_csv_btn)
        controls_row.addWidget(self.export_pdf_btn)
        controls_row.addWidget(self.reset_filters_btn)
        controls_row.addWidget(QtWidgets.QLabel("Page size"))
        controls_row.addWidget(self.page_size_spin)
        controls_row.addWidget(self.show_all_cb)
        controls_row.addWidget(self.prev_btn)
        controls_row.addWidget(self.next_btn)
        controls_row.addWidget(self.page_label)
        layout.addLayout(controls_row)

        self.export_csv_btn.clicked.connect(self._export_csv)
        self.export_pdf_btn.clicked.connect(self._export_pdf)
        self.reset_filters_btn.clicked.connect(self._reset_filters)
        self.page_size_spin.valueChanged.connect(self._change_page_size)
        self.prev_btn.clicked.connect(lambda: self._change_page(-1))
        self.next_btn.clicked.connect(lambda: self._change_page(1))

        # Debounced filter reload
        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self.refresh_table)

        self.search_input.textChanged.connect(lambda _: self._filter_timer.start())
        for key, widget in self.filter_inputs.items():
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.textChanged.connect(lambda _v, k=key: self._filter_timer.start())
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.currentTextChanged.connect(lambda _v, k=key: self._filter_timer.start())

        self.refresh_table()

    def _filters(self) -> dict:
        filters = {}
        for key, widget in self.filter_inputs.items():
            if isinstance(widget, QtWidgets.QLineEdit):
                val = widget.text().strip()
                if key in ("row", "bin") and val.isdigit():
                    filters[key] = int(val)
                else:
                    filters[key] = val
            elif isinstance(widget, QtWidgets.QComboBox):
                filters[key] = widget.currentText().strip()
        gs = self.search_input.text().strip()
        if gs:
            filters["__global__"] = gs
        return filters

    def _build_sql_filters(self) -> dict:
        filters = {}
        all_filters = self._filters()
        global_term = all_filters.pop("__global__", "")
        if global_term:
            filters["global"] = global_term
        filters.update(all_filters)
        return filters

    def _reset_filters(self) -> None:
        self.search_input.clear()
        for key, widget in self.filter_inputs.items():
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.clear()
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.setCurrentIndex(0)
        self.page = 0
        self.refresh_table()

    def refresh_table(self) -> None:
        filters = self._build_sql_filters()
        order_by, order_dir = self.current_sort
        if self.show_all_cb.isChecked():
            limit = max(self.total or 1, int(self.page_size_spin.value()))
            offset = 0
        else:
            limit = int(self.page_size_spin.value())
            offset = self.page * limit

        # Build combined filters (global search spreads across textual columns)
        sql_filters = {}
        global_term = filters.pop("global", "")
        if global_term:
            sql_filters["global"] = global_term
        sql_filters.update(filters)

        rows, total = self.inventory_repo.list_inventory_view_filtered(
            sql_filters,
            order_by=order_by,
            order_dir="DESC" if order_dir == QtCore.Qt.SortOrder.DescendingOrder else "ASC",
            limit=limit,
            offset=offset,
        )
        self.total = total
        self.model.set_rows(rows)
        self._update_pagination_label()

    def _change_page(self, delta: int) -> None:
        max_page = max(0, (self.total - 1) // int(self.page_size_spin.value()) if self.total else 0)
        new_page = min(max(self.page + delta, 0), max_page)
        if new_page != self.page:
            self.page = new_page
            self.refresh_table()

    def _change_page_size(self, value: int) -> None:
        self.page_size = value
        self.page = 0
        self.refresh_table()

    def _update_pagination_label(self) -> None:
        if self.total == 0:
            self.page_label.setText("No results")
            return
        if self.show_all_cb.isChecked():
            self.page_label.setText(f"All results ({self.total})")
        else:
            total_pages = max(1, (self.total + int(self.page_size_spin.value()) - 1) // int(self.page_size_spin.value()))
            self.page_label.setText(f"Page {self.page + 1} of {total_pages} (Total {self.total})")

    def _toggle_show_all(self, checked: bool) -> None:
        if checked:
            # set page size to total results on next refresh
            self.page_size_spin.setEnabled(False)
        else:
            self.page_size_spin.setEnabled(True)
        self.page = 0
        self.refresh_table()

    def _on_header_clicked(self, section: int) -> None:
        header = self.headers[section]
        # Toggle sort order
        current_col, current_dir = self.current_sort
        if current_col == header:
            order_dir = QtCore.Qt.SortOrder.DescendingOrder if current_dir == QtCore.Qt.SortOrder.AscendingOrder else QtCore.Qt.SortOrder.AscendingOrder
        else:
            order_dir = QtCore.Qt.SortOrder.AscendingOrder
        self.current_sort = (header, order_dir)
        self.refresh_table()

    def _export_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            str(self.export_dir / "inventory_view.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        import csv

        headers = self.model.headers
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for row_idx in range(self.model.rowCount()):
                    row_data = []
                    for col_idx in range(len(headers)):
                        index = self.model.index(row_idx, col_idx)
                        row_data.append(self.model.data(index))
                    writer.writerow(row_data)
            QtWidgets.QMessageBox.information(self, "Exported", f"CSV saved to {path}")
        except Exception as exc:  # pylint: disable=broad-except
            QtWidgets.QMessageBox.warning(self, "Export failed", str(exc))

    def _export_pdf(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export PDF",
            str(self.export_dir / "inventory_view.pdf"),
            "PDF Files (*.pdf)",
        )
        if not path:
            return
        from PyQt6.QtPrintSupport import QPrinter
        from PyQt6.QtGui import QTextDocument

        headers = self.model.headers
        html_rows = []
        for row_idx in range(self.model.rowCount()):
            cols = []
            for col_idx in range(len(headers)):
                index = self.model.index(row_idx, col_idx)
                cols.append(f"<td>{self.model.data(index) or ''}</td>")
            html_rows.append(f"<tr>{''.join(cols)}</tr>")
        html = f"""
        <html><body>
        <h2>Inventory View</h2>
        <table border="1" cellspacing="0" cellpadding="3">
          <tr>{''.join(f'<th>{h}</th>' for h in headers)}</tr>
          {''.join(html_rows)}
        </table>
        </body></html>
        """
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        doc = QTextDocument()
        doc.setHtml(html)
        doc.print(printer)
        QtWidgets.QMessageBox.information(self, "Exported", f"PDF saved to {path}")


class AuditTab(QtWidgets.QWidget):
    def __init__(
        self,
        location_repo: LocationRepository,
        inventory_repo: InventoryRepository,
        audit_repo: AuditRepository,
    ):
        super().__init__()
        self.location_repo = location_repo
        self.inventory_repo = inventory_repo
        self.audit_repo = audit_repo
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        top_row = QtWidgets.QHBoxLayout()
        self.location_input = QtWidgets.QLineEdit()
        self.location_input.setPlaceholderText("Location ID")
        self.load_btn = QtWidgets.QPushButton("Load Location")
        self.load_btn.clicked.connect(self._load_location)
        top_row.addWidget(self.location_input)
        top_row.addWidget(self.load_btn)
        layout.addLayout(top_row)

        self.location_meta = QtWidgets.QLabel("")
        layout.addWidget(self.location_meta)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.expected_model = InventoryTableModel()
        self.expected_table = QtWidgets.QTableView()
        self.expected_table.setModel(self.expected_model)
        splitter.addWidget(self.expected_table)

        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        self.observed_list = QtWidgets.QListWidget()
        right_layout.addWidget(QtWidgets.QLabel("Observed asset IDs:"))
        right_layout.addWidget(self.observed_list)

        observed_controls = QtWidgets.QHBoxLayout()
        self.observed_input = QtWidgets.QLineEdit()
        self.observed_input.setPlaceholderText("Scan or type asset ID")
        self.add_observed_btn = QtWidgets.QPushButton("Add")
        self.clear_observed_btn = QtWidgets.QPushButton("Clear")
        observed_controls.addWidget(self.observed_input)
        observed_controls.addWidget(self.add_observed_btn)
        observed_controls.addWidget(self.clear_observed_btn)
        right_layout.addLayout(observed_controls)

        self.add_observed_btn.clicked.connect(self._add_observed)
        self.clear_observed_btn.clicked.connect(self.observed_list.clear)
        splitter.addWidget(right_widget)
        layout.addWidget(splitter)

        self.compare_btn = QtWidgets.QPushButton("Compare")
        self.apply_btn = QtWidgets.QPushButton("Apply Fixes")
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(self.compare_btn)
        btn_row.addWidget(self.apply_btn)
        layout.addLayout(btn_row)

        self.compare_btn.clicked.connect(self._compare)
        self.apply_btn.clicked.connect(self._apply_fixes_placeholder)

        self.results = QtWidgets.QTextEdit()
        self.results.setReadOnly(True)
        layout.addWidget(self.results)

    def _load_location(self) -> None:
        location_id = self.location_input.text().strip()
        if not location_id:
            return
        location = self.location_repo.get_location(location_id)
        if not location:
            QtWidgets.QMessageBox.warning(self, "Not found", "Location not found.")
            return
        meta = f"Location {location.location_id} | Vehicle: {location.vehicle_id or 'N/A'} | {location.side} row {location.row} bin {location.bin}"
        self.location_meta.setText(meta)
        items = self.inventory_repo.list_inventory(location_id=location_id)
        self.expected_model.set_rows([asdict(item) for item in items])
        self.results.clear()

    def _add_observed(self) -> None:
        value = self.observed_input.text().strip()
        if not value:
            return
        self.observed_list.addItem(value)
        self.observed_input.clear()

    def _compare(self) -> None:
        expected_ids = {self.expected_model._rows[i].get("asset_id") for i in range(len(self.expected_model._rows))}  # type: ignore[attr-defined]
        observed_ids = {self.observed_list.item(i).text() for i in range(self.observed_list.count())}
        missing = sorted(expected_ids - observed_ids)
        extra = sorted(observed_ids - expected_ids)
        lines = [
            f"Missing ({len(missing)}): {', '.join(missing) if missing else 'none'}",
            f"Extra ({len(extra)}): {', '.join(extra) if extra else 'none'}",
            "Note: Apply Fixes is a placeholder; wire this to audit_repo for full functionality.",
        ]
        self.results.setPlainText("\n".join(lines))

    def _apply_fixes_placeholder(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Apply Fixes",
            "Audit resolution is not fully implemented. Extend this method to write InventoryAudit entries and update locations.",
        )


class VehiclesTab(QtWidgets.QWidget):
    def __init__(self, vehicle_repo: VehicleRepository):
        super().__init__()
        self.vehicle_repo = vehicle_repo
        layout = QtWidgets.QVBoxLayout(self)
        headers = [
            "vehicle_id",
            "vehicle_name",
            "vehicle_type",
            "vin",
            "vehicle_number",
            "mileage",
            "last_service",
            "items_stored_count",
        ]
        self.model = DictTableModel(headers=headers)
        self.proxy = QtCore.QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_table)
        layout.addWidget(self.refresh_btn)
        self.refresh_table()

    def refresh_table(self) -> None:
        rows = self.vehicle_repo.overview_with_counts()
        self.model.set_rows(rows)
