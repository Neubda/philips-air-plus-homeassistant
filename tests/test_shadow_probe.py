"""Ensure diagnostic output cannot expose numeric-looking device identifiers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from airplus_shadow_probe import summarize_fields


class ShadowSummaryTests(unittest.TestCase):
    def test_identity_fields_are_not_reported_as_sensor_values(self):
        fields = summarize_fields({"DeviceId": "private", "mac": "private",
                                   "D01S0D": "123456789012", "D0310C": 17,
                                   "D03221": "12", "WifiVersion": "version"})
        indexed = {item["field"]: item for item in fields}
        self.assertNotIn("DeviceId", indexed)
        self.assertNotIn("mac", indexed)
        self.assertNotIn("value", indexed["D01S0D"])
        self.assertEqual(indexed["D0310C"]["value"], 17)
        self.assertEqual(indexed["D03221"]["value"], "12")
        self.assertNotIn("value", indexed["WifiVersion"])

    def test_nested_tokens_are_omitted(self):
        fields = summarize_fields({"nested": {"secret": "private", "rssi": -60}})
        self.assertEqual(fields, [{"field": "nested.rssi", "type": "int", "value": -60}])
