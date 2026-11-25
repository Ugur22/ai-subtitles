import ast
from pathlib import Path
from typing import NamedTuple

from ratchet import fingerprint, record_unique, source_files

ROOT = Path(__file__).resolve().parents[3]
HEAVY = frozenset({"torch", "torchaudio", "pyannote", "faster_whisper", "sentence_transformers", "transformers",
                   "insightface", "onnxruntime", "cv2", "librosa", "ctranslate2"})
SKIP_DIRS = frozenset({"tests", "venv", "node_modules", "graphify-out"})
MODULE = "<module>"


class ImportAtLoad(NamedTuple):
    node: ast.stmt
    scope: str


def heavy_names(node):
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    else:
        names = [node.module] if node.level == 0 and node.module else []
    return [n for n in names if n.split(".")[0] in HEAVY]


def type_checking(test):
    return getattr(test, "id", None) == "TYPE_CHECKING" or getattr(test, "attr", None) == "TYPE_CHECKING"


def imports_at_load(body, scope=MODULE):
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield ImportAtLoad(node, scope)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        elif isinstance(node, ast.ClassDef):
            yield from imports_at_load(node.body, node.name if scope == MODULE else f"{scope}.{node.name}")
        elif isinstance(node, ast.If) and type_checking(node.test):
            yield from imports_at_load(node.orelse, scope)
        else:
            for _, value in ast.iter_fields(node):
                for child in value if isinstance(value, list) else ():
                    if isinstance(child, ast.stmt):
                        yield from imports_at_load([child], scope)
                    elif isinstance(child, (ast.ExceptHandler, ast.match_case)):
                        yield from imports_at_load(child.body, scope)


def is_test(name):
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


class Module(NamedTuple):
    rel: str
    name: str
    is_package: bool
    lines: list
    imports: list


def parse(rel, text):
    parts = rel[len("backend/"):-len(".py")].split("/")
    is_package = parts[-1] == "__init__"
    name = ".".join(parts[:-1] if is_package else parts)
    return Module(rel, name, is_package, text.splitlines(), list(imports_at_load(ast.parse(text, filename=rel).body)))


def candidate_modules(node, module):
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    base = node.module or ""
    if node.level:
        parts = module.name.split(".")
        package = parts[:len(parts) - node.level + module.is_package]
        base = ".".join(package + ([base] if base else []))
    return [base] + [f"{base}.{a.name}" if base else a.name for a in node.names]


def collect(root=ROOT):
    modules = [parse(rel, text) for rel, text in source_files(root, "backend", (".py",), SKIP_DIRS, is_test)]
    directly_heavy_modules = {m.name for m in modules if any(heavy_names(i.node) for i in m.imports)}
    out = {}
    for m in modules:
        for node, scope in m.imports:
            heavy = heavy_names(node)
            via = [] if heavy else sorted(set(candidate_modules(node, m)) & directly_heavy_modules)
            if heavy or via:
                detail = ", ".join(heavy) if heavy else f"via {', '.join(via)}"
                record_unique(out, fingerprint(m.rel, m.lines[node.lineno - 1], scope), detail)
    return out
