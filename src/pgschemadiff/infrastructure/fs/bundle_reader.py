"""Filesystem adapter for reading migration bundle inputs."""

from __future__ import annotations

import errno
import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class FilesystemBundleReader:
    """Read ``manifest.json`` and ``up.sql`` from a bundle directory.

    Filesystem errors, including missing paths and non-regular bundle entries,
    propagate as :class:`OSError` for the presentation layer to classify.
    """

    def read(self, bundle_dir: Path) -> tuple[bytes, bytes]:
        """Return manifest and executable SQL bytes; never read ``down.sql``."""
        directory_mode = bundle_dir.stat().st_mode
        if not stat.S_ISDIR(directory_mode):
            raise NotADirectoryError(
                errno.ENOTDIR,
                "Migration bundle path is not a directory",
                str(bundle_dir),
            )

        manifest_path = bundle_dir / "manifest.json"
        up_sql_path = bundle_dir / "up.sql"
        for path in (manifest_path, up_sql_path):
            if not stat.S_ISREG(path.lstat().st_mode):
                raise OSError(
                    errno.EINVAL,
                    "Migration bundle entry must be a regular file",
                    str(path),
                )

        return manifest_path.read_bytes(), up_sql_path.read_bytes()
