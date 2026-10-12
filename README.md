# Philips Air+ Home Assistant Integration

This is a community fork of
[ShorMeneses/philips-airplus-homeassistant](https://github.com/ShorMeneses/philips-airplus-homeassistant).
The original project's **Versuni DaConnect cloud/MQTT** integration remains the
basis for supported older purifiers. This fork adds model support and a separate
**Air+ cloud/AWS shadow backend** for **PureProtect 3200i (AC3220/10 / AC3221)**.

## Why two connection paths?

`models.yaml` is a device-property mapping: it tells the original integration
which reported registers, modes and sensors belong to a model. Adding an entry
works when the device is already discovered through DaConnect and speaks that
backend's MQTT port protocol. It does not change login, device discovery, MQTT
authentication or the message format.

That distinction matters for the two devices investigated in this fork:

| Device | Evidence | What was needed |
| --- | --- | --- |
| AC1715/10 | The [issue report](https://github.com/NikGro/philips-air-plus-homeassistant/issues/2) describes successful discovery and MQTT setup, followed by an unknown-model warning. The [merged contribution](https://github.com/NikGro/philips-air-plus-homeassistant/pull/1) reports a successful real-device test. | An additional `models.yaml` entry, matching the upstream AC1715/11 configuration. Use the DaConnect path. |
| PureProtect 3200i, reported as AC3220/10 / Unicorn | The old registry did not return the device; captured Air+ app traffic and a real cloud shadow identified a different API and MQTT protocol. | A new account client, device registry, token/signing flow, regional MQTT credentials, shadow transport and model mapping. Use the Air+ cloud path. |

Both setup paths offer email verification. The underlying implementation differs;
the new path still requires only an email code and device selection from the user.
Sharing D03/D05 register names does not prove that two devices share a cloud
backend, or that every register has the same meaning.

> This community fork is developed with AI assistance. The new AC3220/10
> backend is based on captured app traffic and a real read-only cloud shadow.
> Automated tests cover Home Assistant 2026.10.1; full control and long-term
> reconnection still need validation in a user's Home Assistant installation.

## What changed in v1.1.0?

Previous releases queried only DaConnect. A purifier visible in Air+ could
therefore be missing from the Home Assistant device picker. The new default
**Air+ cloud: email + verification code** queries `enduser/deviceList/` instead.
An AC3221 can be reported by this cloud as **AC3220/10**, type **Unicorn**.

The new Air+ backend provides:

- Email verification login, automatic cloud-token renewal and device selection.
- Cloud on/off and preset modes: Auto, Sleep, Medium, Turbo and Speed1–Speed5.
- PM2.5, allergen index, fan level, filter-cleaning and replacement-life sensors.
- MQTT reported-state updates with periodic reconciliation.
- Fresh signed MQTT credentials on every reconnect, with retry backoff.
- A cloud connection option that pauses activity and reloads the integration.

For this backend, power uses `D03102`, mode uses `D0310C`, and fan level uses
`D0310D`. Desired-state acknowledgments do not fabricate a physical state change.
Filter reset and standby-monitor commands are not exposed for Unicorn: their
meaning has not been verified. Older DaConnect models retain their existing
features and mappings in `models.yaml`.

## Installation and updating

1. In HACS, add `https://github.com/NikGro/philips-air-plus-homeassistant`
   as a custom repository with category **Integration**, if not already added.
2. Install or update **Philips Air+** to **v1.1.0**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Philips Air+**.
5. Choose the connection path for your device:
   - **PureProtect 3200i:** **Air+ cloud: email + verification code (recommended)**.
   - **AC1715/10 and other supported DaConnect models:**
     **DaConnect: email + verification code (older devices)**.
6. Enter the account email used in the official Air+ app, then its six-digit
   email verification code. Select the purifier from the list.

**Upgrading an unsuccessful PureProtect 3200i setup from v1.0.x:** remove the old, unsuccessful
Philips Air+ configuration entry and add it again using the new **Air+ cloud**
option. Existing entries retain their original authentication/backend; installing
an update alone does not change a DaConnect entry into an Air+ cloud entry.
Keep working entries for older devices. No manual UUID, app installation on the
PC, packet capture or DevTools is needed for the new setup.

For manual installation, copy `custom_components/philips_airplus` into your
Home Assistant configuration's `custom_components` directory and restart.
The purifier must already be linked to the same account in the official Air+ app.

## Supported backends

| Setup option | Devices | Mapping |
| --- | --- | --- |
| Air+ cloud (recommended) | Unicorn AC3220/10 and AC3221 variants | Captured cloud registers in `airmatters_model.py` |
| DaConnect email verification | AC1715/10 and other older devices linked to the Versuni registry | `models.yaml` |
| OAuth PKCE (advanced) | Legacy Air+ OAuth accounts | `models.yaml` |

The existing DaConnect mappings include AC0650/10, AC0651/10, **AC1715/10**,
AC1715/11 and AC1715/70. The AC1715/10 entry is included in **v1.1.0** and matches
the upstream AC1715/11 entry for every functional field (modes, ports, properties,
sensors and buttons). Its contributor reports working controls and sensor values
on a real AC1715/10; this is contributor validation, not a separate hardware test
by the maintainer. Regional suffixes alone are not sufficient evidence for other
models: check discovery, reported model identifier and MQTT values first.
For OAuth, follow the login URL and redirect instructions displayed by the setup
flow. This fallback uses the old registry and will not fix a missing Unicorn.

## Testing AC1715/10 support

Update through HACS to [v1.1.0](https://github.com/NikGro/philips-air-plus-homeassistant/releases/tag/v1.1.0)
and restart Home Assistant. Keep an existing entry created with the old email
flow: it stays on DaConnect. If setting up from scratch, select **DaConnect:
email + verification code (older devices)**. The new default Air+ cloud backend
currently supports Unicorn AC32xx devices and is not the AC1715 setup path.

Check that a fan and the PM2.5, allergen, fan-level and filter-life sensors appear.
Compare on/off, available presets and sensor values with the official app.
Wait for the reported state after commands; filter reset buttons do not need to
be pressed to validate discovery or sensors.

If something still fails, report the integration release, HA version, selected
setup option, whether the device appears in the picker, and whether entities are
missing, unavailable or displaying incorrect values. These are different failures:

| Observation | Useful evidence | Likely next investigation |
| --- | --- | --- |
| Device discovered and MQTT connected, but no entities | Reported model (`ctn`), `Device model reported` / `Model ... not found` messages, entity creation errors | Model matching or entity setup |
| Entities exist but state/control is incorrect | Redacted Config/Status/filter-port properties; relevant D03/D05 keys before and after one on/off or mode change | Register or mode mapping |
| Device absent from DaConnect, or MQTT never connects | Exact setup step/error, selected backend, account's official app, firmware and broker hostname/connection result | Account discovery or transport; investigate the alternate registry only if evidence points there |

For a short reproduction, enable these targeted loggers in **Developer tools →
Actions → `logger.set_level`**:

```yaml
action: logger.set_level
data:
  custom_components.philips_airplus.model_manager: debug
  custom_components.philips_airplus.coordinator: debug
  custom_components.philips_airplus.mqtt_client: debug
```

Reload the integration, reproduce one problem, then return those levels to `info`.
Share only relevant, redacted excerpts. Legacy MQTT debug messages can contain
device/account identifiers: remove emails, UUIDs, serial/MAC/IP values, tokens,
Authorization/Signature headers, client IDs and signed URL query strings. Keep
model identifiers, property names and non-identifying sensor/mode values.

If the device really is missing from the legacy registry, the optional
[read-only Windows probe](tools/airplus_windows_probe.ps1) can establish whether
it appears in the alternate Air+ registry and report its model/type/region without
printing tokens or device IDs. Appearance there alone does not establish support:
an unrecognised device family still needs a confirmed MQTT protocol and mapping.

## Account storage and network requirements

The Air+ setup stores the account identifier and app signing value in the local
Home Assistant config entry. The signing value is loaded once from a pinned,
SHA-256-verified upstream research document; downloaded content is never executed.
The GitHub raw-content host must therefore be reachable during setup. Runtime
requests use Philips/Gigya HTTPS and the regional AWS IoT MQTT broker on port 443.
JWTs and signed MQTT URLs remain in memory and are not written to config entries
or logs. Protect Home Assistant configuration backups as account-sensitive data.

Tokens are renewed without another email code during normal operation. If the
account is rejected or the device is unlinked, Home Assistant requests
reauthentication. Use the original account for that device. A network outage
instead triggers a retry with fresh MQTT credentials.

## Troubleshooting

- **No device in the picker:** check the device-specific setup option above and
  use the same account as the official app. For AC1715/10, start with DaConnect;
  for PureProtect 3200i, use Air+ cloud.
- **Unsupported model:** the new backend currently supports the Unicorn AC32xx
  models above. Other cloud families need their own confirmed mappings.
- **Unavailable:** check connectivity to Philips and AWS IoT on port 443. The
  integration retries outages; it cannot make a physically disconnected purifier
  reconnect to Wi-Fi.
- **Controls are acknowledged but state stays unchanged:** the integration waits
  for the device's reported state, rather than assuming it obeyed a command.

The read-only Windows diagnostic and research notes remain available in
[the investigation document](docs/ac3221-cloud-investigation.md). Remove account
identifiers, JWTs, signed URLs and captures before sharing diagnostics. The exact
Google Home server-to-server interface and a downloadable firmware image have
not been established; this integration uses the confirmed Air+ app backend.

## Development

Offline diagnostics:

```sh
python -m unittest discover -s tests -v
pwsh -NoProfile -File tools/airplus_windows_probe.ps1 -OfflineSelfTest
```

Home Assistant protocol and integration tests (Python 3.14):

```sh
python -m pip install homeassistant==2026.10.1 paho-mqtt==2.1.0 pytest pytest-asyncio
python -m pytest -q ha_tests
```

Tests use synthetic account identifiers and mock transports; they do not send
commands to a real purifier. CI runs both suites.

## Credits and license

Fork of [ShorMeneses/philips-airplus-homeassistant](https://github.com/ShorMeneses/philips-airplus-homeassistant).
Thanks to the original contributors, including @vkostakos, @markusstephany,
@rgpublic, and @renaudallard for the legacy HomeID email-login work.
The new Air+ login uses the independently documented runtime signing protocol in
[kwesolowski/node-red-contrib-philips-airplus](https://github.com/kwesolowski/node-red-contrib-philips-airplus).
See [third-party notices](tools/THIRD_PARTY_NOTICE.md) and [LICENSE](LICENSE).
