"""Standard-library PEP 517 backend: builds AutoDebug without downloading anything."""

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
NAME, VERSION = PROJECT["name"], PROJECT["version"]
DIST_INFO = f"{NAME}-{VERSION}.dist-info"
PACKAGE = ROOT / "src" / "autodebug"


def _package_files() -> list[Path]:
    """Python modules plus the extension sources the wheel must carry."""
    files = [p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts]
    files += [p for p in (PACKAGE / "extension").glob("*") if p.suffix in (".js", ".json", ".md")]
    return sorted(files)


def _metadata() -> dict[str, bytes]:
    scripts = "\n".join(f"{name} = {target}" for name, target in PROJECT.get("scripts", {}).items())
    headers = [f"Metadata-Version: 2.1", f"Name: {NAME}", f"Version: {VERSION}", f"Summary: {PROJECT['description']}",
               f"Requires-Python: {PROJECT['requires-python']}"]
    if PROJECT.get("license"):
        headers.append(f"License: {PROJECT['license']}")
    headers += [f"Classifier: {c}" for c in PROJECT.get("classifiers", [])]
    headers += [f"Project-URL: {label}, {url}" for label, url in PROJECT.get("urls", {}).items()]
    readme = (ROOT / PROJECT["readme"]).read_text(encoding="utf-8") if PROJECT.get("readme") else ""
    if readme:
        headers.append("Description-Content-Type: text/markdown")
    return {
        "METADATA": ("\n".join(headers) + "\n\n" + readme).encode("utf-8"),
        "WHEEL": b"Wheel-Version: 1.0\nGenerator: autodebug\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        "entry_points.txt": f"[console_scripts]\n{scripts}\n".encode(),
    }


def _wheel(directory: str, editable: bool) -> str:
    filename = f"{NAME}-{VERSION}-py3-none-any.whl"
    records = []
    with zipfile.ZipFile(Path(directory) / filename, "w", zipfile.ZIP_DEFLATED) as wheel:
        def add(name: str, data: bytes) -> None:
            wheel.writestr(name, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            records.append((name, f"sha256={digest}", str(len(data))))

        if editable:
            add(f"__editable__.{NAME}.pth", f"{ROOT / 'src'}\n".encode())
        else:
            for path in _package_files():
                add(path.relative_to(ROOT / "src").as_posix(), path.read_bytes())
        for name, data in _metadata().items():
            add(f"{DIST_INFO}/{name}", data)
        record = io.StringIO()
        csv.writer(record, lineterminator="\n").writerows([*records, (f"{DIST_INFO}/RECORD", "", "")])
        wheel.writestr(f"{DIST_INFO}/RECORD", record.getvalue())
    return filename


def get_requires_for_build_wheel(config_settings=None):
    return []


get_requires_for_build_editable = get_requires_for_build_sdist = get_requires_for_build_wheel


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    folder = Path(metadata_directory) / DIST_INFO
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in _metadata().items():
        (folder / name).write_bytes(data)
    return DIST_INFO


prepare_metadata_for_build_editable = prepare_metadata_for_build_wheel


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    return _wheel(wheel_directory, editable=False)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    return _wheel(wheel_directory, editable=True)


def build_sdist(sdist_directory, config_settings=None):
    filename = f"{NAME}-{VERSION}.tar.gz"
    prefix = f"{NAME}-{VERSION}"
    with tarfile.open(Path(sdist_directory) / filename, "w:gz") as archive:
        metadata = _metadata()["METADATA"]
        info = tarfile.TarInfo(f"{prefix}/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        for path in [ROOT / "pyproject.toml", ROOT / "build_backend.py", ROOT / "README.md", ROOT / "LICENSE",
                     *_package_files()]:
            archive.add(path, arcname=f"{prefix}/{path.relative_to(ROOT).as_posix()}", recursive=False)
    return filename
