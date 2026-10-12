#!/usr/bin/env python3
"""Investigate the alternate Air+ cloud without changing device state.

Protocol reference: Ka3seBr0t/HA_Philips_Air_Plus (MIT), commit
d1d3c61e991430a674a526e62d5721ede25b3161, airmatters_auth.py and oneid_login.py.
This is an isolated diagnostic, not proof of AC3221 support. No credentials
are hardcoded, printed, cached, or written to the diagnostic report.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

AIR_HOST = "https://www.api.air.philips.com/"
GIGYA_HOST = "https://cdc.accounts.home.id/"
GIGYA_KEY = "4_JGZWlP8eQHpEqkvQElolbA"  # Public app identifier, not a credential.
APP_ID = "9fd505fa9c7111e9a1e3061302926720"  # Public app identifier.
SECRET_PATTERN = re.compile(rb"(?<![A-Za-z0-9_])a_[0-9a-f]{32}(?![A-Za-z0-9_])")
ASCII_STRINGS = re.compile(rb"[\x20-\x7e]{4,}")
MAX_MEMBER_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class ProbeError(Exception):
    """A diagnostic failed; messages must never include response bodies/tokens."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None


def apk_strings(path: Path) -> tuple[set[str], set[str]]:
    """Read strings from DEX/resources/native binaries; never execute the APK."""
    strings: set[str] = set()
    secrets: set[str] = set()
    consumed = 0

    def scan(archive: zipfile.ZipFile, depth: int = 0):
        nonlocal consumed
        for member in archive.infolist():
            name = member.filename.lower()
            if not name.endswith((".apk", ".dex", ".so", ".json", ".xml", ".properties", ".txt", ".arsc")):
                continue
            if member.file_size > MAX_MEMBER_BYTES or consumed + member.file_size > MAX_TOTAL_BYTES:
                raise ProbeError("APK exceeds the static scanner size limit")
            consumed += member.file_size
            payload = archive.read(member)
            if name.endswith(".apk"):
                if depth == 0:
                    try:
                        with zipfile.ZipFile(io.BytesIO(payload)) as inner:
                            scan(inner, depth + 1)
                    except zipfile.BadZipFile:
                        continue
                continue
            secrets.update(value.decode("ascii") for value in SECRET_PATTERN.findall(payload))
            strings.update(value.decode("ascii") for value in ASCII_STRINGS.findall(payload))

    try:
        with zipfile.ZipFile(path) as archive:
            scan(archive)
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise ProbeError("Cannot read this APK/APKM/XAPK archive") from error
    return strings, secrets


def inspect_apk(path: Path) -> dict:
    strings, secrets = apk_strings(path)
    hosts: set[str] = set()
    paths: set[str] = set()
    firmware: set[str] = set()
    for value in strings:
        for match in re.findall(r"https?://[^\s\"'<>]+", value):
            try:
                url = urllib.parse.urlsplit(match)
                if url.hostname and any(term in url.hostname for term in ("philips", "versuni", "air-matters", "amazonaws")):
                    hosts.add(url.hostname)
            except ValueError:
                continue
        paths.update(re.findall(r"enduser/[A-Za-z0-9_./-]+", value))
        # Only report path-shaped candidates; generic words like "total"
        # must not be mistaken for OTA endpoints. These are not called.
        if re.search(r"firmware|upgrade|(?<![a-z])ota(?![a-z])", value, re.I):
            for match in re.findall(r"(?:https?://[^\s\"'<>]+|enduser/[A-Za-z0-9_./-]+/)", value):
                if re.search(r"firmware|upgrade|(?:^|/)ota(?:/|$)", match, re.I):
                    candidate = match.split("?", 1)[0]
                    if len(candidate) < 300 and not SECRET_PATTERN.search(candidate.encode()):
                        firmware.add(candidate)
    return {
        "apk_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "signing_value_candidates": len(secrets),
        "hosts": sorted(hosts),
        "device_paths": sorted(paths),
        "firmware_path_candidates": sorted(firmware),
        "firmware_candidates_are_verified": False,
    }


