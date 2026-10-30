"""Reading a stopped program's variables: scopes, paths such as mesh.verts[2].co, large arrays a page at a time,
hexadecimal values (docs/design.md, "Agent tools": inspect)."""

from __future__ import annotations

import re

from autodebug.connection import DebugError


def split_path(name: str) -> list[str]:
    """`mesh.verts[2].co` and `scene->objects[2]` as their parts."""
    parts = []
    for piece in str(name).replace("->", ".").split("."):
        parts += [a or b for a, b in re.findall(r"([^\[\].]+)|\[(\d+)\]", piece)]
    return [p for p in parts if p]


def _child_matches(child: dict, part: str) -> bool:
    name = str(child.get("name"))
    if name in (part, f"[{part}]"):
        return True
    # Debuggers number elements their own way: [5000], 5000, or debugpy's zero-padded 05000.
    digits = name.strip("[]")
    return part.isdigit() and digits.isdigit() and int(digits) == int(part)


#: Child entries that are not elements: debugpy's groups and its link to the next hundred elements.
_NOT_ELEMENTS = re.compile(r"(special|function|protected|class) variables|len\(\)|more|Raw View|\[Raw View\]")


_RANGE = re.compile(r"\[(\d+):(\d+)\]")


#: Scopes that are not the frame's own variables; inspect without names leaves them out.
_WIDE_SCOPE = re.compile(r"global|static|register|module|thread", re.IGNORECASE)


def _is_more(child: dict) -> bool:
    """debugpy lists a long list a hundred elements at a time, with a "more" child that holds the rest as ranges."""
    return child.get("type") == "MoreItems" or (child.get("name") == "more" and child.get("value") == "..."
                                                and bool(child.get("variablesReference")))


