"""Prepare a private virtual environment once, then launch the local server."""

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path


def main():
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required. Install Python from https://www.python.org/downloads/")
        return 1
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("Preparing local Python environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    requirements = root / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = environment / ".requirements.sha256"
    installed = stamp.exists() and stamp.read_text().strip() == fingerprint
    if installed:
        installed = subprocess.run([str(python), "-c", "import flask, pikepdf, waitress"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not installed:
        print("Installing PDF dependencies (internet required on first run)...", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements)], check=True)
        stamp.write_text(fingerprint, encoding="ascii")
    return subprocess.call([str(python), str(root / "app.py"), *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Startup failed: {exc}\nCheck your Python installation and network, then try again.")
        raise SystemExit(1)