def java_urlencode(value: str) -> str:
    """Match Java URLEncoder, including its handling of *, ~ and UTF-8."""
    result = []
    for byte in value.encode("utf-8"):
        if 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122 or byte in b"-._*":
            result.append(chr(byte))
        else:
            result.append("+" if byte == 32 else f"%{byte:02X}")
    return "".join(result)


def signature(timestamp: str, username: str, secret: str) -> str:
    body = f"app_id={APP_ID}&timestamp={timestamp}&username={java_urlencode(username)}"
    first = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return hmac.new(username.encode(), first.encode(), hashlib.sha256).hexdigest()


def request_json(url: str, *, body=None, form=False, headers=None) -> dict:
    """Bounded, authenticated requests to the two documented hosts only."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ("www.api.air.philips.com", "cdc.accounts.home.id"):
        raise ProbeError("Refusing an unexpected cloud host")
    request_headers = {"User-Agent": "okhttp/4.9.3", "Accept": "application/json"}
    request_headers.update(headers or {})
    encoded = None
    if body is not None:
        if form:
            encoded = urllib.parse.urlencode(body).encode()
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            encoded = json.dumps(body, separators=(",", ":")).encode()
            request_headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=encoded, headers=request_headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise ProbeError(f"{parsed.path}: HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProbeError(f"{parsed.path}: network request failed") from None
    except (ValueError, UnicodeError):
        raise ProbeError(f"{parsed.path}: invalid JSON response") from None
    if not isinstance(payload, dict):
        raise ProbeError(f"{parsed.path}: unexpected response shape")
    return payload


def validate_reply(reply: dict, stage: str, *, gigya=False):
    code = reply.get("errorCode", -1) if gigya else reply.get("meta", {}).get("code", -1)
    if code != 0:
        # Server messages can echo personal data; report numeric error only.
        safe_code = code if isinstance(code, int) else "unknown"
        raise ProbeError(f"{stage}: backend error {safe_code}")


def login(email: str, code_reader=getpass.getpass) -> str:
    common = {"email": email, "apiKey": GIGYA_KEY, "format": "json"}
    reply = request_json(GIGYA_HOST + "accounts.auth.otp.email.sendCode", body=common, form=True)
    validate_reply(reply, "send_code", gigya=True)
    vtoken = reply.get("vToken")
    if not vtoken:
        raise ProbeError("send_code: verification handle missing")
    code = code_reader("Philips email confirmation code: ").strip()
    if not re.fullmatch(r"[0-9]{6}", code):
        raise ProbeError("Confirmation code must be six digits")
    reply = request_json(
        GIGYA_HOST + "accounts.auth.otp.email.login",
        body={**common, "code": code, "vToken": vtoken}, form=True,
    )
    validate_reply(reply, "verify_code", gigya=True)
    uid = reply.get("UID")
    if not isinstance(uid, str) or not uid:
        raise ProbeError("verify_code: UID missing")
    return uid


def discover(uid: str, secret: str, *, mqtt_info=False) -> dict:
    reply = request_json(AIR_HOST + "device/serverTime/")
    validate_reply(reply, "server_time")
    server_data = reply.get("data")
    if isinstance(server_data, str):
        try:
            server_data = json.loads(server_data)
        except ValueError:
            raise ProbeError("server_time: invalid data") from None
    timestamp = server_data.get("timestamp2") if isinstance(server_data, dict) else None
    if not isinstance(timestamp, (str, int)) or not re.fullmatch(r"[0-9]{1,20}", str(timestamp)):
        raise ProbeError("server_time: timestamp missing or invalid")
    timestamp = str(timestamp)
    username = "PHILIPS:" + uid
    reply = request_json(
        AIR_HOST + "enduser/v2/getToken/",
        body={"timestamp": timestamp, "username": username, "app_id": APP_ID},
        headers={"Signature": signature(timestamp, username, secret)},
    )
    validate_reply(reply, "airplus_token")
    token = reply.get("data", {}).get("token")
    if not isinstance(token, str) or not token:
        raise ProbeError("airplus_token: token missing")
    headers = {"Authorization": "jwt " + token}
    reply = request_json(AIR_HOST + "enduser/deviceList/", headers=headers)
    validate_reply(reply, "device_list")
    devices = reply.get("data", [])
    if not isinstance(devices, list):
        raise ProbeError("device_list: expected list")
    report = {"backend": "airplus_gaoda", "device_count": len(devices), "devices": []}
    own_ids: list[str] = []
    for item in devices:
        if not isinstance(item, dict) or not isinstance(item.get("device_id"), str):
            raise ProbeError("device_list: invalid device record")
        device_id = item["device_id"]
        info = item.get("device_info", {})
        if not isinstance(info, dict):
            raise ProbeError("device_list: invalid device metadata")
        own_ids.append(device_id)
        # Names, MAC addresses, serials, IDs and all credential fields omitted.
        summary = {"reference": hashlib.sha256(device_id.encode()).hexdigest()[:12], "metadata_keys": sorted(info)}
        for key in ("modelid", "type", "swversion", "product_id", "service_region", "is_online"):
            value = info.get(key)
            if isinstance(value, (str, int, float, bool)) and (not isinstance(value, str) or len(value) < 100):
                summary[key] = value
        summary["update_metadata_keys"] = [key for key in info if re.search(r"firmware|upgrade|ota|swversion", key, re.I)]
        report["devices"].append(summary)
    if mqtt_info and own_ids:
        reply = request_json(AIR_HOST + "enduser/v2/mqttInfo/", body={"device_id": own_ids}, headers=headers)
        validate_reply(reply, "mqtt_info")
        entries = reply.get("data", {}).get("mqttinfos", [])
        if not isinstance(entries, list):
            raise ProbeError("mqtt_info: expected list")
        connections = []
        for item in entries:
            if not isinstance(item, dict) or item.get("device_id") not in own_ids:
                raise ProbeError("mqtt_info: unexpected device")
            raw_endpoint = item.get("endpoint") or item.get("host", "")
            endpoint = urllib.parse.urlsplit(raw_endpoint if "://" in raw_endpoint else "//" + raw_endpoint)
            connections.append({
                "reference": hashlib.sha256(item["device_id"].encode()).hexdigest()[:12],
                "broker_host": endpoint.hostname,
                "has_client_id": bool(item.get("client_id")),
                "has_websocket_path": bool(item.get("path")),
            })
        report["mqtt_connection_metadata"] = connections
    report["device_state_changed"] = False
    report["mqtt_connection_attempted"] = False
    report["ac3221_support_verified"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "probe"))
    parser.add_argument("--apk", type=Path, required=True, help="Your Philips Air+ APK/APKM/XAPK")
    parser.add_argument("--decompiled-dir", type=Path, help="JADX sources directory for Air+ 3.19.0 production configuration")
    parser.add_argument("--mqtt-info", action="store_true", help="Also fetch metadata; does not connect or control")
    parser.add_argument("--output", type=Path, help="Write a sanitized JSON report")
    args = parser.parse_args()
    try:
        if args.mode == "inspect":
            report = inspect_apk(args.apk)
        else:
            if args.decompiled_dir is None:
                raise ProbeError("Live probing requires --decompiled-dir: the plain APK signing candidate is an overridden SDK default")
            try:
                from airplus_apk_config import production_config
                config = production_config(args.decompiled_dir)
            except Exception:
                raise ProbeError("Cannot read production configuration; check JADX sources and install cryptography") from None
            if config["host"] != AIR_HOST or config["app_id"] != APP_ID:
                raise ProbeError("Unsupported production host or app identifier")
            email = input("Philips account email: ").strip()
            if "@" not in email:
                raise ProbeError("Invalid email address")
            uid = login(email)
            report = discover(uid, config["secret"], mqtt_info=args.mqtt_info)
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(text + "\n")
        print(text)
        return 0
    except (ProbeError, OSError) as error:
        print(f"Diagnostic failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
