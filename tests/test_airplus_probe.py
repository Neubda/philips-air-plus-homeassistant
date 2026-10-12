"""Offline tests: no Philips account, real APK, or device is contacted."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.airplus_probe import ProbeError, apk_strings, discover, inspect_apk, java_urlencode, login, request_json


class ProbeTests(unittest.TestCase):
    def test_java_encoding(self):
        self.assertEqual(java_urlencode("PHILIPS:a b~*é"), "PHILIPS%3Aa+b%7E*%C3%A9")

    def test_nested_apk_scans_without_reporting_secret(self):
        secret = "a_" + "c0ffee00" * 4  # Synthetic fixture, never an app credential.
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("classes.dex", f"\0{secret}\0enduser/deviceList/\0enduser/firmware/check/\0https://www.api.air.philips.com/\0".encode())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.apkm"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("base.apk", data.getvalue())
            _, hits = apk_strings(path)
            self.assertEqual(hits, {secret})
            report = inspect_apk(path)
            self.assertEqual(report["signing_value_candidates"], 1)
            self.assertIn("enduser/firmware/check/", report["firmware_path_candidates"])
            self.assertNotIn(secret, json.dumps(report))
            self.assertFalse(report["firmware_candidates_are_verified"])

    def test_empty_device_list_is_not_guessed(self):
        with patch("tools.airplus_probe.request_json", side_effect=[
            {"meta": {"code": 0}, "data": {"token": "private-token"}},
            {"meta": {"code": 0}, "data": []},
        ]) as call:
            report = discover("private-uid", "private-key", mqtt_info=True)
        self.assertEqual(report["device_count"], 0)
        self.assertEqual(call.call_count, 2)
        self.assertFalse(report["ac3221_support_verified"])

    def test_metadata_report_omits_account_device_and_connection_credentials(self):
        raw_device = {"device_id": "private-device", "device_info": {
            "modelid": "AC3221/13", "swversion": "1.0.7", "name": "My bedroom", "mac": "private-mac", "serial": "private-serial",
        }}
        replies = [
            {"meta": {"code": 0}, "data": {"token": "private-token"}},
            {"meta": {"code": 0}, "data": [raw_device]},
            {"meta": {"code": 0}, "data": {"mqttinfos": [{"device_id": "private-device", "endpoint": "wss://broker.example/mqtt?X-Amz-Signature=private-signature", "path": "/mqtt?private-path", "client_id": "private-client"}]}},
        ]
        with patch("tools.airplus_probe.request_json", side_effect=replies) as call:
            report = discover("private-uid", "private-key", mqtt_info=True)
        text = json.dumps(report)
        for value in ("private-device", "private-token", "private-signature", "private-path", "private-client", "private-mac", "private-serial", "My bedroom"):
            self.assertNotIn(value, text)
        self.assertEqual(report["devices"][0]["modelid"], "AC3221/13")
        self.assertEqual(report["mqtt_connection_metadata"][0]["broker_host"], "broker.example")
        self.assertTrue(all("update" not in invocation.args[0] for invocation in call.call_args_list))

    def test_unknown_mqtt_device_is_rejected(self):
        replies = [
            {"meta": {"code": 0}, "data": {"token": "token"}},
            {"meta": {"code": 0}, "data": [{"device_id": "own", "device_info": {}}]},
            {"meta": {"code": 0}, "data": {"mqttinfos": [{"device_id": "other"}]}},
        ]
        with patch("tools.airplus_probe.request_json", side_effect=replies), self.assertRaises(ProbeError):
            discover("uid", "key", mqtt_info=True)

    def test_login_uses_uid_not_oidc_or_device_id(self):
        replies = [{"errorCode": 0, "vToken": "secret-vtoken"}, {"errorCode": 0, "UID": "correct-uid", "sessionInfo": {"cookieValue": "session-token"}}]
        with patch("tools.airplus_probe.request_json", side_effect=replies) as call:
            self.assertEqual(login("user@example.org", lambda _: "123456"), "correct-uid")
        self.assertEqual(call.call_count, 2)
        self.assertTrue(all("oidc" not in invocation.args[0] for invocation in call.call_args_list))

    def test_error_does_not_echo_backend_response(self):
        replies = [{"meta": {"code": 403, "message": "private-secret"}}]
        with patch("tools.airplus_probe.request_json", side_effect=replies):
            with self.assertRaises(ProbeError) as caught:
                discover("uid", "key")
        self.assertNotIn("private-secret", str(caught.exception))

    def test_no_requests_to_arbitrary_hosts(self):
        with self.assertRaises(ProbeError):
            request_json("https://unrelated.example/endpoint", headers={"Authorization": "secret"})


if __name__ == "__main__":
    unittest.main()
