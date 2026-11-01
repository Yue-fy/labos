"""Portable archive paths and immutable publication for delivery builders.

The POSIX mode on staging files is not a Windows ACL guarantee. Callers on
Windows must use an output directory accessible only to the provisioning user.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path


class ArchivePaths:
    """Reject names that alias or escape when extracted on Windows or POSIX."""

    def __init__(self):
        self.entries: dict[str, tuple[str, bool, bool]] = {}

    def add(self, name: str, *, directory: bool = False, prefix: str | None = None) -> bool:
        """Register a destination; return whether its explicit entry is new."""
        if not name or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise ValueError(f"unsafe archive path: {name!r}")
        if directory and name.endswith("/"):
            name = name[:-1]
        parts = name.split("/")
        for part in parts:
            stem = part.split(".", 1)[0].upper()
            reserved = stem in {"CON", "PRN", "AUX", "NUL"} or (
                len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789¹²³"
            )
            if (part in {"", ".", ".."} or part.endswith((".", " ")) or reserved
                    or any(c in '<>:"|?*' for c in part)):
                raise ValueError(f"unsafe archive path: {name!r}")
        if prefix is not None and not (name.startswith(prefix + "/") or directory and name == prefix):
            raise ValueError(f"archive member outside {prefix!r}: {name!r}")
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            key = path.casefold()
            final = index == len(parts)
            is_directory = not final or directory
            old = self.entries.get(key)
            if old:
                spelling, old_directory, _ = old
                if spelling != path or not old_directory or not is_directory:
                    raise ValueError(f"colliding archive path: {name!r}")
            self.entries[key] = (path, is_directory, final or bool(old and old[2]))
        return old is None or not old[2]


def validate_members(archive: zipfile.ZipFile, *, prefix: str | None = None) -> list[zipfile.ZipInfo]:
    paths = ArchivePaths()
    members = archive.infolist()
    selected = []
    for member in members:
        # ZipInfo.filename may have silently truncated an original NUL-containing name.
        new_entry = paths.add(member.orig_filename, directory=member.is_dir(), prefix=prefix)
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("archive symbolic links are not supported")
        if new_entry:
            selected.append(member)
    return selected


def preflight_outputs(paths: list[Path]):
    for path in paths:
        if os.path.lexists(path):
            raise FileExistsError(f"delivery output exists: {path}")


@contextmanager
def private_stage(output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".labos-", suffix=".tmp", dir=output.parent)
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w+b") as stream:
            yield path, stream
    finally:
        path.unlink(missing_ok=True)


def publish_outputs(staged: list[tuple[Path, Path]]):
    """Publish without replacing any target; remove only links created by this call."""
    created = []
    try:
        for source, target in staged:
            os.link(source, target)
            created.append(target)
    except BaseException:
        for path in reversed(created):
            path.unlink()
        raise
