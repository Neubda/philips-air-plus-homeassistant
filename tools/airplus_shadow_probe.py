#!/usr/bin/env python3
"""Read an own-account Air+ AWS shadow using an existing app JWT.

This temporary diagnostic does not solve autonomous login. Credentials stay
in memory. It publishes only an empty shadow/get request, never shadow/update.
Requires paho-mqtt. No raw messages, IDs, signed URLs or JWTs are reported.
"""
import getpass
import hashlib
import json
import os
import urllib.parse
import re
import threading

from airplus_probe import AIR_HOST, ProbeError, request_json, validate_reply


def summarize_fields(value, prefix=""):
    fields = []
    if not isinstance(value, dict):
        return fields
    for key, item in value.items():
        if not isinstance(key, str) or re.search(r"token|secret|serial|mac|ssid|password|device.?id|client.?id|^ip$|^name$", key, re.I):
            continue
        path = prefix + key
        if isinstance(item, dict):
            fields.extend(summarize_fields(item, path + "."))
        else:
            entry = {"field": path, "type": type(item).__name__}
            if isinstance(item, (bool, int, float)):
                entry["value"] = item
            elif isinstance(item, str) and key.startswith(("D03", "D05")) and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", item):
                entry["value"] = item
            fields.append(entry)
    return fields


def read_shadow(connection, device_id):
    import paho.mqtt.client as mqtt
    broker = connection.get("endpoint")
    path = connection.get("path")
    client_id = connection.get("client_id")
    if not isinstance(broker, str) or not broker.endswith(".amazonaws.com") or "/" in broker:
        raise ProbeError("Unexpected MQTT endpoint")
    if not isinstance(path, str) or not path.startswith("/mqtt?") or not isinstance(client_id, str):
        raise ProbeError("Missing signed websocket metadata")
    topic = f"$aws/things/{device_id}/shadow/get"
    finished = threading.Event()
    result = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, transport="websockets")
    network_proxy = os.environ.get("HTTPS_PROXY")
    if network_proxy:
        import socks
        proxy = urllib.parse.urlsplit(network_proxy)
        if proxy.scheme != "http" or not proxy.hostname:
            raise ProbeError("Unsupported network proxy")
        client.proxy_set(proxy_type=socks.HTTP, proxy_addr=proxy.hostname,
                         proxy_port=proxy.port or 80, proxy_rdns=True,
                         proxy_username=urllib.parse.unquote(proxy.username or "") or None,
                         proxy_password=urllib.parse.unquote(proxy.password or "") or None)
    client.tls_set()
    client.ws_set_options(path=path)

    def on_connect(client, userdata, flags, reason, properties):
        if reason.is_failure:
            result["error"] = "MQTT connection rejected"
            finished.set()
        else:
            client.subscribe([(topic + "/accepted", 0), (topic + "/rejected", 0)])

    def on_subscribe(client, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons):
            result["error"] = "Shadow subscription rejected"
            finished.set()
        else:
            client.publish(topic, payload=b"", qos=0, retain=False)

    def on_message(client, userdata, message):
        if message.topic == topic + "/rejected":
            result["error"] = "Shadow read rejected"
        elif message.topic == topic + "/accepted":
            try:
                body = json.loads(message.payload)
                state = body.get("state", {})
                result["reported_fields"] = summarize_fields(state.get("reported", {}))
                result["desired_field_keys"] = [item["field"] for item in summarize_fields(state.get("desired", {}))]
                result["shadow_version"] = body.get("version")
            except (ValueError, AttributeError, TypeError):
                result["error"] = "Unexpected shadow JSON"
        else:
            return
        finished.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    try:
        client.connect(broker, port=443, keepalive=30)
        client.loop_start()
        if not finished.wait(25):
            raise ProbeError("Shadow read timed out")
        if "error" in result:
            raise ProbeError(result["error"])
        return result
    except ProbeError:
        raise
    except Exception as error:
        raise ProbeError(f"MQTT transport failed ({type(error).__name__})") from None
    finally:
        client.disconnect()
        client.loop_stop()


def main():
    token = getpass.getpass("Existing Air+ JWT (not saved): ").strip()
    headers = {"Authorization": "jwt " + token}
    reply = request_json(AIR_HOST + "enduser/deviceList/", headers=headers)
    validate_reply(reply, "device_list")
    devices = reply.get("data")
    if not isinstance(devices, list):
        raise ProbeError("Unexpected device list")
    ids = [item.get("device_id") for item in devices if isinstance(item, dict)]
    if not ids or not all(isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]+", item) for item in ids):
        raise ProbeError("No valid own-account devices")
    reply = request_json(AIR_HOST + "enduser/v2/mqttInfo/", body={"device_id": ids}, headers=headers)
    validate_reply(reply, "mqtt_info")
    connections = reply.get("data", {}).get("mqttinfos", [])
    reports = []
    for connection in connections:
        device_id = connection.get("device_id")
        if device_id not in ids:
            raise ProbeError("Unexpected MQTT device")
        reports.append({"reference": hashlib.sha256(device_id.encode()).hexdigest()[:12],
                        "broker_host": connection.get("endpoint"),
                        **read_shadow(connection, device_id)})
    print(json.dumps({"shadows": reports, "device_state_changed": False}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ProbeError as error:
        print(f"Diagnostic failed: {error}")
        raise SystemExit(1)
