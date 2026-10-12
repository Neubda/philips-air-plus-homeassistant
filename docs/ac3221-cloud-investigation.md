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

`tools/airplus_probe.py` uses only Python's standard library. It does not import
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
python tools/airplus_probe.py probe --apk /path/to/AirPlus.apk --output probe-report.json
```

The tool asks for the account email and a fresh emailed confirmation code. It
extracts the app signing value locally, keeps credentials only in memory, and
queries the alternate device list. Device names, MAC addresses, serials, IDs,
tokens and signing values are omitted from the report.

There is no OIDC exchange or HomeID device-list fallback in this route.

### 3. Check MQTT metadata, without connecting

```sh
python tools/airplus_probe.py probe --apk /path/to/AirPlus.apk --mqtt-info --output probe-report.json
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
