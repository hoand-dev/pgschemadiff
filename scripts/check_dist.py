"""Check built package archives for required resources and accidental files."""

from __future__ import annotations

import configparser
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "pgschemadiff"
CATALOG_ROOT = PACKAGE_ROOT / "infrastructure" / "postgres" / "catalog"
TUI_ROOT = PACKAGE_ROOT / "presentation" / "tui"
CONSOLE_SCRIPTS = ("pgsd", "pgschemadiff")


def _required_package_files() -> set[str]:
    files = {path.relative_to(PACKAGE_ROOT).as_posix() for path in PACKAGE_ROOT.rglob("*.py")}
    files.update(path.relative_to(PACKAGE_ROOT).as_posix() for path in CATALOG_ROOT.rglob("*.sql"))
    files.update(path.relative_to(PACKAGE_ROOT).as_posix() for path in TUI_ROOT.rglob("*.tcss"))
    files.add("py.typed")
    return files


def _check_forbidden_files(
    archive_name: str, member_names: list[str], violations: list[str]
) -> None:
    for member_name in member_names:
        parts = PurePosixPath(member_name).parts
        if "tests" in parts:
            violations.append(f"{archive_name}: contains tests/ entry {member_name}")
        if "__pycache__" in parts:
            violations.append(f"{archive_name}: contains __pycache__ entry {member_name}")
        if member_name.endswith(".pyc"):
            violations.append(f"{archive_name}: contains .pyc entry {member_name}")


def _check_wheel(path: Path, required_files: set[str], violations: list[str]) -> None:
    try:
        with zipfile.ZipFile(path) as wheel:
            names = wheel.namelist()
            name_set = set(names)
            for required in sorted(required_files):
                wheel_path = f"pgschemadiff/{required}"
                if wheel_path not in name_set:
                    violations.append(f"{path.name}: missing required file {wheel_path}")

            entry_points_files = sorted(
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            )
            if not entry_points_files:
                violations.append(f"{path.name}: missing .dist-info/entry_points.txt")
            else:
                parser = configparser.ConfigParser()
                try:
                    parser.read_string(wheel.read(entry_points_files[0]).decode("utf-8"))
                except (configparser.Error, UnicodeDecodeError) as error:
                    violations.append(f"{path.name}: invalid entry_points.txt: {error}")
                else:
                    scripts = (
                        parser["console_scripts"] if parser.has_section("console_scripts") else {}
                    )
                    for script in CONSOLE_SCRIPTS:
                        if script not in scripts:
                            violations.append(f"{path.name}: missing console script '{script}'")
            _check_forbidden_files(path.name, names, violations)
    except (OSError, zipfile.BadZipFile) as error:
        violations.append(f"{path.name}: cannot read wheel archive: {error}")


def _check_sdist(path: Path, required_files: set[str], violations: list[str]) -> None:
    try:
        with tarfile.open(path, "r:gz") as sdist:
            names = [member.name for member in sdist.getmembers()]
            name_set = set(names)
            roots = sorted(
                {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
            )
            if not roots:
                violations.append(f"{path.name}: missing source distribution root")
            else:
                root = roots[0]
                required_sdist_files = {"pyproject.toml", "README.md", "LICENSE"}
                required_sdist_files.update(f"src/pgschemadiff/{name}" for name in required_files)
                for required in sorted(required_sdist_files):
                    sdist_path = f"{root}/{required}"
                    if sdist_path not in name_set:
                        violations.append(f"{path.name}: missing required file {sdist_path}")
            _check_forbidden_files(path.name, names, violations)
    except (OSError, tarfile.TarError) as error:
        violations.append(f"{path.name}: cannot read sdist archive: {error}")


def main(argv: list[str]) -> int:
    """Validate wheel and source distributions in the supplied directory."""
    if len(argv) != 1:
        print("usage: check_dist.py DIST_DIR", file=sys.stderr)
        return 2

    dist_dir = Path(argv[0])
    if not dist_dir.is_dir():
        print(f"distribution directory does not exist: {dist_dir}", file=sys.stderr)
        return 2

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    violations: list[str] = []
    if not wheels:
        violations.append(f"{dist_dir}: no wheel archive (*.whl) found")
    if not sdists:
        violations.append(f"{dist_dir}: no source archive (*.tar.gz) found")

    required_files = _required_package_files()
    for wheel in wheels:
        _check_wheel(wheel, required_files, violations)
    for sdist in sdists:
        _check_sdist(sdist, required_files, violations)

    if violations:
        print("Distribution check failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print(f"Distribution check passed: {len(wheels)} wheel(s), {len(sdists)} sdist(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
