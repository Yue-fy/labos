"""Bounded, read-only source evidence from locally registered directories."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from .files import atomic_write, contains_credential, json_bytes
from .models import Identifier, Model

MAX_EVIDENCE_BYTES = 12288
MAX_FILE_BYTES = 1048576


class SourceContextError(ValueError):
    pass


class SourceRequest(Model):
    root: Identifier
    path: str = Field(min_length=1, max_length=512)
    kind: Literal["read", "outline", "index"] = "read"
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


def shorten(text, limit):
    return text.encode("utf-8")[:max(0, limit)].decode("utf-8", errors="ignore")


def opened_path(fd):
    """Resolve the open handle itself, never a separately checked pathname."""
    if sys.platform == "linux":
        return Path(os.readlink(f"/proc/self/fd/{fd}"))
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        function = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
        function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        function.restype = wintypes.DWORD
        handle = msvcrt.get_osfhandle(fd)
        size = function(handle, None, 0, 0)
        if not 0 < size < 32768:
            raise SourceContextError("Cannot verify the opened source handle")
        buffer = ctypes.create_unicode_buffer(size + 1)
        actual = function(handle, buffer, len(buffer), 0)
        if not 0 < actual < len(buffer):
            raise SourceContextError("Cannot verify the opened source handle")
        path = buffer.value
        if path.startswith("\\\\?\\UNC\\"):
            path = "\\\\" + path[8:]
        elif path.startswith("\\\\?\\"):
            path = path[4:]
        return Path(path)
    raise SourceContextError("Handle-verified source reading supports Windows and Linux")


@contextmanager
def open_confined(path, root):
    """Check the opened regular file before reading a byte, including parent swaps."""
    fd = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(fd).st_mode) or not opened_path(fd).is_relative_to(root):
            raise SourceContextError("Opened source file is outside its registered root or not regular")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            yield handle
    except OSError:
        raise SourceContextError("Cannot open a confined source file") from None
    finally:
        if fd is not None:
            os.close(fd)


class ReadOnlySources:
    def __init__(self, roots):
        self.roots = {}
        for label, path in roots.items():
            resolved = Path(path).resolve()
            if not resolved.is_dir():
                raise SourceContextError(f"Registered source root is unavailable: {label}")
            self.roots[label] = resolved

    def resolve(self, request):
        root = self.roots.get(request.root)
        if root is None:
            raise SourceContextError(f"Source root is not registered: {request.root}")
        relative = PurePosixPath(request.path.replace("\\", "/"))
        if (relative.is_absolute() or PureWindowsPath(request.path).drive
                or ".." in relative.parts or "\x00" in request.path):
            raise SourceContextError("Source paths must stay relative to a registered root")
        candidate = root
        for part in relative.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise SourceContextError("Source paths must not follow symlinks")
        path = candidate.resolve()
        if not path.is_relative_to(root):
            raise SourceContextError("Source path leaves its registered root")
        return path

    def one(self, request, guard=None):
        check = guard or (lambda: None)
        check()
        path = self.resolve(request)
        check()
        evidence = {"root": request.root, "path": request.path.replace("\\", "/"),
                    "kind": request.kind, "truncated": False}
        if request.kind == "index":
            if not path.is_dir():
                raise SourceContextError("Source index requires a directory")
            listing, pending = [], [path]
            scan = {"entries": 0, "directories": 1, "opened_directories": 0, "limit": None}
            while pending and scan["limit"] is None:
                check()
                directory = pending.pop()
                if directory.is_symlink() or not directory.resolve().is_relative_to(self.roots[request.root]):
                    raise SourceContextError("Source index directory left its registered root")
                check()
                scan["opened_directories"] += 1
                with os.scandir(directory) as entries:
                    while True:
                        check()
                        if scan["entries"] >= 10000:
                            scan["limit"] = "entries"
                            break
                        entry = next(entries, None)
                        if entry is None:
                            break
                        scan["entries"] += 1
                        check()
                        if entry.is_symlink():
                            continue
                        check()
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.startswith(".") or entry.name == "__pycache__":
                                continue
                            if scan["directories"] >= 1000:
                                scan["limit"] = "directories"
                                break
                            pending.append(Path(entry.path))
                            scan["directories"] += 1
                        elif Path(entry.name).suffix.lower() in {".py", ".md"}:
                            check()
                            file = Path(entry.path)
                            with open_confined(file, self.roots[request.root]):
                                check()
                            listing.append(file.relative_to(self.roots[request.root]).as_posix())
                            if len(listing) >= 250:
                                scan["limit"] = "matches"
                                break
            evidence["scan"] = scan
            evidence["truncated"] = scan["limit"] is not None
            evidence["content"] = "\n".join(sorted(listing))
        else:
            check()
            if path.suffix.lower() not in {".py", ".md"} or not path.is_file():
                raise SourceContextError(f"Only existing .py/.md source files may be read: {request.path}")
            try:
                check()
                with open_confined(path, self.roots[request.root]) as handle:
                    check()
                    data = handle.read(MAX_FILE_BYTES + 1)
                    check()
                if len(data) > MAX_FILE_BYTES:
                    raise SourceContextError("Source file exceeds the 1 MiB read limit")
                text = data.decode("utf-8-sig")
            except (OSError, UnicodeError):
                raise SourceContextError(f"Source file cannot be read as UTF-8: {request.path}") from None
            evidence["sha256"] = hashlib.sha256(data).hexdigest()
            if request.kind == "outline":
                if path.suffix.lower() != ".py":
                    raise SourceContextError("AST outlines require a Python source file")
                check()
                try:
                    tree = ast.parse(text)
                except (SyntaxError, RecursionError):
                    raise SourceContextError(f"Source file did not parse; it was not executed: {request.path}") from None
                evidence.update(self.outline(tree, check))
            else:
                check()
                lines = text.splitlines()
                end = min(request.end_line or request.start_line + 119, len(lines))
                if request.start_line > end or end - request.start_line >= 200:
                    raise SourceContextError("Request an existing line range of at most 200 lines")
                evidence.update(start_line=request.start_line, end_line=end)
                evidence["content"] = "\n".join(f"{i+1}: {lines[i]}" for i in range(request.start_line - 1, end))
        check()
        if len(evidence["content"].encode()) > 4096:
            evidence["content"] = shorten(evidence["content"], 4096)
            evidence["truncated"] = True
        return evidence

    @staticmethod
    def outline(tree, check):
        # Iterator frames retain only the active depth, never an entire child queue.
        stack = [(iter([tree]), "")]
        lines, size, imports = [], 0, 0
        scan = {"nodes": 0, "definitions": 0, "limit": None}
        truncated = False
        while stack:
            check()
            if scan["nodes"] >= 10000:
                scan["limit"] = "nodes"
                break
            children, prefix = stack[-1]
            node = next(children, None)
            if node is None:
                stack.pop()
                continue
            scan["nodes"] += 1
            line = None
            child_prefix = prefix
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if scan["definitions"] >= 250:
                    scan["limit"] = "definitions"
                    break
                scan["definitions"] += 1
                full_name = prefix + node.name
                name = shorten(full_name, 1024)
                truncated |= name != full_name
                child_prefix = name + "."
                if isinstance(node, ast.ClassDef):
                    line = f"class {name} [lines {node.lineno}-{node.end_lineno}]"
                else:
                    signature = ReadOnlySources.render_outline_node(node.args, check)
                    truncated |= signature is None
                    line = f"def {name}({signature if signature is not None else '<signature omitted: too large>'}) [lines {node.lineno}-{node.end_lineno}]"
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if imports < 80:
                    imports += 1
                    line = ReadOnlySources.render_outline_node(node, check)
                    if line is None:
                        line = "<import omitted: too large>"
                        truncated = True
                else:
                    truncated = True
            if line is not None:
                remaining = 4096 - size
                lines.append(shorten(line, remaining))
                size += len(lines[-1].encode()) + 1
                if size >= 4096:
                    scan["limit"] = "content"
                    break
            stack.append((ast.iter_child_nodes(node), child_prefix))
        return {"content": "\n".join(lines), "scan": scan,
                "truncated": truncated or scan["limit"] is not None}

    @staticmethod
    def render_outline_node(node, check):
        # Bound even the subtree sent to unparse; no giant argument/import rendering.
        stack, count, text_size = [iter([node])], 0, 0
        while stack:
            check()
            child = next(stack[-1], None)
            if child is None:
                stack.pop()
                continue
            count += 1
            if count > 256 or len(stack) > 32:
                return None
            for _, value in ast.iter_fields(child):
                if isinstance(value, (str, bytes)):
                    text_size += len(value)
            if text_size > 4096:
                return None
            stack.append(ast.iter_child_nodes(child))
        return ast.unparse(node)

    def collect(self, requests, guard=None):
        if not isinstance(requests, list) or not 1 <= len(requests) <= 6:
            raise SourceContextError("Request between one and six source excerpts")
        try:
            evidence = [self.one(SourceRequest.model_validate(r), guard) for r in requests]
        except ValidationError:
            raise SourceContextError("Invalid source request fields") from None
        while len(json.dumps(evidence, ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
            largest = max(evidence, key=lambda e: len(e["content"].encode()))
            size = len(largest["content"].encode())
            if not size:
                raise SourceContextError("Source request metadata exceeds the evidence limit")
            largest["content"] = shorten(largest["content"], size - 256)
            largest["truncated"] = True
        return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect approved .py/.md source text without importing it")
    parser.add_argument("--profile", choices=["worker", "program"], default="worker")
    parser.add_argument("--config", type=Path, required=True, help="local cooperation.yaml with registered source_roots")
    parser.add_argument("--requests", type=Path, required=True, help="JSON manifest containing requests and an optional instruction")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-task", action="store_true", help="prepare a report-only task for central automatic analysis")
    args = parser.parse_args(argv)
    try:
        from .cooperation_worker import Task, load_worker_config
        from .config import AgentConfig, CentralConfig, load_config
        if args.profile == "program":
            from .program_connector import load_program_config
            config = load_program_config(args.config)
        else:
            config = load_worker_config(args.config)
        request = json.loads(args.requests.read_text(encoding="utf-8-sig"))
        if not isinstance(request, dict):
            raise SourceContextError("The request manifest must be an object")
        evidence = ReadOnlySources(config.source_roots).collect(request["requests"])
        connection = load_config(config.connection_config, CentralConfig if config.role == "central" else AgentConfig)
        secrets = [connection.admin_token, *[a.token for a in connection.agents.values()]] if config.role == "central" else [connection.token]
        context = {"source_evidence": evidence, "collection_method": "read_text_and_ast_only_no_production_imports"}
        if contains_credential(context, secrets):
            raise SourceContextError("Credential found in source evidence; collection was not exported")
        output = context
        if args.as_task:
            instruction = request.get("instruction", "Review the approved source evidence and identify the smallest supported acquisition entry, initialization writes and missing dependencies. Do not execute production code or access hardware.")
            identity = hashlib.sha256(json_bytes({"context": context, "instruction": instruction})).hexdigest()[:32]
            output = {"protocol": "labos-agent-v1", "document_type": "labos_auto_task",
                      "task_id": "source-review-" + identity, "instruction": instruction,
                      "context": context, "executable": False}
            Task.model_validate(output)
        if contains_credential(output, secrets):
            raise SourceContextError("Credential found in output; collection was not exported")
        atomic_write(args.output, json_bytes(output))
        print(json.dumps({"output": str(args.output), "source_excerpts": len(evidence), "production_code_executed": False}))
        return 0
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        print("Source collection failed. Check registered roots, UTF-8 source paths, request fields and evidence limits.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