class Values:
    """Variable reading for Session: needs `s`, `_dap` and `_caps`."""

    def _frame_id(self, args: dict) -> int:
        s = self.s
        frame = args.get("frame")
        if isinstance(frame, int):
            return frame
        frames = self._dap("stackTrace", {"threadId": s["thread_id"], "startFrame": 0, "levels": 1}).get("stackFrames") or []
        if not frames:
            raise DebugError("NOT_FOUND", "the debugger shows no stack frame")
        return frames[0]["id"]

    def _format(self, args: dict) -> dict | None:
        if not args.get("hex"):
            return None
        self._need("supportsValueFormattingOptions", "show values in hex")
        return {"hex": True}

    def variables(self, args: dict) -> dict:
        """Variables of a frame. `scope` reads one scope by name (also the slow ones: globals, registers); `start`
        and `count` page through a large array or list; `hex` asks the debugger for hexadecimal values."""
        self.current("paused")
        frame = self._frame_id(args)
        fmt = self._format(args)
        wanted = [str(n) for n in args["names"]] if isinstance(args.get("names"), list) else None
        paging = args.get("start") is not None or args.get("count") is not None
        if paging and (not wanted or len(wanted) != 1):
            raise DebugError("BAD_REQUEST", "start and count page through one variable: pass exactly one name")
        scopes = self._dap("scopes", {"frameId": frame}).get("scopes") or []
        found = self._in_scopes(self._scopes_to_read(scopes, args.get("scope"), wanted), fmt,
                                500 if args.get("scope") else 200)
        if wanted is None:
            chosen = list(found.values())
        else:
            chosen = [{**v, "name": name} for name in wanted if (v := self._lookup(found, name, fmt)) is not None]
        if paging:
            start, count = max(0, int(args.get("start") or 0)), max(1, min(int(args.get("count") or 50), 200))
            shown = [self._page(v, start, count, fmt) for v in chosen]
        else:
            depth, budget = max(0, min(int(args.get("depth") or 0), 3)), {"nodes": 0}
            shown = [self._expand(v, depth, wanted is not None, budget, fmt) for v in chosen]
        return {"frame": frame, "variables": shown,
                "scopes": [{"name": sc.get("name"), "expensive": bool(sc.get("expensive"))} for sc in scopes]}

    @staticmethod
    def _scopes_to_read(scopes: list[dict], name: str | None, wanted: list[str] | None) -> list[dict]:
        """The scope named, else the fast scopes: for names all of them, without names the frame's own variables
        (gdb lists Arguments and Locals apart), not globals or registers."""
        if name:
            chosen = [sc for sc in scopes if str(sc.get("name", "")).lower() == str(name).lower()]
            if not chosen:
                raise DebugError("NOT_FOUND", f"no scope {name}; this frame has: "
                                              f"{', '.join(str(sc.get('name')) for sc in scopes) or 'none'}")
            return chosen
        fast = [sc for sc in scopes if not sc.get("expensive") and sc.get("variablesReference")]
        if wanted:
            return fast
        return [sc for sc in fast if not _WIDE_SCOPE.search(str(sc.get("name")))] or fast[:1]

    def _in_scopes(self, scopes: list[dict], fmt: dict | None, limit: int) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for scope in scopes:
            for variable in self._children(scope["variablesReference"], fmt)[:limit]:
                name = variable.get("name")
                if name not in found and not re.fullmatch(r"(special|function) variables", str(name)):
                    found[name] = variable
        return found

    def _children(self, reference: int, fmt: dict | None = None, start: int | None = None,
                  count: int | None = None, indexed: bool = False) -> list[dict]:
        request: dict = {"variablesReference": reference}
        if fmt:
            request["format"] = fmt
        if start is not None:
            request.update({"start": start, "count": count or 1})
            if indexed:
                request["filter"] = "indexed"
        return self._dap("variables", request).get("variables") or []

    def _child(self, parent: dict, part: str, fmt: dict | None) -> dict | None:
        """One child by name. An index into a large array is read on its own when the debugger pages, and found
        by following debugpy's "more" links otherwise."""
        if part.isdigit() and parent.get("indexedVariables"):
            for child in self._children(parent["variablesReference"], fmt, int(part), 1, indexed=True):
                if _child_matches(child, part):
                    return child
        if part.isdigit():
            found, _ = self._slice(parent["variablesReference"], int(part), int(part) + 1, fmt, [200])
            return found[0] if found else None
        return next((c for c in self._children(parent["variablesReference"], fmt) if _child_matches(c, part)), None)

    def _slice(self, reference: int, start: int, end: int, fmt: dict | None, budget: list[int]) -> tuple[list[dict], int | None]:
        """The elements with index start..end-1 of a list or array, and its length when the debugger says it.
        Follows debugpy's "more" child and its [a:b] ranges, reading only the ranges that hold those elements."""
        elements, total, position = [], None, 0
        for child in self._children(reference, fmt):
            name = str(child.get("name"))
            bounds = _RANGE.fullmatch(name)
            if _is_more(child) or (bounds and child.get("variablesReference")):
                if bounds and (int(bounds.group(2)) <= start or int(bounds.group(1)) >= end):
                    continue
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                elements += self._slice(child["variablesReference"], start, end, fmt, budget)[0]
                continue
            if name == "len()" and str(child.get("value")).isdigit():
                total = int(child["value"])
                continue
            if _NOT_ELEMENTS.fullmatch(name):
                continue
            digits = name.strip("[]")
            index = int(digits) if digits.isdigit() else position
            position += 1
            if start <= index < end:
                elements.append(child)
        return elements, total

    def _lookup(self, roots: dict[str, dict], name: str, fmt: dict | None = None) -> dict | None:
        parts = split_path(name)
        if not parts:
            return None
        current = roots.get(name) or roots.get(parts[0])
        if current is None:
            return None
        if name in roots:
            return current
        for part in parts[1:]:
            if not current.get("variablesReference"):
                return None
            current = self._child(current, part, fmt)
            if current is None:
                return None
        return current

    def _page(self, variable: dict, start: int, count: int, fmt: dict | None) -> dict:
        node = {"name": variable.get("name"), "type": variable.get("type") or "", "value": str(variable.get("value"))}
        if not variable.get("variablesReference"):
            return node
        total = variable.get("indexedVariables")
        if total:
            children = self._children(variable["variablesReference"], fmt, start, min(count, max(0, total - start)), True)
        else:
            children, known = self._slice(variable["variablesReference"], start, start + count, fmt, [200])
            total = known if known is not None else (len(children) + start if len(children) < count else None)
        node["children"] = [{"name": c.get("name"), "type": c.get("type") or "", "value": str(c.get("value")),
                             **({"expandable": True} if c.get("variablesReference") else {})} for c in children]
        node["page"] = {"start": start, "count": len(children), "total": total}
        return node

    def _expand(self, variable: dict, depth: int, named: bool, budget: dict, fmt: dict | None = None) -> dict:
        node = {"name": variable.get("name"), "type": variable.get("type") or "", "value": str(variable.get("value"))}
        if budget["nodes"] >= 1000:
            return {**node, "expandable": True}
        budget["nodes"] += 1
        if not variable.get("variablesReference"):
            return node
        if variable.get("indexedVariables"):
            node["size"] = variable["indexedVariables"]
        if depth <= 0:
            return {**node, "expandable": True}
        limit = 50 if named else 20
        if variable.get("indexedVariables"):
            children = self._children(variable["variablesReference"], fmt, 0, min(limit, variable["indexedVariables"]), True)
            total = variable["indexedVariables"] + (variable.get("namedVariables") or 0)
        else:
            children = self._children(variable["variablesReference"], fmt)
            total = len(children)
        node["children"] = []
        for child in children[:limit]:
            if budget["nodes"] >= 1000:
                break
            node["children"].append(self._expand(child, depth - 1, named, budget, fmt))
        if total > len(node["children"]):
            node["more"] = total - len(node["children"])
            node["expandable"] = True
        return node

    def _variable(self, name: str, frame: int) -> tuple[dict | None, int, str]:
        """A variable by path in `frame`: (it, the reference of the container that holds it, its name there)."""
        scopes = [sc for sc in self._dap("scopes", {"frameId": frame}).get("scopes") or [] if sc.get("variablesReference")]
        parts = split_path(name)
        if not parts:
            raise DebugError("BAD_REQUEST", f"{name!r} is not a variable name or path")
        for scope in scopes:
            if scope.get("expensive") and len(scopes) > 1:
                continue
            container = scope["variablesReference"]
            current = next((v for v in self._children(container) if v.get("name") == parts[0]), None)
            if current is None:
                continue
            for part in parts[1:]:
                if not current.get("variablesReference"):
                    return None, 0, ""
                container = current["variablesReference"]
                current = self._child(current, part, None)
                if current is None:
                    return None, 0, ""
            return current, container, current.get("name") or parts[-1]
        return None, 0, ""
