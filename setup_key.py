"""Save your platform.kimi.ai API key to .env without it ever appearing on screen.

    python setup_key.py
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

import httpx

ENV = Path(__file__).with_name(".env")
BASE_URL = "https://api.moonshot.ai/v1"


def check(key: str) -> str:
    r = httpx.post(f"{BASE_URL}/tokenizers/estimate-token-count",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": "kimi-k3.1-pro", "messages": [{"role": "user", "content": "Bonjour Kimi"}]},
                   timeout=30)
    if r.status_code == 200 and "data" in r.json():
        return "ok"
    return f"HTTP {r.status_code}: {r.text[:200]}"


def main() -> int:
    key = getpass.getpass("Paste your Kimi API key (input is hidden), then press Enter: ").strip().strip('"\'')
    if not key:
        print("Nothing pasted; .env unchanged.")
        return 1
    if not key.startswith("sk-"):
        print("That doesn't look like a Kimi key (they start with 'sk-'). .env unchanged.")
        return 1
    if key.count("sk-") > 1:
        print(f"The key looks pasted {key.count('sk-')} times (the prompt hides what you type). "
              "Run again and paste once, then press Enter. .env unchanged.")
        return 1
    ENV.write_text(f"KIMI_API_KEY={key}\n", encoding="utf-8")
    os.chmod(ENV, 0o600)
    print(f"Saved to {ENV} (gitignored, readable only by you). Key ends in …{key[-4:]}.")
    result = check(key)
    if result == "ok":
        print("✓ Kimi accepted the key. You're ready: streamlit run app.py")
        return 0
    print(f"✗ Kimi rejected the key: {result}")
    print("  Check it was created on platform.kimi.ai > API Keys, and copied in full.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
