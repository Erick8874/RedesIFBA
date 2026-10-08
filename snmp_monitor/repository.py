import sqlite3
from pathlib import Path

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
                    rx_bytes_sec REAL NOT NULL,
                    tx_bytes_sec REAL NOT NULL,
                    rx_counter INTEGER NOT NULL,
                    tx_counter INTEGER NOT NULL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def add(self, sample: Sample) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?, ?)",
                (
                    sample.timestamp,
                    sample.cpu_percent,
                    sample.rx_bytes_sec,
                    sample.tx_bytes_sec,
                    sample.rx_counter,
                    sample.tx_counter,
                ),
            )

    def between(self, start: float, end: float) -> list[Sample]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT timestamp, cpu_percent, rx_bytes_sec, tx_bytes_sec,
                          rx_counter, tx_counter
                   FROM samples WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp""",
                (start, end),
            ).fetchall()
        return [Sample(*row) for row in rows]