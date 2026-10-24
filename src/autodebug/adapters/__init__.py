"""The five IDE adapters (IDE-01). Each delegates to an injected,
IDE-specific client through the shared `ClientBackedAdapter`; none claims
verified native-debugger support (see docs/compatibility-ledger.md).
"""

from autodebug.adapters.base import BaseAdapter
from autodebug.adapters.clion import CLionAdapter
from autodebug.adapters.cursor import CursorAdapter
from autodebug.adapters.visual_studio import VisualStudioAdapter
from autodebug.adapters.vscode import VSCodeAdapter
from autodebug.adapters.xcode import XcodeAdapter

ALL_ADAPTERS = (
    VSCodeAdapter,
    CursorAdapter,
    CLionAdapter,
    VisualStudioAdapter,
    XcodeAdapter,
)

__all__ = [
    "BaseAdapter",
    "VSCodeAdapter",
    "CursorAdapter",
    "CLionAdapter",
    "VisualStudioAdapter",
    "XcodeAdapter",
    "ALL_ADAPTERS",
]
