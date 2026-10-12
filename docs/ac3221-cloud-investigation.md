# AC3221 cloud investigation — 12 October 2026

## Current result

The existing integration queries the **Versuni DaConnect** device list. An
empty list does not establish that the Air+ account has no devices, or that
the device has no cloud ID. It establishes that this API did not return it.
Adding a model entry or inventing a manual UUID cannot fix a different backend.

A concrete alternate Air+ route is already implemented in another project:

1. Philips/Gigya email OTP returns a **UID**.
2. A client-signed request exchanges `PHILIPS:<UID>` for an **Air+/gaoda JWT**.
3. The Air+ `deviceList` endpoint returns device IDs and metadata.
4. The Air+ `mqttInfo` endpoint returns connection details for these devices.
5. That reference project uses those details for AWS IoT shadow communication.

This route is demonstrated for a **CX3550/01 fan**, not for this user's AC3221.
The current task is to verify discovery for the AC3221 before implementing
controls. No AC3221 cloud support claim should be made until that verification.

## Sources and strength of evidence

| Source | What it establishes | What it does not establish |
| --- | --- | --- |
| [Ka3seBr0t reference implementation](https://github.com/Ka3seBr0t/HA_Philips_Air_Plus/tree/d1d3c61e991430a674a526e62d5721ede25b3161) | An implemented gaoda/Air+ authentication, discovery and MQTT path for CX3550 | AC3221 compatibility; the exact Google Home partner API |
| [OTP UID handling](https://github.com/Ka3seBr0t/HA_Philips_Air_Plus/blob/d1d3c61e991430a674a526e62d5721ede25b3161/custom_components/philips_airplus/oneid_login.py) | Its discovery uses Gigya UID, not the Versuni user-ID lookup | A successful login for the user's account |
| [Air+ cloud client](https://github.com/Ka3seBr0t/HA_Philips_Air_Plus/blob/d1d3c61e991430a674a526e62d5721ede25b3161/custom_components/philips_airplus/airmatters_auth.py) | Actual request paths and signed-token algorithm | A public API contract or stable vendor guarantee |
| [ioBroker Philips adapter](https://github.com/iobroker-community-adapters/ioBroker.philips-air) | AC3221 local register support, added in August 2026 | The alternate cloud path; it explicitly uses local CoAP |
| [Official Android app](https://play.google.com/store/apps/details?id=com.philips.ph.homecare) | The Air+ package is `com.philips.ph.homecare` | Access to its binary without a download/own installed copy |

Earlier notes in the reference project contain hypotheses later superseded by
its working client. The diagnostic follows the implementation rather than
assuming every earlier architecture note is correct.

## Concrete read-only diagnostic

Offline inspection in `tools/airplus_probe.py` uses only Python's standard library.
Live probing additionally requires `cryptography` and local JADX sources. It does not import
Home Assistant and does not replace the installed integration.

### 1. Inspect the app, offline

Provide your own Air+ APK, APKM or XAPK. A base APK or bundle containing it is
needed; a language-only split is insufficient. The official Android app can be
exported from an Android device, or an APK can be obtained from the
[Air+ distribution page](https://www.apkmirror.com/apk/versuni-netherlands-b-v/philips-air/).
The app is inspected as an archive and never run or modified.

```sh
python tools/airplus_probe.py inspect --apk /path/to/AirPlus.apk --output apk-report.json
```

The report lists relevant hosts, device paths and firmware-related path
candidates. Candidates are **not verified endpoints**. The signing value is
not included in the report; only the number of candidates is shown.

### 2. Check the alternate cloud device list

```sh
python tools/airplus_probe.py probe --apk /path/to/AirPlus.apk --decompiled-dir /path/to/jadx/sources --output probe-report.json
```

The tool asks for the account email and a fresh emailed confirmation code. It
extracts the app signing value locally, keeps credentials only in memory, and
queries the alternate device list. Device names, MAC addresses, serials, IDs,
tokens and signing values are omitted from the report.

There is no OIDC exchange or HomeID device-list fallback in this route.

### 3. Check MQTT metadata, without connecting

```sh
python tools/airplus_probe.py probe --apk /path/to/AirPlus.apk --decompiled-dir /path/to/jadx/sources --mqtt-info --output probe-report.json
```

This additional step only requests connection metadata for devices returned
by the authenticated account's own list. It reports broker hostname and
whether connection fields are present. It does not log signed URLs, connect to
MQTT, issue state commands, pair devices, install firmware, or change settings.

The source needs to be checked against the actual response: do not assume a
`da-` prefix, NCP port names, or purifier control keys from the older backend.
After discovery is verified, the next step is an exact-device MQTT **shadow/get**
capture, followed by mapping observed keys. `mqttInfo` credentials must be
renewed when reconnecting instead of blindly reusing an old signed URL.

## Firmware: can we obtain and reverse-engineer it?

**No confirmed AC3221 firmware image or public download URL has been obtained.**
The app binary is the best initial target: it may reveal update metadata
requests, firmware package URLs, model/product identifiers and image formats.
This can provide the cloud interface directly without needing firmware first.

Preferred order:

1. Inspect the APK's firmware/update paths and the AC3221's returned metadata.
2. Observe an **update check** by the user's official app, without installing an
   update. An account-authorized response may contain an image URL, version,
   signature or hash. Do not guess download paths or call update commands.
3. Download that exact authorized image if available; identify its container,
   hashes, compression, executable sections and embedded endpoint strings.
4. Only if that fails, consider a physical flash dump. The chip, interfaces and
   encryption settings must be established for the actual device. Neither
   readable UART nor an unencrypted ESP32 image is confirmed for this AC3221.

A downloaded image can be encrypted or contain only a patch, so obtaining it
does not guarantee useful decompilation. Hardware extraction is unnecessary
if the app already exposes the required authentication/discovery protocol.

## Required next evidence

- An Air+ APK/bundle to inspect (current download attempts here were blocked).
- The device-info screen: exact AC3221 suffix and installed firmware version.
- The sanitized diagnostic report from the user's account, to establish whether
  this alternate backend lists the purifier and offers MQTT metadata.

No account password, pasted access token, or manually guessed device ID is
needed. The current HA integration remains unchanged while this is investigated.

## Offline tests

```sh
python -m unittest discover -s tests -v
```

Tests cover nested APK scanning, non-disclosure of credentials in reports,
empty lists, OTP UID selection, Java-compatible encoding and unexpected-device
rejection. They do not claim live login, MQTT control or AC3221 verification.

## Static analysis of the supplied Air+ 3.19.0 APK

The supplied APK has SHA-256
`1c79f75b7562eaa122abfadc44c41cad1462015ca21c3ec4f817e28e9105278c`.
The supplied device-info screenshot reports **Wi-Fi firmware 86** and
**device firmware 0.2.3**. It does not establish the model suffix or hardware
platform. No firmware image was identified in the inspected APK assets.

JADX 1.5.6 produced source for 8,473 classes, with 68 decompilation errors.
The following findings are tied to readable methods; this is not a claim that
every app function was reconstructed. Proprietary source and signing values
are not included in this repository.

| APK class/method | Finding |
| --- | --- |
| `com.gaoda.sdk.http.HttpRequestManager.getTokenV2`, inner `a.onSuccess` | First GET `device/serverTime/`; extract `data.timestamp2` (the method parses `data` as JSON text); use it for the previously described two-stage HMAC signature and token POST. The diagnostic now mirrors this instead of assuming the computer clock. |
| `defpackage.ge`, `HttpRequestManager.getDeviceList`, `deviceDetail` | `enduser/deviceList/` is GET; `enduser/deviceInfo/` is GET with a `device_id` query parameter. |
| `defpackage.fe` | Authenticated requests use `Authorization: jwt <token>`. |
| `defpackage.g71`, `com.gaoda.sdk.mqtt.MxMqttClient` | AWS topics include `$aws/things/{device_id}/shadow/get`, `/get/#`, `/update`, `/update/accepted`, `/update/rejected`; additional notices use `Philips/{device_id}/ai-notice`. This independently confirms the reference's shadow transport. |
| `defpackage.lk1.b`, `tb0.n`, `x40.d`, `w40.m` | Device metadata is requested separately from `https://data.air-matters.com/UQtUO1_3qKZKlh7K` with a JSON `devices` array, `context: app`, `app_type: HomeCare`, and `user_info`. The app adds `x-am-app` and `x-am-authentication` headers. Returned `devices[0]` can include `wifi_firmware` and `device_firmware`. |
| `defpackage.tn1` | Each firmware record parses `URL`, `title`, `version`, `ota_id`, and `ota_mode`. |
| `PhilipsDeviceInfoActivity.onClick` | `URL` is attached to the **more information** button and opened as a page; it is not established as a binary download link. |
| `HttpRequestManager.otaConfirmation`, `defpackage.e01.c3` | POST `enduser/ota/confirmation/` contains `device_id` and `ota_id`; it is called when confirming an update. Do not use this for inspection. |
| `FirmwareUpdatePullRemote` | Its methods explicitly throw "Not implemented yet". This bundled legacy CDP2 class does not establish a working firmware downloader or the AC3221's platform. |

The metadata request includes model, model range/family, Wi-Fi/device versions,
platform, and potentially raw device data. The app chooses `mxchip`, `ESP`, or
`murata` based on the device object class. None is confirmed for this AC3221
from the screenshot alone. Replaying a guessed platform or fabricating IDs
would reduce the reliability of the investigation.

**Next step:** run the diagnostic against the user's Air+ account to verify its
actual device list and connection metadata. After that, capture a read-only
shadow and determine the real platform/control schema. Firmware retrieval
remains secondary; no binary URL or firmware image has been obtained. If
needed, observe the official app's metadata response and OTA delivery path
without accepting or installing an update.

The earlier APK/device-screen requests above have now been satisfied; the
outstanding evidence is the account-authorized discovery result. An empty
result must still be reported as empty rather than treated as support proof.


## Live authentication finding and correction

The user-authorized email OTP login succeeded. The subsequent Air+ token
exchange returned backend code **10001**, so no device list or MQTT metadata
was retrieved. This is not an empty-device-list result.

Tracing `ab1`'s constructor established that `HttpRequestManager.setSecret`
overrides the SDK's readable default with `mk1.w`'s production configuration.
That configuration is encrypted/obfuscated through `tj0.e`. Local decoding
confirmed the same production host and public app identifier, but a **different
signing secret**. Selecting the sole readable `a_...` candidate was incorrect.

`tools/airplus_apk_config.py` now reconstructs the non-China production branch
from the user's locally decompiled Air+ 3.19.0 sources. It embeds no app keys,
and the live probe fails closed unless this configuration is supplied and the
host/app identifier match. This reader is version-specific, not a general
extractor for future APKs. The default-configuration fingerprint is not proof
of a production signing key.

Preparation for this version:

```sh
python -m pip install cryptography
jadx --no-res -d /path/to/jadx /path/to/AirPlus.apk
python tools/airplus_probe.py probe --apk /path/to/AirPlus.apk --decompiled-dir /path/to/jadx/sources --mqtt-info --output probe-report.json
```

The corrected production configuration still requires a fresh live account
test; successful device discovery must not be claimed from static decoding.
