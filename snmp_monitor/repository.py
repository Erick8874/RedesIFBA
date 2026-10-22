from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Iterator

from snmp_monitor.models import Sample


class SampleRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS samples (
                    timestamp REAL PRIMARY KEY,
                    cpu_percent REAL NOT NULL,
                    rx_bps REAL NOT NULL,
                    tx_bps REAL NOT NULL,
                    rx_counter INTEGER NOT NULL,
                    tx_counter INTEGER NOT NULL
                )"""
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(samples)")
            }
            if "rx_bytes_sec" in columns and "rx_bps" not in columns:
                connection.execute(
                    "ALTER TABLE samples RENAME COLUMN rx_bytes_sec TO rx_bps"
                )
                connection.execute(
                    "ALTER TABLE samples RENAME COLUMN tx_bytes_sec TO tx_bps"
                )
                connection.execute(
                    "UPDATE samples SET rx_bps = rx_bps * 8, tx_bps = tx_bps * 8"
                )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add(self, sample: Sample) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sample.timestamp,
                    sample.cpu_percent,
                    sample.rx_bps,
                    sample.tx_bps,
                    sample.rx_counter,
                    sample.tx_counter,
                ),
            )

    def between(self, start: float, end: float) -> list[Sample]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT timestamp, cpu_percent, rx_bps, tx_bps,
                          rx_counter, tx_counter
                   FROM samples WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp""",
                (start, end),
            ).fetchall()
        return [Sample(*row) for row in rows]