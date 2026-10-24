"""The five IDE adapters, declared from T01 as contract-conforming stubs
(IDE-01). Each conforms to the same `BaseAdapter` protocol; none claims real
native-debugger support until its proof task (T08–T12) lands.
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
