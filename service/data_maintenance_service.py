"""用户数据目录检查与可恢复数据清理。"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from utils.runtime_path import (
    get_data_path,
    resolve_data_path,
)


BROWSER_CACHE_DIR_NAMES = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "GraphiteDawnCache",
    "GPUPersistentCache",
    "component_crx_cache",
    "extensions_crx_cache",
}
HISTORY_TABLE_NAMES = ("conversation_records", "agent_messages")


@dataclass
class CleanupResult:
    removed_files: int = 0
    removed_directories: int = 0
    removed_bytes: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class HistoryCleanupResult:
    removed_rows: int = 0
    databases: int = 0
    errors: list[str] = field(default_factory=list)


class DataMaintenanceService:
    def __init__(
        self,
        data_path: Path | None = None,
        history_database_paths: list[Path] | None = None,
        log_clearer=None,
    ) -> None:
        self.data_path = Path(data_path) if data_path is not None else get_data_path()
        self.history_database_paths = history_database_paths
        self.log_clearer = log_clearer

    def ensure_data_directory(self) -> Path:
        self.data_path.mkdir(parents=True, exist_ok=True)
        return self.data_path

    def clear_cache_and_logs(self) -> CleanupResult:
        result = CleanupResult()
        if self.log_clearer is None:
            from utils.logger_loguru import clear_log_files
            log_clearer = clear_log_files
        else:
            log_clearer = self.log_clearer

        files, size, errors = log_clearer()
        result.removed_files += files
        result.removed_bytes += size
        result.errors.extend(errors)

        user_data = self.data_path / "user_data"
        if user_data.exists():
            cache_paths = sorted(
                (
                    path for path in user_data.rglob("*")
                    if path.is_dir() and path.name in BROWSER_CACHE_DIR_NAMES
                ),
                key=lambda path: len(path.parts),
            )
            for path in cache_paths:
                if not path.exists():
                    continue
                size = self._path_size(path)
                try:
                    shutil.rmtree(path)
                    result.removed_directories += 1
                    result.removed_bytes += size
                except OSError as exc:
                    result.errors.append(f"{path}: {exc}")

        temporary_files = set((self.data_path / "temp").rglob("*.tmp"))
        temporary_files.add(self.data_path / "config.tmp")
        for path in temporary_files:
            if not path.is_file():
                continue
            try:
                result.removed_bytes += path.stat().st_size
                path.unlink()
                result.removed_files += 1
            except OSError as exc:
                result.errors.append(f"{path}: {exc}")
        return result

    def clear_conversation_history(self) -> HistoryCleanupResult:
        result = HistoryCleanupResult()
        for database_path in self._history_database_paths():
            if not database_path.is_file():
                continue
            try:
                connection = sqlite3.connect(str(database_path), timeout=10)
                try:
                    table_rows = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                    table_names = {str(row[0]) for row in table_rows}
                    touched = False
                    for table_name in HISTORY_TABLE_NAMES:
                        if table_name not in table_names:
                            continue
                        count = connection.execute(
                            f'SELECT COUNT(*) FROM "{table_name}"'
                        ).fetchone()[0]
                        connection.execute(f'DELETE FROM "{table_name}"')
                        result.removed_rows += int(count)
                        touched = True
                    connection.commit()
                    if touched:
                        result.databases += 1
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as exc:
                result.errors.append(f"{database_path}: {exc}")
        return result

    def _history_database_paths(self) -> list[Path]:
        if self.history_database_paths is not None:
            return sorted({Path(path).resolve() for path in self.history_database_paths})
        from config import config

        configured = resolve_data_path(
            config.get("db_path", "./temp/channel_shop.db")
        )
        paths = {
            Path(configured).resolve(),
            (self.data_path / "temp" / "agent.db").resolve(),
        }
        return sorted(paths)

    @staticmethod
    def _path_size(path: Path) -> int:
        total = 0
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
        return total


data_maintenance_service = DataMaintenanceService()


__all__ = [
    "BROWSER_CACHE_DIR_NAMES",
    "CleanupResult",
    "DataMaintenanceService",
    "HistoryCleanupResult",
    "data_maintenance_service",
]
