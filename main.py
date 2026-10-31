#!/usr/bin/env python3
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL",
    category=Warning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Importing verbose from langchain root module is no longer supported",
    category=UserWarning,
)


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Redirected stdout/stderr default to cp1252 on Windows, which crashes
# console.print on non-ASCII output (e.g. the "→" in batch titles).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from jobs_auto_apply.cli import main

if __name__ == "__main__":
    main()
