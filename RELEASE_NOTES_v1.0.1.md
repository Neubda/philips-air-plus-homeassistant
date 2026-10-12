## v1.0.1

### ⚠️ Vibe-coded
This fork was built largely with AI assistance ("vibe coding") and is not broadly tested on real hardware. Use at your own risk and back up your Home Assistant config first.

### What is included
- **AC1715/10 model support** – merged from PR #1 by @vraptunovich (`models.yaml` only).
- **AC3221 investigation tooling** – merged from PR #3: read-only diagnostics (`tools/`), tests, a CI workflow and `docs/ac3221-cloud-investigation.md`. These files do **not** change the installed integration; HACS only installs `custom_components/philips_airplus`. The README now states that AC3221 cloud support is still unverified.
- Everything from the earlier fork: PureProtect 3200i (AC3221) mapping (experimental), email + verification code onboarding, manual device UUID fallback.

### Fixes in this release
- `manifest.json` version aligned with the release tag (was `1.1.0`, tag was `v1.0.0`).
- `hacs.json` icon URL pointed to branch `main`; the default branch is `master`.
- README: added AC1715/10 to the supported-devices table and the contributors list, added the vibe-coding notice.

### 🎉 New contributor
Welcome and thank you to **@vraptunovich** for their first contribution: AC1715/10 model support in https://github.com/NikGro/philips-air-plus-homeassistant/pull/1

**Full changelog:** https://github.com/NikGro/philips-air-plus-homeassistant/compare/v1.0.0...v1.0.1
