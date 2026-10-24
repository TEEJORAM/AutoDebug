"""`autodebug setup`: package and install the extension, write the MCP entry."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

EXTENSION_DIR = Path(__file__).with_name("extension")
_FILES = (("package.json", "package.json"), ("extension.js", "extension.js"),
          ("bridge.js", "bridge.js"), ("README.md", "readme.md"))
#: Earlier extension IDs to remove so two versions never run side by side.
OLD_EXTENSIONS = ("autodebug.autodebug-bridge",)
SERVER_NAME = "autodebug"


def manifest() -> dict:
    return json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))


def extension_id() -> str:
    data = manifest()
    return f"{data['publisher']}.{data['name']}"


def build_vsix(folder: Path) -> Path:
    """Write the extension as a .vsix (the layout `vsce` produces) and return its path."""
    data = manifest()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{extension_id()}-{data['version']}.vsix"
    attr = lambda v: escape(str(v), {'"': "&quot;"})  # noqa: E731
    vsixmanifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{attr(data['name'])}" Version="{attr(data['version'])}" Publisher="{attr(data['publisher'])}" />
    <DisplayName>{escape(data['displayName'])}</DisplayName>
    <Description xml:space="preserve">{escape(data['description'])}</Description>
    <Tags></Tags>
    <Categories>{escape(','.join(data.get('categories', [])))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{attr(data['engines']['vscode'])}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="{attr(','.join(data.get('extensionKind', ['workspace'])))}" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExecutesCode" Value="true" />
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/readme.md" Addressable="true" />
  </Assets>
</PackageManifest>
"""
    content_types = ('<?xml version="1.0" encoding="utf-8"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension=".json" ContentType="application/json"/>'
                     '<Default Extension=".vsixmanifest" ContentType="text/xml"/>'
                     '<Default Extension=".js" ContentType="application/javascript"/>'
                     '<Default Extension=".md" ContentType="text/markdown"/></Types>')
    entries = [("extension.vsixmanifest", vsixmanifest.encode()), ("[Content_Types].xml", content_types.encode())]
    entries += [(f"extension/{target}", (EXTENSION_DIR / source).read_bytes()) for source, target in _FILES]
    temporary = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    temporary.replace(path)
    return path


def ide_command(ide: str) -> str | None:
    """The IDE's command-line launcher: PATH first, then the default install places."""
    name = {"cursor": "cursor", "vscode": "code"}[ide]
    found = shutil.which(name)
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = {
        "cursor": [local / "Programs" / "cursor" / "resources" / "app" / "bin" / "cursor.cmd",
                   Path("/Applications/Cursor.app/Contents/Resources/app/bin/cursor")],
        "vscode": [local / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                   Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft VS Code" / "bin" / "code.cmd",
                   Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")],
    }[ide]
    return next((str(p) for p in candidates if str(p) not in (".", "") and p.is_file()), None)


def install_extension(command: str, vsix: Path) -> subprocess.CompletedProcess:
    for old in OLD_EXTENSIONS:
        subprocess.run([command, "--uninstall-extension", old], capture_output=True, text=True, timeout=120, check=False)
    return subprocess.run([command, "--install-extension", str(vsix), "--force"], capture_output=True, text=True,
                          timeout=300, check=False)


# -- MCP configuration ------------------------------------------------------------


def server_entry(ide: str) -> dict:
    """How the IDE starts this server: this Python, with `src` on the path when run from a checkout."""
    entry: dict = {"type": "stdio", "command": sys.executable, "args": ["-m", "autodebug", "serve"]}
    package = Path(__file__).resolve().parent
    if (package.parent.name == "src") and (package.parents[1] / "pyproject.toml").is_file():
        entry["env"] = {"PYTHONPATH": str(package.parent)}
    return entry


def config_file(ide: str, folder: str | None = None) -> Path:
    if folder:
        return Path(folder).expanduser().resolve() / (".cursor" if ide == "cursor" else ".vscode") / "mcp.json"
    if ide == "cursor":
        return Path.home() / ".cursor" / "mcp.json"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Code" / "User" / "mcp.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "Code" / "User" / "mcp.json"


def _top_key(ide: str) -> str:
    return "mcpServers" if ide == "cursor" else "servers"


def read_config(path: Path) -> dict:
    """Read an MCP config, tolerating a BOM or UTF-16 (Windows PowerShell)."""
    if not path.exists():
        return {}
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{path} is not plain JSON (it may contain comments); add the entry by hand") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def write_config(ide: str, folder: str | None = None) -> Path:
    """Add or replace the `autodebug` entry, keeping every other server."""
    path = config_file(ide, folder)
    data = read_config(path)
    servers = data.setdefault(_top_key(ide), {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path}: {_top_key(ide)} is not an object")
    servers[SERVER_NAME] = server_entry(ide)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def configured_entry(ide: str, folder: str | None = None) -> dict | None:
    try:
        entry = read_config(config_file(ide, folder)).get(_top_key(ide), {}).get(SERVER_NAME)
    except (OSError, ValueError, AttributeError):
        return None
    return entry if isinstance(entry, dict) else None
