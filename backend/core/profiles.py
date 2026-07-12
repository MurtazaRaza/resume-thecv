"""User profiles: a profile is a directory holding ALL per-person state
(cv.yaml, bank.yaml, versions/, letters/, out/, tracker.db). See
docs/features/profiles-and-bank.md.

The active profile is resolved per request from the `cve_profile` cookie, so
the per-user paths that used to be config.py constants are now attributes of a
resolved Profile. No auth: this is a data-partitioning convenience on a trusted
local machine, not a security boundary.
"""
import datetime
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from backend import config

COOKIE_NAME = "cve_profile"
DEFAULT_SLUG = "default"


@dataclass(frozen=True)
class Profile:
    """A resolved profile: its slug, display name, and every per-user path.
    Core modules take these paths explicitly instead of reading config."""
    slug: str
    name: str

    @property
    def dir(self) -> Path:
        return config.PROFILES_DIR / self.slug

    @property
    def cv_path(self) -> Path:
        return self.dir / "cv.yaml"

    @property
    def bank_path(self) -> Path:
        return self.dir / "bank.yaml"

    @property
    def versions_dir(self) -> Path:
        return self.dir / "versions"

    @property
    def letters_dir(self) -> Path:
        return self.dir / "letters"

    @property
    def out_dir(self) -> Path:
        return self.dir / "out"

    @property
    def tracker_db(self) -> Path:
        return self.dir / "tracker.db"

    @property
    def profile_yaml(self) -> Path:
        return self.dir / "profile.yaml"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "profile"


def _unique_slug(name: str) -> str:
    """Filesystem-safe slug, de-duplicated against existing profile dirs."""
    base = slugify(name)
    slug, n = base, 2
    while (config.PROFILES_DIR / slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _read_profile(slug: str) -> Optional[Profile]:
    d = config.PROFILES_DIR / slug
    if not d.is_dir():
        return None
    name = slug
    meta = d / "profile.yaml"
    if meta.is_file():
        try:
            data = yaml.safe_load(meta.read_text()) or {}
            name = str(data.get("name") or slug).strip() or slug
        except yaml.YAMLError:
            pass
    return Profile(slug=slug, name=name)


def list_profiles() -> List[Profile]:
    """All profiles, sorted by display name. Auto-creates `default` if none
    exist so the app always has a profile to resolve to."""
    config.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profiles = [p for slug in sorted(d.name for d in config.PROFILES_DIR.iterdir()
                                     if d.is_dir())
                if (p := _read_profile(slug)) is not None]
    if not profiles:
        profiles = [create_profile("Default")]
    return profiles


def get_profile(slug: str) -> Optional[Profile]:
    return _read_profile(slug)


def create_profile(name: str) -> Profile:
    """Create a new empty profile directory with profile.yaml metadata."""
    slug = _unique_slug(name)
    prof = Profile(slug=slug, name=(name or slug).strip() or slug)
    prof.dir.mkdir(parents=True, exist_ok=True)
    prof.profile_yaml.write_text(yaml.safe_dump(
        {"name": prof.name,
         "created_at": datetime.datetime.now().isoformat(timespec="seconds")},
        sort_keys=False, allow_unicode=True))
    return prof


def delete_profile(slug: str) -> None:
    """Remove a profile and all its data. Refuses to delete the last profile
    (the app always needs at least one)."""
    remaining = [p for p in list_profiles() if p.slug != slug]
    if not remaining:
        raise ValueError("Cannot delete the only profile.")
    d = config.PROFILES_DIR / slug
    if d.is_dir():
        shutil.rmtree(d)


def resolve(slug: Optional[str]) -> Profile:
    """Resolve a cookie slug to a Profile: the named one if it exists, else the
    first existing profile (auto-creating `default` via list_profiles)."""
    if slug:
        prof = _read_profile(slug)
        if prof is not None:
            return prof
    return list_profiles()[0]
