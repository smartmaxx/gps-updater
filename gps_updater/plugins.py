from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from gps_updater.models import CameraProfile

logger = logging.getLogger(__name__)

_DEFAULT_DATETIME_PRIORITY = [
    "DateTimeOriginal",
    "DateTimeDigitized",
    "CreateDate",
    "DateTime",
]


def load_all(extra_dir: str | None = None) -> list[CameraProfile]:
    """
    Discover and load all camera profiles.
    User-supplied profiles override bundled ones for the same make/model.
    Conflicts between two user-supplied profiles produce a warning.
    """
    bundled_dir = Path(__file__).parent.parent / "plugins"
    user_dirs: list[Path] = []

    home_plugins = Path.home() / ".config" / "gps-updater" / "plugins"
    if home_plugins.exists():
        user_dirs.append(home_plugins)

    local_plugins = Path.cwd() / "plugins"
    if local_plugins.exists():
        user_dirs.append(local_plugins)

    if extra_dir is not None:
        p = Path(extra_dir)
        if p.exists():
            user_dirs.append(p)
        else:
            logger.warning("Configured plugins_dir does not exist: %s", extra_dir)

    bundled = _load_dir(bundled_dir)
    user = []
    for d in user_dirs:
        user.extend(_load_dir(d))

    return _merge(bundled, user)


def match(profiles: list[CameraProfile], make: str | None, model: str | None) -> CameraProfile | None:
    """
    Return the best-matching profile for the given make/model.
    Matching is case-insensitive. Exact model match beats substring match.
    """
    if not make and not model:
        return None

    make_lower = (make or "").lower()
    model_lower = (model or "").lower()

    exact: CameraProfile | None = None
    substring: CameraProfile | None = None

    for profile in profiles:
        if profile.make.lower() != make_lower:
            continue
        for pattern in profile.model_patterns:
            p = pattern.lower()
            if p == model_lower:
                exact = profile
                break
            if p in model_lower or model_lower in p:
                substring = profile

    return exact or substring


def _load_dir(directory: Path) -> list[CameraProfile]:
    profiles = []
    if not directory.is_dir():
        return profiles
    for path in sorted(directory.glob("*.json")):
        profile = _load_file(path)
        if profile is not None:
            profiles.append(profile)
    return profiles


def _load_file(path: Path) -> CameraProfile | None:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Cannot load plugin %s: %s", path, exc)
        return None

    required = ("make", "model", "datetime_field_priority", "datetime_is_utc")
    missing = [k for k in required if k not in data]
    if missing:
        logger.error("Plugin %s missing required fields: %s", path, missing)
        return None

    model_raw = data["model"]
    model_patterns: list[str] = (
        [model_raw] if isinstance(model_raw, str) else list(model_raw)
    )

    return CameraProfile(
        make=data["make"],
        model_patterns=model_patterns,
        datetime_field_priority=list(data.get("datetime_field_priority", _DEFAULT_DATETIME_PRIORITY)),
        datetime_is_utc=bool(data.get("datetime_is_utc", False)),
        default_timezone_offset=data.get("default_timezone_offset"),
        has_embedded_gps=bool(data.get("has_embedded_gps", False)),
        on_embedded_gps=data.get("on_embedded_gps"),
        video_timestamp_source=data.get("video_timestamp_source"),
        reference_timestamp_source=data.get("reference_timestamp_source", "gps_timestamp"),
        notes=data.get("notes", ""),
        source_file=path,
    )


def _merge(bundled: list[CameraProfile], user: list[CameraProfile]) -> list[CameraProfile]:
    """
    Merge bundled and user profiles. User overrides bundled for same make/model.
    Warn when two user profiles clash.
    """
    # Index bundled by (make_lower, pattern_lower)
    registry: dict[tuple[str, str], CameraProfile] = {}
    for profile in bundled:
        for pattern in profile.model_patterns:
            registry[(profile.make.lower(), pattern.lower())] = profile

    # Track user-registered keys to detect user-vs-user conflicts
    user_registered: dict[tuple[str, str], Path] = {}

    for profile in user:
        for pattern in profile.model_patterns:
            key = (profile.make.lower(), pattern.lower())
            if key in user_registered:
                logger.warning(
                    "Conflicting camera profiles for %s / %s: %s and %s — using first found",
                    profile.make,
                    pattern,
                    user_registered[key],
                    profile.source_file,
                )
                continue
            user_registered[key] = profile.source_file
            registry[key] = profile

    seen_ids: set[int] = set()
    result: list[CameraProfile] = []
    for profile in registry.values():
        if id(profile) not in seen_ids:
            seen_ids.add(id(profile))
            result.append(profile)

    return result
