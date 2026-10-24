"""Build and install the AutoDebug Bridge extension (ide-debug-bridge BR-12).

The `.vsix` is a ZIP in the same layout Microsoft's `vsce` produces, written
with the standard library only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

EXTENSION_DIR = Path(__file__).with_name("extension")
#: Files the extension needs at runtime: (source name, name inside the package).
_FILES = (("package.json", "package.json"), ("extension.js", "extension.js"),
          ("bridge-core.js", "bridge-core.js"), ("README.md", "readme.md"))
#: Command-line launchers of each IDE.
IDE_COMMANDS = {"vscode": "code", "cursor": "cursor"}

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension=".json" ContentType="application/json"/>'
    '<Default Extension=".vsixmanifest" ContentType="text/xml"/>'
    '<Default Extension=".js" ContentType="application/javascript"/>'
    '<Default Extension=".md" ContentType="text/markdown"/></Types>'
)


def manifest() -> dict:
    return json.loads((EXTENSION_DIR / "package.json").read_text(encoding="utf-8"))


def vsix_name() -> str:
    data = manifest()
    return f"{data['publisher']}.{data['name']}-{data['version']}.vsix"


def _vsixmanifest(data: dict) -> str:
    def attr(value: str) -> str:
        return escape(str(value), {'"': "&quot;", "'": "&apos;"})

    kinds = ",".join(data.get("extensionKind", ["workspace"]))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{attr(data['name'])}" Version="{attr(data['version'])}" Publisher="{attr(data['publisher'])}" />
    <DisplayName>{escape(data['displayName'])}</DisplayName>
    <Description xml:space="preserve">{escape(data['description'])}</Description>
    <Tags></Tags>
    <Categories>{escape(",".join(data.get('categories', [])))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{attr(data['engines']['vscode'])}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="{attr(kinds)}" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.EnabledApiProposals" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExecutesCode" Value="true" />
      <Property Id="Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown" Value="true" />
      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/readme.md" Addressable="true" />
  </Assets>
</PackageManifest>
"""


def build_vsix(destination_folder: Path) -> Path:
    """Write the extension package into `destination_folder` and return its path."""
    folder = Path(destination_folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / vsix_name()
    entries = [("extension.vsixmanifest", _vsixmanifest(manifest()).encode("utf-8")),
               ("[Content_Types].xml", _CONTENT_TYPES.encode("utf-8"))]
    entries += [(f"extension/{target}", (EXTENSION_DIR / source).read_bytes()) for source, target in _FILES]
    temporary = path.with_suffix(".vsix.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    temporary.replace(path)
    return path


def find_ide_command(ide: str) -> str | None:
    """The IDE's command-line launcher (`code` or `cursor`), if on PATH."""
    return shutil.which(IDE_COMMANDS[ide])


def install(ide: str, vsix: Path, *, command: str, timeout: float = 180) -> subprocess.CompletedProcess:
    return subprocess.run([command, "--install-extension", str(vsix), "--force"], capture_output=True, text=True,
                          timeout=timeout, check=False)
