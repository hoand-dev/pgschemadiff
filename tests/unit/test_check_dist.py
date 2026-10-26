from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "pgschemadiff"
CATALOG_ROOT = PACKAGE_ROOT / "infrastructure" / "postgres" / "catalog"
SCRIPT = PROJECT_ROOT / "scripts" / "check_dist.py"
SDIST_ROOT = "pgschemadiff-0.1.0"
ENTRY_POINTS = (
    "[console_scripts]\n"
    "pgsd = pgschemadiff.presentation.cli.main:app\n"
    "pgschemadiff = pgschemadiff.presentation.cli.main:app\n"
)


def _package_files() -> dict[str, bytes]:
    files = {
        path.relative_to(PACKAGE_ROOT).as_posix(): path.read_bytes()
        for path in PACKAGE_ROOT.rglob("*.py")
    }
    files.update(
        {
            path.relative_to(PACKAGE_ROOT).as_posix(): path.read_bytes()
            for path in CATALOG_ROOT.rglob("*.sql")
        }
    )
    files.update(
        {
            path.relative_to(PACKAGE_ROOT).as_posix(): path.read_bytes()
            for path in (PACKAGE_ROOT / "presentation" / "tui").rglob("*.tcss")
        }
    )
    files["py.typed"] = (PACKAGE_ROOT / "py.typed").read_bytes()
    return files


def _make_dist(
    dist_dir: Path,
    *,
    omit_wheel_files: set[str] | None = None,
    omit_sdist_files: set[str] | None = None,
    entry_points: str | None = ENTRY_POINTS,
    wheel_extras: dict[str, bytes] | None = None,
    sdist_extras: dict[str, bytes] | None = None,
) -> Path:
    dist_dir.mkdir()
    package_files = _package_files()
    omitted_wheel = {f"pgschemadiff/{name}" for name in omit_wheel_files or set()}
    wheel_files = {
        f"pgschemadiff/{name}": content
        for name, content in package_files.items()
        if f"pgschemadiff/{name}" not in omitted_wheel
    }
    if entry_points is not None:
        wheel_files["pgschemadiff-0.1.0.dist-info/entry_points.txt"] = entry_points.encode()
    wheel_files.update(wheel_extras or {})
    with zipfile.ZipFile(dist_dir / "pgschemadiff-0.1.0-py3-none-any.whl", "w") as wheel:
        for name, content in wheel_files.items():
            wheel.writestr(name, content)

    omitted_sdist = {f"src/pgschemadiff/{name}" for name in omit_sdist_files or set()}
    sdist_files = {
        f"{SDIST_ROOT}/src/pgschemadiff/{name}": content
        for name, content in package_files.items()
        if f"src/pgschemadiff/{name}" not in omitted_sdist
    }
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        sdist_files[f"{SDIST_ROOT}/{name}"] = (PROJECT_ROOT / name).read_bytes()
    sdist_files.update(
        {f"{SDIST_ROOT}/{name}": content for name, content in (sdist_extras or {}).items()}
    )
    with tarfile.open(dist_dir / "pgschemadiff-0.1.0.tar.gz", "w:gz") as sdist:
        for name, content in sdist_files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            sdist.addfile(info, BytesIO(content))
    return dist_dir


def _run_checker(dist_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, str(dist_dir)],
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.unit
def test_checker_accepts_complete_wheel_and_sdist(tmp_path: Path) -> None:
    result = _run_checker(_make_dist(tmp_path / "dist"))

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
def test_checker_reports_missing_catalog_sql(artifact: str, tmp_path: Path) -> None:
    missing = "infrastructure/postgres/catalog/schemas.sql"
    if artifact == "wheel":
        dist_dir = _make_dist(tmp_path / "dist", omit_wheel_files={missing})
    else:
        dist_dir = _make_dist(tmp_path / "dist", omit_sdist_files={missing})
    result = _run_checker(dist_dir)

    assert result.returncode != 0
    assert "schemas.sql" in result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
def test_checker_reports_missing_py_typed(artifact: str, tmp_path: Path) -> None:
    if artifact == "wheel":
        dist_dir = _make_dist(tmp_path / "dist", omit_wheel_files={"py.typed"})
    else:
        dist_dir = _make_dist(tmp_path / "dist", omit_sdist_files={"py.typed"})
    result = _run_checker(dist_dir)

    assert result.returncode != 0
    assert "py.typed" in result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["pgsd", "pgschemadiff"])
def test_checker_reports_missing_console_entry_point(missing: str, tmp_path: Path) -> None:
    present = "pgschemadiff" if missing == "pgsd" else "pgsd"
    entry_points = f"[console_scripts]\n{present} = pgschemadiff.presentation.cli.main:app\n"
    result = _run_checker(_make_dist(tmp_path / "dist", entry_points=entry_points))

    assert result.returncode != 0
    assert f"missing console script '{missing}'" in result.stdout + result.stderr


@pytest.mark.unit
def test_checker_reports_missing_entry_points_file(tmp_path: Path) -> None:
    result = _run_checker(_make_dist(tmp_path / "dist", entry_points=None))

    assert result.returncode != 0
    assert "entry_points.txt" in result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("artifact", "member"),
    [
        ("wheel", "tests/test_unwanted.py"),
        ("sdist", "tests/test_unwanted.py"),
    ],
)
def test_checker_rejects_tests_directory(artifact: str, member: str, tmp_path: Path) -> None:
    extras = {member: b"unwanted"}
    if artifact == "wheel":
        dist_dir = _make_dist(tmp_path / "dist", wheel_extras=extras)
    else:
        dist_dir = _make_dist(tmp_path / "dist", sdist_extras=extras)
    result = _run_checker(dist_dir)

    assert result.returncode != 0
    assert "tests/" in result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("artifact", "member"),
    [
        ("wheel", "pgschemadiff/__pycache__/module.pyc"),
        ("sdist", "src/pgschemadiff/__pycache__/module.pyc"),
        ("wheel", "pgschemadiff/module.pyc"),
        ("sdist", "src/pgschemadiff/module.pyc"),
    ],
)
def test_checker_rejects_bytecode_and_cache_directories(
    artifact: str, member: str, tmp_path: Path
) -> None:
    if artifact == "wheel":
        dist_dir = _make_dist(tmp_path / "dist", wheel_extras={member: b"unwanted"})
    else:
        dist_dir = _make_dist(tmp_path / "dist", sdist_extras={member: b"unwanted"})
    result = _run_checker(dist_dir)

    assert result.returncode != 0
    assert "__pycache__" in result.stdout + result.stderr or ".pyc" in result.stdout + result.stderr


@pytest.mark.unit
def test_checker_reports_missing_python_module(tmp_path: Path) -> None:
    result = _run_checker(_make_dist(tmp_path / "dist", omit_wheel_files={"__init__.py"}))

    assert result.returncode != 0
    assert "__init__.py" in result.stdout + result.stderr


@pytest.mark.unit
def test_checker_reports_unreadable_archives(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "broken.whl").write_bytes(b"not a zip")
    (dist_dir / "broken.tar.gz").write_bytes(b"not a tarball")

    result = _run_checker(dist_dir)

    assert result.returncode != 0
    assert "cannot read" in result.stdout + result.stderr


@pytest.mark.unit
def test_checker_requires_one_distribution_directory_argument(tmp_path: Path) -> None:
    result = _run_checker(tmp_path, "extra")

    assert result.returncode != 0
    assert "usage" in (result.stdout + result.stderr).lower()
