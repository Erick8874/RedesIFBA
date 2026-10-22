import tempfile
import sqlite3
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from snmp_monitor.alerts import (
    alert_messages,
    reset_changed_threshold_states,
    transition_alert_messages,
)
from snmp_monitor.config import AppConfig
from snmp_monitor.models import Sample
from snmp_monitor.repository import SampleRepository
from snmp_monitor.snmp_client import SnmpClient, calculate_rate


class RateTests(unittest.TestCase):
    def test_rate_is_reported_in_bits_per_second(self):
        self.assertEqual(calculate_rate(1500, 500, 2), 4000)

    def test_rate_handles_counter_wrap(self):
        self.assertEqual(calculate_rate(5, 2**32 - 5, 2), 40)

    def test_non_positive_elapsed_time_returns_zero(self):
        self.assertEqual(calculate_rate(100, 10, 0), 0)

    def test_counter_reset_does_not_create_a_huge_rate(self):
        self.assertEqual(calculate_rate(10, 1000, 1), 0)


class RepositoryTests(unittest.TestCase):
    def test_samples_can_be_saved_and_filtered_by_time(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SampleRepository(Path(directory) / "history.sqlite3")
            expected = Sample(100, 42, 1000, 500, 9000, 8000)
            repository.add(expected)
            repository.add(Sample(200, 12, 0, 0, 9000, 8000))

            self.assertEqual(repository.between(90, 110), [expected])

    def test_legacy_history_is_migrated_from_bytes_to_bits_per_second(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.sqlite3"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """CREATE TABLE samples (
                        timestamp REAL PRIMARY KEY, cpu_percent REAL NOT NULL,
                        rx_bytes_sec REAL NOT NULL, tx_bytes_sec REAL NOT NULL,
                        rx_counter INTEGER NOT NULL, tx_counter INTEGER NOT NULL
                    )"""
                )
                connection.execute(
                    "INSERT INTO samples VALUES (100, 42, 1000, 500, 9000, 8000)"
                )
                connection.commit()
            finally:
                connection.close()

            repository = SampleRepository(path)

            self.assertEqual(repository.between(90, 110), [Sample(100, 42, 8000, 4000, 9000, 8000)])


class AlertTests(unittest.TestCase):
    def test_cpu_alert_requires_usage_greater_than_one_percent(self):
        config = AppConfig()
        at_threshold = Sample(100, 1.0, 0, 0, 0, 0)
        above_threshold = Sample(101, 1.1, 0, 0, 0, 0)

        self.assertEqual(alert_messages(at_threshold, config), [])
        self.assertEqual(len(alert_messages(above_threshold, config)), 1)

    def test_messages_are_created_for_thresholds_reached(self):
        config = AppConfig(alert_cpu_percent=80, alert_traffic_bps=1_000_000)
        sample = Sample(100, 82, 1_200_000, 300_000, 0, 0)

        messages = alert_messages(sample, config)

        self.assertEqual(len(messages), 2)
        self.assertIn("CPU:", messages[0])
        self.assertIn("Tráfego IN:", messages[1])
        self.assertIn("bps", messages[1])
        self.assertIn(datetime.fromtimestamp(100).strftime("%Y-%m-%d %H:%M:%S"), messages[0])

    def test_traffic_threshold_is_checked_independently_for_each_direction(self):
        config = AppConfig(alert_traffic_bps=1000)
        sample = Sample(100, 0, 500, 1500, 0, 0)

        self.assertEqual(
            alert_messages(sample, config),
            [f"Tráfego OUT: 1500 bps (limite: 1000 bps) às {datetime.fromtimestamp(100):%Y-%m-%d %H:%M:%S}."],
        )

    def test_alert_repeats_only_after_metric_recovers(self):
        config = AppConfig(alert_cpu_percent=80)
        state = {"cpu": False, "in": False, "out": False}
        high = Sample(100, 90, 0, 0, 0, 0)
        normal = Sample(105, 70, 0, 0, 0, 0)

        first, state = transition_alert_messages(high, config, state)
        repeated, state = transition_alert_messages(high, config, state)
        recovered, state = transition_alert_messages(normal, config, state)
        again, _ = transition_alert_messages(high, config, state)

        self.assertEqual(len(first), 1)
        self.assertEqual(repeated, [])
        self.assertEqual(recovered, [])
        self.assertEqual(len(again), 1)

    def test_changing_cpu_threshold_rearms_cpu_alert(self):
        previous_config = AppConfig(alert_cpu_percent=80, alert_traffic_bps=1000)
        config = AppConfig(alert_cpu_percent=70, alert_traffic_bps=1000)
        state = {"cpu": True, "in": True, "out": False}

        updated_state = reset_changed_threshold_states(state, previous_config, config)
        messages, _ = transition_alert_messages(
            Sample(110, 75, 1500, 500, 0, 0), config, updated_state
        )

        self.assertEqual(updated_state, {"cpu": False, "in": True, "out": False})
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].startswith("CPU:"))

    def test_changing_traffic_threshold_rearms_both_directions(self):
        previous_config = AppConfig(alert_cpu_percent=80, alert_traffic_bps=1000)
        config = AppConfig(alert_cpu_percent=80, alert_traffic_bps=500)
        state = {"cpu": True, "in": True, "out": False}

        updated_state = reset_changed_threshold_states(state, previous_config, config)
        messages, _ = transition_alert_messages(
            Sample(110, 90, 700, 600, 0, 0), config, updated_state
        )

        self.assertEqual(updated_state, {"cpu": True, "in": False, "out": False})
        self.assertEqual(len(messages), 2)
        self.assertTrue(all(message.startswith("Tráfego") for message in messages))


class ConfigTests(unittest.TestCase):
    def test_router_address_defaults_to_configured_address(self):
        self.assertEqual(AppConfig().router_host, "192.168.88.1")

    def test_legacy_traffic_threshold_is_converted_from_bytes_to_bits(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                '{"alert_traffic_bytes_sec": 1000}', encoding="utf-8"
            )
            with patch("snmp_monitor.config.CONFIG_PATH", config_path):
                config = AppConfig.load()

        self.assertEqual(config.alert_traffic_bps, 8000)

    def test_snmpv3_requires_authentication_credentials(self):
        with self.assertRaisesRegex(ValueError, "SNMPv3 exige usuário"):
            AppConfig(snmp_version="3").validate()


class SnmpV3ClientTests(unittest.TestCase):
    def test_snmpv3_client_uses_usm_authentication(self):
        client = SnmpClient(
            "127.0.0.1",
            "",
            snmp_version="3",
            snmpv3_user="monitor",
            snmpv3_auth_key="auth-secret",
            snmpv3_priv_key="privacy-secret",
        )
        try:
            self.assertEqual(client.auth.__class__.__name__, "UsmUserData")
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()