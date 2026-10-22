from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime

from snmp_monitor.config import AppConfig
from snmp_monitor.models import Sample


def alert_messages(sample: Sample, config: AppConfig) -> list[str]:
    messages: list[str] = []
    timestamp = datetime.fromtimestamp(sample.timestamp).strftime("%Y-%m-%d %H:%M:%S")
    if sample.cpu_percent > config.alert_cpu_percent:
        messages.append(
            f"CPU: {sample.cpu_percent:.1f}% (limite: "
            f"{config.alert_cpu_percent:.1f}%) às {timestamp}."
        )
    for direction, value in (("IN", sample.rx_bps), ("OUT", sample.tx_bps)):
        if value >= config.alert_traffic_bps:
            messages.append(
                f"Tráfego {direction}: {value:.0f} bps (limite: "
                f"{config.alert_traffic_bps:.0f} bps) às {timestamp}."
            )
    return messages


def transition_alert_messages(
    sample: Sample,
    config: AppConfig,
    previous_state: dict[str, bool],
) -> tuple[list[str], dict[str, bool]]:
    states = {
        "cpu": sample.cpu_percent > config.alert_cpu_percent,
        "in": sample.rx_bps >= config.alert_traffic_bps,
        "out": sample.tx_bps >= config.alert_traffic_bps,
    }
    labels = {"cpu": "CPU:", "in": "Tráfego IN:", "out": "Tráfego OUT:"}
    messages = [
        message
        for message in alert_messages(sample, config)
        if any(
            states[key] and not previous_state[key] and message.startswith(label)
            for key, label in labels.items()
        )
    ]
    return messages, states


def reset_changed_threshold_states(
    previous_state: dict[str, bool],
    previous_config: AppConfig,
    config: AppConfig,
) -> dict[str, bool]:
    states = previous_state.copy()
    if previous_config.alert_cpu_percent != config.alert_cpu_percent:
        states["cpu"] = False
    if previous_config.alert_traffic_bps != config.alert_traffic_bps:
        states["in"] = False
        states["out"] = False
    return states


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