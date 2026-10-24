"""Atomic filesystem adapter for migration bundles."""

from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from pgschemadiff.application.migration.render import render_bundle
from pgschemadiff.shared.errors import MigrationError

if TYPE_CHECKING:
    from pgschemadiff.application.migration.model import MigrationPlan


def _destination_exists(path: Path) -> bool:
    """Check filesystem entries, including dangling symlinks."""
    return path.exists() or path.is_symlink()


def _directory_fsync_unsupported(error: OSError) -> bool:
    return sys.platform == "win32" or error.errno in {
        errno.EINVAL,
        errno.ENOSYS,
        errno.ENOTSUP,
        errno.EOPNOTSUPP,
    }


def _fsync_directory(path: Path) -> None:
    """Sync directory metadata where the platform and filesystem support it."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        if _directory_fsync_unsupported(error):
            return
        raise

    try:
        os.fsync(descriptor)
    except OSError as error:
        if not _directory_fsync_unsupported(error):
            raise
    finally:
        os.close(descriptor)


def _remove_temp_directory(path: Path) -> None:
    with suppress(OSError):
        shutil.rmtree(path)


class FilesystemMigrationWriter:
    """Write complete bundles to an existing parent directory, without overwrite.

    The final path is checked immediately before ``os.rename``. A concurrent
    process can still create an empty destination between that check and rename;
    on POSIX, ``os.rename`` may replace such a directory.

    If syncing the parent fails after rename, the complete bundle remains
    published even though ``write`` raises; a retry then encounters a collision.
    """

    def write(self, plan: MigrationPlan, output_dir: Path) -> Path:
        """Render and atomically publish a bundle below an existing directory."""
        temp_directory: Path | None = None
        operation = "render bundle"
        operation_path: Path | str = output_dir

        try:
            rendered = render_bundle(plan)
            final_path = output_dir / rendered.dir_name

            operation = "check destination"
            operation_path = final_path
            if _destination_exists(final_path):
                raise MigrationError(f"Migration bundle destination already exists: {final_path}")

            operation = "validate output directory"
            operation_path = output_dir
            if not output_dir.is_dir():
                raise MigrationError(f"Output directory must already exist: {output_dir}")

            operation = "create temporary directory"
            temp_directory = Path(
                tempfile.mkdtemp(prefix=f".{rendered.dir_name}.tmp-", dir=output_dir)
            )

            for filename, content in rendered.files:
                file_path = temp_directory / filename
                operation = "write file"
                operation_path = file_path
                with open(file_path, "wb") as file:
                    file.write(content)
                    operation = "flush file"
                    file.flush()
                    operation = "fsync file"
                    os.fsync(file.fileno())

            operation = "fsync temporary directory"
            operation_path = temp_directory
            _fsync_directory(temp_directory)

            operation = "check destination"
            operation_path = final_path
            if _destination_exists(final_path):
                raise MigrationError(f"Migration bundle destination already exists: {final_path}")

            operation = "rename temporary directory"
            operation_path = f"{temp_directory} -> {final_path}"
            os.rename(temp_directory, final_path)
            temp_directory = None

            operation = "fsync output directory"
            operation_path = output_dir
            _fsync_directory(output_dir)
            return final_path
        except OSError as error:
            raise MigrationError(f"Failed to {operation} at {operation_path}: {error}") from error
        finally:
            if temp_directory is not None:
                _remove_temp_directory(temp_directory)
