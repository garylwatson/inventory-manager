import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List

from PyQt6 import QtCore

from .config import BackupConfig

logger = logging.getLogger(__name__)


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    """
    Create a consistent backup copy of the SQLite database using the backup API.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"inventory_{timestamp}.db"

    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(backup_path))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    logger.info("Backup created at %s", backup_path)
    return backup_path


def prune_backups(backup_dir: Path, max_backups: int) -> List[Path]:
    backups = sorted(backup_dir.glob("inventory_*.db"))
    removed: List[Path] = []
    if max_backups <= 0 or len(backups) <= max_backups:
        return removed
    for path in backups[:-max_backups]:
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            logger.warning("Unable to remove old backup %s: %s", path, exc)
    return removed


class BackupManager(QtCore.QObject):
    backup_started = QtCore.pyqtSignal()
    backup_finished = QtCore.pyqtSignal(str)
    backup_failed = QtCore.pyqtSignal(str)

    def __init__(self, db_path: Path, config: BackupConfig):
        super().__init__()
        self.db_path = Path(db_path)
        self.config = config
        self.backup_dir = Path(config.directory)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(self.config.interval_seconds * 1000)
        self.timer.timeout.connect(self._trigger_backup)
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        if not self.config.enabled:
            logger.info("Backups disabled via configuration")
            return
        self.timer.start()
        logger.info(
            "Backup timer started: every %s seconds", self.config.interval_seconds
        )

    def stop(self) -> None:
        self.timer.stop()

    def manual_backup(self) -> None:
        self._trigger_backup()

    def _trigger_backup(self) -> None:
        if not self.config.enabled:
            return
        if not self._lock.acquire(blocking=False):
            return
        self._running = True
        self.backup_started.emit()
        threading.Thread(target=self._run_backup, daemon=True).start()

    def _run_backup(self) -> None:
        try:
            backup_path = backup_database(self.db_path, self.backup_dir)
            removed = prune_backups(self.backup_dir, self.config.max_backups)
            QtCore.QTimer.singleShot(
                0, lambda: self._notify_success(backup_path, removed)
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Backup failed: %s", exc)
            QtCore.QTimer.singleShot(0, lambda: self._notify_failure(str(exc)))
        finally:
            self._lock.release()
            self._running = False

    def _notify_success(self, backup_path, removed):
        removed_str = ", ".join(str(p.name) for p in removed) if removed else "none"
        logger.info("Backup completed: %s (pruned: %s)", backup_path.name, removed_str)
        self.backup_finished.emit(str(backup_path))

    def _notify_failure(self, message: str):
        self.backup_failed.emit(message)
