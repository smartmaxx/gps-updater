from __future__ import annotations

import shutil
import subprocess
import sys

_REQUIRED_PACKAGES = {
    "click": "click",
    "rich": "rich",
    "gpxpy": "gpxpy",
    "exiftool": "PyExifTool",
}

_EXIFTOOL_INSTALL = {
    "darwin": "brew install exiftool",
    "linux": "sudo apt install libimage-exiftool-perl\n"
              "        or: sudo dnf install perl-Image-ExifTool",
    "win32": "winget install OliverBetz.ExifTool\n"
             "        or download installer from https://exiftool.org",
}


def check_all() -> str:
    """
    Check all dependencies. Returns the ExifTool version string.
    Prints error messages and exits with code 1 on any failure.
    """
    failed = False

    missing = [pkg for mod, pkg in _REQUIRED_PACKAGES.items() if not _importable(mod)]
    if missing:
        print(f"[ERROR] Missing Python packages: {', '.join(missing)}")
        print(f"        Install with: pip install {' '.join(missing)}")
        failed = True

    exiftool_version = _check_exiftool()
    if exiftool_version is None:
        failed = True

    if failed:
        sys.exit(1)

    return exiftool_version


def _importable(module: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(module) is not None


def _check_exiftool() -> str | None:
    if shutil.which("exiftool") is None:
        hint = _EXIFTOOL_INSTALL.get(sys.platform, "See https://exiftool.org")
        print("[ERROR] ExifTool not found on PATH")
        print(f"        Install with: {hint}")
        return None
    try:
        result = subprocess.run(
            ["exiftool", "-ver"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception as exc:
        print(f"[ERROR] ExifTool found but could not run: {exc}")
        return None
