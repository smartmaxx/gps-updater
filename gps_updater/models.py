from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class MatchStatus(Enum):
    MATCHED = "matched"
    SKIPPED = "skipped"
    WARNED = "warned"
    FAILED = "failed"


@dataclass
class TrackPoint:
    timestamp: datetime
    latitude: float
    longitude: float
    elevation: float | None
    hdop: float | None
    pdop: float | None
    source_file: Path


@dataclass
class CameraProfile:
    make: str
    model_patterns: list[str]
    datetime_field_priority: list[str]
    datetime_is_utc: bool
    default_timezone_offset: str | None
    has_embedded_gps: bool
    on_embedded_gps: str | None
    video_timestamp_source: str | None
    reference_timestamp_source: str
    notes: str
    source_file: Path


@dataclass
class MediaRecord:
    path: Path
    capture_time: datetime | None
    capture_time_raw: str | None
    timezone_applied: str | None
    has_existing_gps: bool
    existing_lat: float | None
    existing_lon: float | None
    camera_make: str | None
    camera_model: str | None
    camera_profile: CameraProfile | None
    is_video: bool


@dataclass
class MatchResult:
    media: MediaRecord
    status: MatchStatus
    matched_lat: float | None
    matched_lon: float | None
    matched_elevation: float | None
    interpolation_ratio: float | None
    distance_to_existing_meters: float | None
    reason: str | None
