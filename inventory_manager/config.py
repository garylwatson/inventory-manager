import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class DatabaseConfig:
    path: str = "./data/inventory.db"


@dataclass
class BackupConfig:
    enabled: bool = True
    interval_seconds: int = 300
    directory: str = "./backups"
    max_backups: int = 3


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = ""


@dataclass
class UiConfig:
    theme: str = "light"


@dataclass
class AppConfig:
    database: DatabaseConfig
    backup: BackupConfig
    logging: LoggingConfig
    ui: UiConfig
    raw: Dict[str, Any]


DEFAULT_CONFIG: Dict[str, Any] = {
    "database": {"path": "./data/inventory.db"},
    "backup": {
        "enabled": True,
        "interval_seconds": 300,
        "directory": "./backups",
        "max_backups": 288,
    },
    "logging": {"level": "INFO", "file": "./logs/app.log"},
    "ui": {"theme": "light"},
}


def _merge_dicts(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            override_sub = overrides.get(key, {}) if isinstance(overrides.get(key, {}), dict) else {}
            merged[key] = _merge_dicts(value, override_sub)
        else:
            merged[key] = overrides.get(key, value)
    # include keys present only in overrides
    for key, value in overrides.items():
        if key not in merged:
            merged[key] = value
    return merged


def load_config(path: Path) -> AppConfig:
    """
    Load configuration from YAML, merging with defaults and creating directories.
    """
    cfg_path = Path(path)
    user_config: Dict[str, Any] = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
            if not isinstance(loaded, dict):
                raise ValueError("config.yaml is not a valid mapping")
            user_config = loaded
    else:
        logging.warning("Config file %s not found. Using defaults.", cfg_path)

    merged = _merge_dicts(DEFAULT_CONFIG, user_config)

    database_cfg = DatabaseConfig(path=str(Path(merged["database"]["path"]).expanduser()))
    backup_cfg = BackupConfig(
        enabled=bool(merged["backup"].get("enabled", True)),
        interval_seconds=int(merged["backup"].get("interval_seconds", 300)),
        directory=str(Path(merged["backup"].get("directory", "./backups")).expanduser()),
        max_backups=int(merged["backup"].get("max_backups", 288)),
    )
    logging_cfg = LoggingConfig(
        level=str(merged["logging"].get("level", "INFO")).upper(),
        file=str(Path(merged["logging"].get("file", "")).expanduser())
        if merged["logging"].get("file", "")
        else "",
    )
    ui_cfg = UiConfig(theme=str(merged["ui"].get("theme", "light")))

    _ensure_directories(database_cfg, backup_cfg, logging_cfg)
    _configure_logging(logging_cfg)

    return AppConfig(
        database=database_cfg,
        backup=backup_cfg,
        logging=logging_cfg,
        ui=ui_cfg,
        raw=merged,
    )


def _ensure_directories(
    database_cfg: DatabaseConfig, backup_cfg: BackupConfig, logging_cfg: LoggingConfig
) -> None:
    Path(database_cfg.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    Path(backup_cfg.directory).expanduser().mkdir(parents=True, exist_ok=True)
    if logging_cfg.file:
        Path(logging_cfg.file).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _configure_logging(logging_cfg: LoggingConfig) -> None:
    level = getattr(logging, logging_cfg.level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]
    if logging_cfg.file:
        handlers.append(logging.FileHandler(logging_cfg.file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
