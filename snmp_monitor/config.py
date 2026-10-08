from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


APP_DIR = Path.home() / ".roteador_snmp_monitor"
CONFIG_PATH = APP_DIR / "config.json"
DATABASE_PATH = APP_DIR / "historico.sqlite3"


@dataclass
class AppConfig:
    router_host: str = ""
    community: str = "public"
    port: int = 161
    interval_seconds: int = 5
    interface_index: int = 0
    cpu_oid: str = "1.3.6.1.2.1.25.3.3.1.2"
    alert_cpu_percent: float = 90.0
    alert_traffic_bytes_sec: float = 10_000_000.0
    alert_mode: str = "popup"
    email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    email_from: str = ""

    @classmethod
    def load(cls) -> AppConfig:
        try:
            values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{key: value for key, value in values.items() if key in allowed})
        except (OSError, json.JSONDecodeError, TypeError):
            return cls()

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )