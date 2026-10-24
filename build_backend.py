"""Small stdlib-only PEP 517 backend for AutoDebug's pure-Python distribution."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
NAME = PROJECT["name"].replace("-", "_")
VERSION = PROJECT["version"]
DIST_INFO = f"{NAME}-{VERSION}.dist-info"


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def _metadata() -> dict[str, bytes]:
    project = PROJECT
    metadata = (
        f"Metadata-Version: 2.1\nName: {project['name']}\nVersion: {VERSION}\n"
        f"Summary: {project['description']}\nRequires-Python: {project['requires-python']}\n"
    )
    for dependency in project.get("dependencies", []):
        metadata += f"Requires-Dist: {dependency}\n"
    scripts = "\n".join(f"{name} = {target}" for name, target in project.get("scripts", {}).items())
    return {
        "METADATA": (metadata + "\n").encode("utf-8"),
        "WHEEL": b"Wheel-Version: 1.0\nGenerator: autodebug-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        "entry_points.txt": f"[console_scripts]\n{scripts}\n".encode("utf-8"),
    }


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    directory = Path(metadata_directory) / DIST_INFO
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in _metadata().items():
        (directory / name).write_bytes(data)
    return DIST_INFO


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    filename = f"{NAME}-{VERSION}-py3-none-any.whl"
    destination = Path(wheel_directory)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(destination / filename, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        def add(name: str, data: bytes) -> None:
            wheel.writestr(name, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
            records.append((name, f"sha256={digest}", str(len(data))))

        for path in sorted((ROOT / "src" / "autodebug").rglob("*.py")):
            if "__pycache__" not in path.parts:
                add(path.relative_to(ROOT / "src").as_posix(), path.read_bytes())
        for name, data in _metadata().items():
            add(f"{DIST_INFO}/{name}", data)
        license_path = ROOT / "LICENSE"
        if license_path.is_file():
            add(f"{DIST_INFO}/LICENSE", license_path.read_bytes())
        record = io.StringIO(newline="")
        writer = csv.writer(record, lineterminator="\n")
        writer.writerows([*records, (f"{DIST_INFO}/RECORD", "", "")])
        wheel.writestr(f"{DIST_INFO}/RECORD", record.getvalue().encode("utf-8"))
    return filename


def build_sdist(sdist_directory, config_settings=None):
    filename = f"{NAME}-{VERSION}.tar.gz"
    destination = Path(sdist_directory)
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"{NAME}-{VERSION}"
    with tarfile.open(destination / filename, "w:gz") as archive:
        metadata = _metadata()["METADATA"]
        info = tarfile.TarInfo(f"{prefix}/PKG-INFO")
        info.size = len(metadata)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(metadata))
        paths = [ROOT / "pyproject.toml", ROOT / "build_backend.py", ROOT / "README.md", ROOT / "LICENSE"]
        paths.extend(sorted((ROOT / "src" / "autodebug").rglob("*.py")))
        for path in paths:
            if path.is_file() and "__pycache__" not in path.parts:
                archive.add(path, arcname=f"{prefix}/{path.relative_to(ROOT).as_posix()}", recursive=False)
    return filename
