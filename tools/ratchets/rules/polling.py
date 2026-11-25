import re
from bisect import bisect_right
from pathlib import Path
from typing import NamedTuple

from ratchet import fingerprint, record_unique, source_files

ROOT = Path(__file__).resolve().parents[3]
SKIP_DIRS = frozenset({"node_modules", "__tests__", "__mocks__"})
TEST_FILE = re.compile(r"\.(test|spec)\.[jt]sx?$|^setupTests\.[jt]s$")
COMMENTS_AND_STRINGS = re.compile(
    r"//[^\n]*|/\*.*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`", re.S)
DECL = re.compile(r"\bfunction\s+(\w+)|\b(?:const|let|var)\s+(\w+)\s*(?::[^;=]*(?:=>[^;=]*)*)?=(?!>)")
METHOD = re.compile(r"(?m)^[ \t]*(?:(?:public|private|protected|static|async|override)\s+)*(\w+)\s*\([^()]*\)"
                    r"\s*(?::\s*[^{;=]+)?\{")
NOT_METHODS = frozenset({"if", "for", "while", "switch", "catch", "function", "return"})
TRIGGERS = (
    (re.compile(r"\bsetInterval\s*\("), "setInterval"),
    (re.compile(r"\brefetchInterval\b(?!\s*:\s*false\b)"), "refetchInterval"),
    (re.compile(r"\bnew\s+Promise\s*\([\s\S]{0,200}?\bsetTimeout\s*\("), "sleep"),
)
TIMEOUT = re.compile(r"\bsetTimeout\s*\(")
STATEMENT_OR_LINE_END = re.compile(r"[;\n]")
RESCHEDULING = "setTimeout re-scheduling itself"


class Scope(NamedTuple):
    name: str
    start: int
    end: int


def blank_comments_and_strings(text):
    return COMMENTS_AND_STRINGS.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def closing(code, start, open_ch, close_ch):
    depth = 0
    for i in range(start, len(code)):
        depth += (code[i] == open_ch) - (code[i] == close_ch)
        if depth == 0 and code[i] == close_ch:
            return i
    return len(code)


def block(code, brace):
    return brace, closing(code, brace, "{", "}")


def function_scopes(code):
    scopes = []
    for m in DECL.finditer(code):
        brace = code.find("{", m.end())
        head = code[m.end():brace]
        first_line = STATEMENT_OR_LINE_END.search(code, m.end())
        first_line_end = first_line.start() if first_line else len(code)
        if m.group(1):
            if brace != -1 and ";" not in head:
                scopes.append(Scope(m.group(1), *block(code, brace)))
        elif brace != -1 and brace < first_line_end and ("function" in head or head.rstrip().endswith("=>")):
            scopes.append(Scope(m.group(2), *block(code, brace)))
        elif "=>" in code[m.end():first_line_end]:
            scopes.append(Scope(m.group(2), m.end(), first_line_end))
    for m in METHOD.finditer(code):
        if m.group(1) not in NOT_METHODS:
            scopes.append(Scope(m.group(1), *block(code, m.end() - 1)))
    return scopes


def calls(name, args):
    return re.search(rf"(?<![\w$.])(?:this\.)?{re.escape(name)}\b", args) is not None


def self_rescheduling_timeouts(code):
    scopes = function_scopes(code)
    for m in TIMEOUT.finditer(code):
        args = code[m.end():closing(code, m.end() - 1, "(", ")")]
        if any(calls(s.name, args) for s in scopes if s.start < m.start() < s.end):
            yield m.start()


def loops_by_line_index(text):
    code = blank_comments_and_strings(text)
    newlines = [i for i, ch in enumerate(code) if ch == "\n"]
    hits = [(m.start(), kind) for pattern, kind in TRIGGERS for m in pattern.finditer(code)]
    hits += [(offset, RESCHEDULING) for offset in self_rescheduling_timeouts(code)]
    found = {}
    for offset, kind in hits:
        found.setdefault(bisect_right(newlines, offset), kind)
    return dict(sorted(found.items()))


def is_test(name):
    return TEST_FILE.search(name) is not None


def collect(root=ROOT):
    out = {}
    for rel, text in source_files(root, "frontend/src", (".ts", ".tsx", ".js", ".jsx"), SKIP_DIRS, is_test):
        lines = text.splitlines()
        for n, kind in loops_by_line_index(text).items():
            record_unique(out, fingerprint(rel, lines[n]), kind)
    return out
