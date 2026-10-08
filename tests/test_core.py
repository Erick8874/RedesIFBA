import tempfile
import unittest
from pathlib import Path

from snmp_monitor.alerts import alert_messages
from snmp_monitor.config import AppConfig
from snmp_monitor.models import Sample
from snmp_monitor.repository import SampleRepository
from snmp_monitor.snmp_client import calculate_rate


class RateTests(unittest.TestCase):
    def test_rate_in_bytes_per_second(self):
        self.assertEqual(calculate_rate(1500, 500, 2), 500)

    def test_rate_handles_counter_wrap(self):
        self.assertEqual(calculate_rate(5, 2**32 - 5, 2), 5)

    def test_non_positive_elapsed_time_returns_zero(self):
        self.assertEqual(calculate_rate(100, 10, 0), 0)


class RepositoryTests(unittest.TestCase):
    def test_samples_can_be_saved_and_filtered_by_time(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SampleRepository(Path(directory) / "history.sqlite3")
            expected = Sample(100, 42, 1000, 500, 9000, 8000)
            repository.add(expected)
            repository.add(Sample(200, 12, 0, 0, 9000, 8000))

            self.assertEqual(repository.between(90, 110), [expected])


class AlertTests(unittest.TestCase):
    def test_messages_are_created_for_thresholds_reached(self):
        config = AppConfig(alert_cpu_percent=80, alert_traffic_bytes_sec=1_000_000)
        sample = Sample(100, 82, 1_200_000, 300_000, 0, 0)

        messages = alert_messages(sample, config)

        self.assertEqual(len(messages), 2)
        self.assertIn("CPU", messages[0])
        self.assertIn("Tráfego", messages[1])


if __name__ == "__main__":
    unittest.main()