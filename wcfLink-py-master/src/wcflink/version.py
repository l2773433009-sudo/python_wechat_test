from __future__ import annotations

from importlib import metadata

from .models import VersionInfo


def current() -> VersionInfo:
    try:
        version = metadata.version("wcflink")
    except metadata.PackageNotFoundError:
        version = "0.1.0"
    return VersionInfo(version=version, commit=None, build_time=None, modified=False)
