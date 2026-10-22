from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


APP_DIR = Path.home() / ".roteador_snmp_monitor"
CONFIG_PATH = APP_DIR / "config.json"
DATABASE_PATH = APP_DIR / "historico.sqlite3"


@dataclass
class AppConfig:
    router_host: str = "192.168.88.1"
    snmp_version: str = "2c"
    community: str = "public"
    snmpv3_user: str = ""
    snmpv3_auth_key: str = ""
    snmpv3_priv_key: str = ""
    port: int = 161
    interval_seconds: int = 5
    interface_index: int = 0
    cpu_oid: str = "1.3.6.1.2.1.25.3.3.1.2"
    # Ajuste aqui os limites padrão; eles também podem ser alterados na tela do app.
    alert_cpu_percent: float = 1.0
    alert_traffic_bps: float = 80_000_000.0
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
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Não foi possível ler a configuração: {error}") from error

        if not isinstance(values, dict):
            raise ValueError("O arquivo de configuração deve conter um objeto JSON.")
        allowed = cls.__dataclass_fields__.keys()
        settings = {key: value for key, value in values.items() if key in allowed}
        try:
            if "alert_traffic_bps" not in settings and "alert_traffic_bytes_sec" in values:
                settings["alert_traffic_bps"] = float(values["alert_traffic_bytes_sec"]) * 8
            if not settings.get("router_host"):
                settings["router_host"] = cls.router_host
            config = cls(**settings)
            config.validate()
            return config
        except (TypeError, ValueError) as error:
            raise ValueError(f"Configuração inválida: {error}") from error

    def validate(self) -> None:
        if not isinstance(self.router_host, str) or not self.router_host.strip():
            raise ValueError("Informe o IP ou nome do roteador.")
        if self.snmp_version not in {"2c", "3"}:
            raise ValueError("A versão SNMP deve ser 2c ou 3.")
        if self.snmp_version == "2c" and (
            not isinstance(self.community, str) or not self.community
        ):
            raise ValueError("Informe a comunidade SNMP de leitura.")
        if self.snmp_version == "3":
            if not self.snmpv3_user or len(self.snmpv3_auth_key) < 8:
                raise ValueError(
                    "SNMPv3 exige usuário e senha de autenticação com pelo menos 8 caracteres."
                )
            if self.snmpv3_priv_key and len(self.snmpv3_priv_key) < 8:
                raise ValueError(
                    "A senha de privacidade SNMPv3 deve ter pelo menos 8 caracteres."
                )
        if (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, int)
            or self.interval_seconds < 1
        ):
            raise ValueError("O intervalo de coleta deve ser um inteiro maior que zero.")
        if not 1 <= self.port <= 65535 or not 1 <= self.smtp_port <= 65535:
            raise ValueError("As portas devem estar entre 1 e 65535.")
        if (
            isinstance(self.interface_index, bool)
            or not isinstance(self.interface_index, int)
            or self.interface_index < 0
        ):
            raise ValueError("O índice da interface deve ser um inteiro não negativo.")
        if not isinstance(self.cpu_oid, str) or not self.cpu_oid.strip():
            raise ValueError("Informe um OID de CPU.")
        if (
            not math.isfinite(self.alert_cpu_percent)
            or not 0 <= self.alert_cpu_percent <= 100
            or not math.isfinite(self.alert_traffic_bps)
            or self.alert_traffic_bps <= 0
        ):
            raise ValueError("Thresholds de CPU ou tráfego inválidos.")
        if self.alert_mode not in {"popup", "email", "both"}:
            raise ValueError("Tipo de alerta inválido.")

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )