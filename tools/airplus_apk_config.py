"""Read Air+ 3.19.0's production configuration from locally decompiled sources.

No vendor constants are embedded. This version-specific reader requires
cryptography and a JADX source directory obtained from the user's own APK.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path


def production_config(source_directory: Path) -> dict[str, str]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    source = (source_directory / "defpackage/tj0.java").read_text()
    config_source = (source_directory / "defpackage/mk1.java").read_text()

    def shifted(encoded: str, offset: int) -> bytes:
        return "".join(chr((ord(char) + offset) % 65536)
                       for char in base64.b64decode(encoded).decode()).encode()

    root = re.search(r'd = new tj0\("([^"]+)", "([^"]+)", (\d+)\)', source)
    config = re.search(r'f = new tj0\(f\("([^"]+)"\), f\("([^"]+)"\), (\d+)\)', source)
    if root is None or config is None:
        raise ValueError("Unsupported app obfuscation layout")
    root_key = base64.b64decode(shifted(root[1], -int(root[3])))
    root_iv = shifted(root[2], int(root[3]))

    def unwrap(encoded: str) -> str:
        return AESGCM(root_key).decrypt(root_iv, base64.b64decode(encoded), None).decode()

    key = base64.b64decode(shifted(unwrap(config[1]), -int(config[3])))
    iv = shifted(unwrap(config[2]), int(config[3]))
    # The final branch of mk1.w is the non-China production environment.
    assignments = re.findall(r'odVar\.([abc]) = tj0.e\("([^"]+)"\)', config_source)
    final_branch = config_source.rsplit('if ("Staging".equals(philipsEnv))', 1)[-1]
    if "return odVar;" not in final_branch or len(assignments) < 3:
        raise ValueError("Unsupported production configuration layout")
    result = {field: AESGCM(key).decrypt(iv, base64.b64decode(encoded), None).decode()
              for field, encoded in assignments[-3:]}
    if set(result) != {"a", "b", "c"}:
        raise ValueError("Incomplete production configuration")
    return {"app_id": result["a"], "secret": result["b"], "host": result["c"]}
