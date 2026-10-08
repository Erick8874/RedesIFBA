from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from snmp_monitor.config import AppConfig
from snmp_monitor.models import Sample


def alert_messages(sample: Sample, config: AppConfig) -> list[str]:
    messages: list[str] = []
    if sample.cpu_percent >= config.alert_cpu_percent:
        messages.append(
            f"CPU em {sample.cpu_percent:.1f}% (limite: {config.alert_cpu_percent:.1f}%)."
        )
    traffic = max(sample.rx_bytes_sec, sample.tx_bytes_sec)
    if traffic >= config.alert_traffic_bytes_sec:
        messages.append(
            "Tráfego em "
            f"{traffic / 1_000_000:.2f} MB/s (limite: "
            f"{config.alert_traffic_bytes_sec / 1_000_000:.2f} MB/s)."
        )
    return messages


def send_email(config: AppConfig, subject: str, body: str, password: str = "") -> None:
    if not config.smtp_host or not config.email_from or not config.email_to:
        raise ValueError("Preencha servidor SMTP, remetente e destinatário.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.email_from
    message["To"] = config.email_to
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        if config.smtp_username:
            server.login(config.smtp_username, password)
        server.send_message(message)