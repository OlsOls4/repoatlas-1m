"""Non-AI DocDrift baseline: check identifiers and call signatures in docs against the code's AST symbols.

Zero model calls. For each repository it:
  1. Builds a symbol table from the package's Python source with ``ast`` (modules, module-level names,
     re-exports and star-imports, classes with methods / class attributes / ``self.x`` attributes / bases,
     and function signatures).
  2. Extracts doc references from Markdown/RST docs and from Python docstrings:
     - Sphinx / MyST cross-reference roles (``:class:`X```, ``{func}`a.b```),
     - dotted names and calls in inline code and Python code blocks (incl. doctest ``>>>`` lines),
     - ``:param x:`` / Google ``Args:`` entries in docstrings,
     - exception-like names (``FooError``) in code blocks, inline code and roles.
  3. Flags references that cannot be resolved (missing module attribute / class attribute, unknown
     role target, exception name defined nowhere) and calls whose positional/keyword arguments cannot
     bind to any matching definition, plus documented params that are not in the signature.

Changelog / migration / release-note files are skipped (they legitimately mention removed names).
"""

from __future__ import annotations

import argparse
import ast
import builtins
import csv
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "build", "dist", "__pycache__", ".tox", ".nox", ".venv", "venv"}
NON_PACKAGE_DIRS = {"tests", "test", "testing", "docs", "doc", "examples", "example", "benchmarks", "bench", "scripts", ".github", "docs_src"}
HISTORY_FILE_PATTERN = re.compile(r"(change|history|news|release|upgrad|migrat|whatsnew|what_s_new|authors|contributing|code_of_conduct)", re.I)
STDLIB = set(getattr(sys, "stdlib_module_names", ()))
BUILTIN_NAMES = set(dir(builtins))
PY_LANGS = {"python", "py", "python3", "pycon", "pytb", "ipython", "default", ""}
ROLE_PATTERN = re.compile(r"(?::(?:py:)?(class|func|meth|attr|data|exc|obj|mod|const)|\{(?:py:)?(class|func|meth|attr|data|exc|obj|mod|const)\}):?`([^`]+)`")
EXC_NAME_PATTERN = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Error|Exception|Warning))\b")
DOTTED_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
PARAM_PATTERN = re.compile(r"^\s*:(?:param|parameter|arg|argument|keyword|kwarg)\s+(?:[^:]*\s)?\*{0,2}([A-Za-z_][A-Za-z0-9_]*)\s*:", re.M)
GOOGLE_HEADER = re.compile(r"^(\s*)(Args|Arguments|Parameters|Params|Keyword Args|Keyword Arguments):\s*$")


# ---------------------------------------------------------------- symbol table

@dataclass
class FuncSig:
    name: str
    posonly: list[str]
    args: list[str]
    kwonly: list[str]
    vararg: bool
    kwarg: bool
    vararg_name: str
    is_method: bool
    decorators: list[str]
    path: str
    line: int

    def accepts(self, n_pos: int, kw_names: list[str], bound: bool) -> str | None:
        """Return None when the call binds, else a reason string."""
        positional = self.posonly + self.args
        if bound and self.is_method and "staticmethod" not in self.decorators and positional:
            positional = positional[1:]
        posonly = [p for p in self.posonly if p in positional]
        if n_pos > len(positional) and not self.vararg:
            return f"{n_pos} positional args but signature takes {len(positional)}"
        filled = set(positional[:n_pos])
        allowed = set(positional) - set(posonly) | set(self.kwonly)
        for kw in kw_names:
            if kw in filled:
                return f"keyword '{kw}' would also be filled positionally (multiple values)"
            if kw not in allowed and not self.kwarg:
                return f"no parameter named '{kw}'"
        return None


@dataclass
class ClassInfo:
    name: str
    module: str
    path: str
    line: int
    attrs: set[str] = field(default_factory=set)
    methods: dict[str, list[FuncSig]] = field(default_factory=dict)
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    has_getattr: bool = False


@dataclass
class ModuleInfo:
    name: str
    path: str
    defs: dict[str, object] = field(default_factory=dict)  # name -> list[FuncSig] | ClassInfo | "var"
    imports: dict[str, str] = field(default_factory=dict)  # alias -> dotted target
    star_imports: list[str] = field(default_factory=list)
    has_getattr: bool = False
    dynamic_all: bool = False


def _dec_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _expr_dotted(node: ast.expr) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool, path: str) -> FuncSig:
    a = node.args
    return FuncSig(
        name=node.name,
        posonly=[x.arg for x in a.posonlyargs],
        args=[x.arg for x in a.args],
        kwonly=[x.arg for x in a.kwonlyargs],
        vararg=a.vararg is not None,
        kwarg=a.kwarg is not None,
        vararg_name=a.vararg.arg if a.vararg else "",
        is_method=is_method,
        decorators=[_dec_name(d) for d in node.decorator_list],
        path=path,
        line=node.lineno,
    )


class SymbolTable:
    def __init__(self, repo_root: Path) -> None:
        self.root = repo_root
        self.modules: dict[str, ModuleInfo] = {}
        self.universe: set[str] = set()  # every identifier / attribute / param / string-literal word in package code
        self.defined_names: set[str] = set()  # names of every def/class/module-level assignment/attribute
        self.methods_by_name: dict[str, list[tuple[ClassInfo, FuncSig]]] = {}
        self.functions: list[tuple[str, ast.AST, FuncSig | None, str]] = []  # (path, node, sig, module)
        self.trees: dict[str, ast.Module] = {}
        self.top_packages: set[str] = set()
        self._build()

    def _package_files(self) -> list[tuple[Path, str]]:
        out = []
        for path in sorted(self.root.rglob("*.py")):
            rel = path.relative_to(self.root)
            if any(p in SKIP_DIRS for p in rel.parts):
                continue
            parts = list(rel.parts)
            if parts[0] == "src":
                parts = parts[1:]
            if not parts or parts[0] in NON_PACKAGE_DIRS or len(parts) == 1 and parts[0] in {"setup.py", "noxfile.py", "conftest.py", "fabfile.py"}:
                continue
            if any(p in NON_PACKAGE_DIRS for p in parts[:-1]):
                continue
            # only importable packages / top-level modules
            if len(parts) > 1:
                pkg_dir = path.parent
                ok = True
                cur = pkg_dir
                top = self.root / "src" if (self.root / "src") in path.parents else self.root
                while cur != top:
                    if not (cur / "__init__.py").exists():
                        ok = False
                        break
                    cur = cur.parent
                if not ok:
                    continue
            mod_parts = parts[:-1] + ([] if parts[-1] == "__init__.py" else [parts[-1][:-3]])
            if not mod_parts:
                continue
            out.append((path, ".".join(mod_parts)))
        return out

    def _build(self) -> None:
        for path, modname in self._package_files():
            rel = str(path.relative_to(self.root))
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            self.trees[rel] = tree
            mod = ModuleInfo(name=modname, path=rel)
            self.modules[modname] = mod
            self.top_packages.add(modname.split(".")[0])
            is_pkg = path.name == "__init__.py"
            self._fill_module(mod, tree, rel, is_pkg)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    self.universe.add(node.id)
                elif isinstance(node, ast.Attribute):
                    self.universe.add(node.attr)
                elif isinstance(node, ast.arg):
                    self.universe.add(node.arg)
                elif isinstance(node, ast.keyword) and node.arg:
                    self.universe.add(node.arg)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.universe.add(node.name)
                    self.defined_names.add(node.name)
                elif isinstance(node, ast.alias):
                    self.universe.add((node.asname or node.name).split(".")[-1])
                    self.universe.update(node.name.split("."))
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
                    self.universe.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value))
        for mod in self.modules.values():
            for name in mod.name.split("."):
                self.universe.add(name)
                self.defined_names.add(name)

    def _fill_module(self, mod: ModuleInfo, tree: ast.Module, rel: str, is_pkg: bool) -> None:
        pkg_parts = mod.name.split(".") if is_pkg else mod.name.split(".")[:-1]

        def handle(body: list[ast.stmt]) -> None:
            for node in body:
                if isinstance(node, (ast.If, ast.Try)):
                    handle(node.body)
                    handle(getattr(node, "orelse", []))
                    for h in getattr(node, "handlers", []):
                        handle(h.body)
                    handle(getattr(node, "finalbody", []))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig = _sig(node, False, rel)
                    existing = mod.defs.get(node.name)
                    if isinstance(existing, list):
                        existing.append(sig)
                    else:
                        mod.defs[node.name] = [sig]
                    self.defined_names.add(node.name)
                    self.functions.append((rel, node, sig, mod.name))
                    if node.name == "__getattr__":
                        mod.has_getattr = True
                elif isinstance(node, ast.ClassDef):
                    mod.defs[node.name] = self._class(node, mod.name, rel)
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        for n in ast.walk(t):
                            if isinstance(n, ast.Name):
                                value = getattr(node, "value", None)
                                alias = _expr_dotted(value) if isinstance(value, (ast.Name, ast.Attribute)) else None
                                if alias:
                                    mod.imports.setdefault(n.id, "@local:" + alias)
                                mod.defs.setdefault(n.id, "var")
                                self.defined_names.add(n.id)
                                if n.id == "__all__" and not isinstance(value, (ast.List, ast.Tuple)):
                                    mod.dynamic_all = True
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        if a.asname:
                            mod.imports[a.asname] = a.name
                        else:
                            mod.imports.setdefault(a.name.split(".")[0], a.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    base = node.module.split(".") if node.module else []
                    if node.level:
                        prefix = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                        base = prefix + base
                    for a in node.names:
                        if a.name == "*":
                            mod.star_imports.append(".".join(base))
                        else:
                            mod.imports[a.asname or a.name] = ".".join(base + [a.name])

        handle(tree.body)

    def _class(self, node: ast.ClassDef, modname: str, rel: str) -> ClassInfo:
        info = ClassInfo(name=node.name, module=modname, path=rel, line=node.lineno)
        info.bases = [d for d in (_expr_dotted(b) for b in node.bases) if d]
        info.decorators = [_dec_name(d) for d in node.decorator_list]
        self.defined_names.add(node.name)
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = _sig(item, True, rel)
                if "staticmethod" in sig.decorators:
                    sig.is_method = False
                info.methods.setdefault(item.name, []).append(sig)
                info.attrs.add(item.name)
                self.methods_by_name.setdefault(item.name, []).append((info, sig))
                self.functions.append((rel, item, sig, modname))
                self.defined_names.add(item.name)
                if item.name in {"__getattr__", "__getattribute__"}:
                    info.has_getattr = True
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in {"self", "cls"} and isinstance(sub.ctx, ast.Store):
                        info.attrs.add(sub.attr)
                        self.defined_names.add(sub.attr)
            elif isinstance(item, ast.ClassDef):
                info.attrs.add(item.name)
                self._class(item, modname, rel)
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for t in targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            info.attrs.add(n.id)
                            self.defined_names.add(n.id)
            elif isinstance(item, (ast.If, ast.Try)):
                for sub in ast.walk(item):
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        info.attrs.add(sub.name)
                    elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                        info.attrs.add(sub.id)
        return info

    # ---------------------------------------------------------- resolution
    # Result: ("ok", obj) | ("missing", detail) | ("unknown", detail)
    def resolve(self, dotted: str, depth: int = 0) -> tuple[str, object]:
        parts = dotted.split(".")
        if parts[0] not in self.top_packages:
            return ("unknown", "not-package")
        if depth > 12:
            return ("unknown", "depth")
        cur: object = self.modules.get(parts[0])
        cur_name = parts[0]
        if cur is None:
            return ("unknown", "no-top")
        for i, part in enumerate(parts[1:], start=1):
            nxt = self._member(cur, part, depth)
            if nxt[0] != "ok":
                if nxt[0] == "missing":
                    return ("missing", f"'{part}' not found on {cur_name}")
                return nxt
            cur = nxt[1]
            cur_name = ".".join(parts[: i + 1])
        return ("ok", cur)

    def _member(self, cur: object, part: str, depth: int) -> tuple[str, object]:
        if isinstance(cur, ModuleInfo):
            sub = self.modules.get(f"{cur.name}.{part}")
            if part in cur.defs:
                d = cur.defs[part]
                if d == "var":
                    alias = cur.imports.get(part)
                    if alias and alias.startswith("@local:"):
                        target = alias[len("@local:"):]
                        first = target.split(".")[0]
                        if first in cur.imports and not cur.imports[first].startswith("@local:"):
                            target = cur.imports[first] + target[len(first):]
                            return self.resolve(target, depth + 1) if target.split(".")[0] in self.top_packages else ("unknown", "external")
                        if first in cur.defs and isinstance(cur.defs[first], ClassInfo):
                            return self.resolve(f"{cur.name}.{target}", depth + 1)
                    return ("unknown", "variable")
                return ("ok", d)
            if part in cur.imports:
                target = cur.imports[part]
                if target.startswith("@local:"):
                    return ("unknown", "variable")
                if target.split(".")[0] not in self.top_packages:
                    return ("unknown", "external")
                if target in self.modules:
                    return ("ok", self.modules[target])
                return self.resolve(target, depth + 1)
            if sub is not None:
                return ("ok", sub)
            for star in cur.star_imports:
                if star in self.modules:
                    r = self._member(self.modules[star], part, depth + 1)
                    if r[0] != "missing":
                        return r
                else:
                    return ("unknown", "external-star")
            if cur.has_getattr or cur.dynamic_all:
                return ("unknown", "module-getattr")
            return ("missing", part)
        if isinstance(cur, ClassInfo):
            if part in cur.attrs:
                if part in cur.methods:
                    return ("ok", cur.methods[part])
                return ("unknown", "class-attr")
            if cur.has_getattr:
                return ("unknown", "class-getattr")
            # attrs / dataclass / pydantic style fields declared via annotations are already in attrs.
            for base in cur.bases:
                base_obj = self._resolve_base(cur, base)
                if base_obj is None:
                    return ("unknown", "external-base")
                r = self._member(base_obj, part, depth + 1)
                if r[0] != "missing":
                    return r
            if part.startswith("__") and part.endswith("__"):
                return ("unknown", "dunder")
            return ("missing", part)
        return ("unknown", "non-container")

    def _resolve_base(self, cls: ClassInfo, base: str) -> ClassInfo | None:
        if base in {"object"}:
            return ClassInfo(name="object", module="builtins", path="", line=0)
        mod = self.modules.get(cls.module)
        if mod is None:
            return None
        first = base.split(".")[0]
        if first in mod.defs and isinstance(mod.defs[first], ClassInfo) and "." not in base:
            return mod.defs[first]
        target = None
        if first in mod.imports:
            target = mod.imports[first] + base[len(first):]
        if target and target.split(".")[0] in self.top_packages:
            r = self.resolve(target)
            if r[0] == "ok" and isinstance(r[1], ClassInfo):
                return r[1]
        return None

    def constructor_sigs(self, cls: ClassInfo, depth: int = 0) -> list[FuncSig] | None:
        if depth > 8:
            return None
        if "__init__" in cls.methods:
            return cls.methods["__init__"]
        if "__new__" in cls.methods:
            return cls.methods["__new__"]
        if any(d in {"define", "frozen", "mutable", "attrs", "s", "dataclass", "attr"} for d in cls.decorators):
            return None
        for base in cls.bases:
            b = self._resolve_base(cls, base)
            if b is None or b.name == "object":
                return None
            sigs = self.constructor_sigs(b, depth + 1)
            if sigs is not None:
                return sigs
        return None

    def name_defined_anywhere(self, name: str) -> bool:
        return name in self.defined_names or name in self.universe


# ---------------------------------------------------------------- doc extraction

@dataclass
class Fragment:
    path: str
    line: int  # 1-based line of the first fragment line in the file
    text: str
    kind: str  # "block" | "inline" | "role"
    role: str = ""


@dataclass
class Flag:
    repo: str
    path: str
    line: int
    check: str
    reference: str
    detail: str


def _strip_prompts(text: str) -> tuple[str, list[int]]:
    lines = text.split("\n")
    if any(l.lstrip().startswith(">>>") for l in lines):
        kept, idx = [], []
        for i, l in enumerate(lines):
            s = l.lstrip()
            if s.startswith(">>> ") or s == ">>>":
                kept.append(s[4:])
                idx.append(i)
            elif s.startswith("... ") or s == "...":
                kept.append(s[4:])
                idx.append(i)
        return "\n".join(kept), idx
    return text, list(range(len(lines)))


def extract_markdown(path: str, text: str, base_line: int = 1) -> list[Fragment]:
    frags: list[Fragment] = []
    lines = text.split("\n")
    in_block = False
    lang = ""
    fence = ""
    buf: list[str] = []
    start = 0
    for i, line in enumerate(lines, start=base_line):
        s = line.strip()
        m = re.match(r"^(\s*)(```+|~~~+)\s*\{?([A-Za-z0-9_+-]*)", line)
        if not in_block and m:
            in_block, fence, lang, buf, start = True, m.group(2), m.group(3).lower(), [], i + 1
            continue
        if in_block:
            if s.startswith(fence):
                if lang in PY_LANGS:
                    frags.append(Fragment(path, start, _dedent("\n".join(buf)), "block"))
                else:
                    # non-python blocks are still scanned for exception names
                    frags.append(Fragment(path, start, "\n".join(buf), "textblock"))
                in_block = False
            else:
                buf.append(line)
            continue
        frags.extend(_inline_fragments(path, i, line))
    return frags


def _dedent(text: str) -> str:
    import textwrap
    return textwrap.dedent(text)


def _inline_fragments(path: str, lineno: int, line: str) -> list[Fragment]:
    out: list[Fragment] = []
    for m in ROLE_PATTERN.finditer(line):
        out.append(Fragment(path, lineno, m.group(3), "role", m.group(1) or m.group(2)))
    stripped = ROLE_PATTERN.sub("", line)
    for m in re.finditer(r"``([^`]+)``|`([^`]+)`", stripped):
        val = m.group(1) or m.group(2)
        out.append(Fragment(path, lineno, val, "inline"))
    return out


def extract_rst(path: str, text: str, base_line: int = 1) -> list[Fragment]:
    frags: list[Fragment] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        lineno = base_line + i
        m = re.match(r"^(\s*)\.\.\s+(code-block|code|sourcecode|doctest|testcode|ipython)::\s*(\S*)", line)
        literal = line.rstrip().endswith("::") and not line.strip().startswith("..") and not m
        if m or literal:
            lang = (m.group(3).lower() if m else "python") if m else "python"
            indent = len(line) - len(line.lstrip())
            j = i + 1
            # skip options and blank lines
            while j < len(lines) and (not lines[j].strip() or re.match(r"^\s+:[\w-]+:", lines[j])):
                j += 1
            block: list[str] = []
            blk_start = j
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                block.append(lines[j])
                j += 1
            if block:
                kind = "block" if (lang in PY_LANGS or m and m.group(2) in {"doctest", "testcode"}) else "textblock"
                frags.append(Fragment(path, base_line + blk_start, _dedent("\n".join(block)), kind))
            if not literal:
                i = j
                continue
            frags.extend(_inline_fragments(path, lineno, line))
            i = j
            continue
        if line.lstrip().startswith(">>>"):
            j = i
            block = []
            while j < len(lines) and lines[j].strip():
                block.append(lines[j])
                j += 1
            frags.append(Fragment(path, lineno, _dedent("\n".join(block)), "block"))
            i = j
            continue
        frags.extend(_inline_fragments(path, lineno, line))
        i += 1
    return frags


# ---------------------------------------------------------------- checks

class Checker:
    def __init__(self, repo: str, table: SymbolTable) -> None:
        self.repo = repo
        self.t = table
        self.flags: list[Flag] = []
        self.stats = {"fragments": 0, "refs_checked": 0, "calls_checked": 0, "params_checked": 0}
        self._seen: set[tuple] = set()

    def flag(self, path: str, line: int, check: str, ref: str, detail: str) -> None:
        key = (path, line, check, ref)
        if key in self._seen:
            return
        self._seen.add(key)
        self.flags.append(Flag(self.repo, path, line, check, ref, detail))

    # dotted names ---------------------------------------------------
    def check_dotted(self, path: str, line: int, dotted: str, check: str) -> None:
        if dotted.split(".")[0] not in self.t.top_packages:
            return
        self.stats["refs_checked"] += 1
        status, detail = self.t.resolve(dotted)
        if status == "missing":
            self.flag(path, line, check, dotted, str(detail))
        elif status == "unknown" and detail in {"variable", "class-attr", "non-container"}:
            # Attribute of an instance/variable we cannot type: require the trailing names to exist somewhere.
            parts = dotted.split(".")
            for p in parts[1:]:
                if not self.t.name_defined_anywhere(p):
                    self.flag(path, line, check + ":name-not-in-code", dotted, f"'{p}' appears nowhere in package code")
                    break

    def check_role(self, frag: Fragment) -> None:
        target = frag.text.strip().lstrip("~!.").split("<")[-1].rstrip(">").strip()
        target = re.sub(r"\(\)$", "", target)
        if not re.match(r"^[A-Za-z_][\w.]*$", target):
            return
        if "." in target:
            if target.split(".")[0] in self.t.top_packages:
                self.check_dotted(frag.path, frag.line, target, "role")
            return
        if target in BUILTIN_NAMES or target in STDLIB:
            return
        self.stats["refs_checked"] += 1
        if frag.role in {"class", "exc", "func", "meth", "attr", "data", "obj", "const"} and not self.t.name_defined_anywhere(target):
            self.flag(frag.path, frag.line, "role:undefined", target, f":{frag.role}: target defined nowhere in package code")

    def check_exc_names(self, frag: Fragment, text: str) -> None:
        for m in EXC_NAME_PATTERN.finditer(text):
            name = m.group(1)
            if name in BUILTIN_NAMES:
                continue
            self.stats["refs_checked"] += 1
            if not self.t.name_defined_anywhere(name):
                self.flag(frag.path, frag.line + text[: m.start()].count("\n"), "exception-name:undefined", name, "exception-like name defined nowhere in package code")

    # code -----------------------------------------------------------
    def check_code(self, frag: Fragment) -> None:
        code, idx = _strip_prompts(frag.text)
        tree = None
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # fall back to statement-by-statement parsing of single lines
            stmts = []
            for k, l in enumerate(code.split("\n")):
                try:
                    t = ast.parse(l.strip())
                except SyntaxError:
                    continue
                for n in ast.walk(t):
                    if hasattr(n, "lineno"):
                        n.lineno = k + 1
                stmts.extend(t.body)
            tree = ast.Module(body=stmts, type_ignores=[])
        self._check_tree(frag, tree, idx)

    def _abs_line(self, frag: Fragment, idx: list[int], node: ast.AST) -> int:
        ln = getattr(node, "lineno", 1) - 1
        if 0 <= ln < len(idx):
            return frag.line + idx[ln]
        return frag.line

    def _check_tree(self, frag: Fragment, tree: ast.AST, idx: list[int]) -> None:
        aliases: dict[str, str] = {}
        local_defs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for a in node.names:
                    if a.name != "*":
                        aliases[a.asname or a.name] = f"{node.module}.{a.name}"
                        if node.module.split(".")[0] in self.t.top_packages:
                            self.check_dotted(frag.path, self._abs_line(frag, idx, node), f"{node.module}.{a.name}", "import")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local_defs.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                local_defs.add(node.id)
        # bare top-level package names are importable in doc snippets even without an import line
        for pkg in self.t.top_packages:
            aliases.setdefault(pkg, pkg)

        def to_package_dotted(expr: ast.expr) -> str | None:
            d = _expr_dotted(expr)
            if not d:
                return None
            first = d.split(".")[0]
            if first in local_defs and first not in aliases:
                return None
            if first in aliases and aliases[first].split(".")[0] in self.t.top_packages:
                return aliases[first] + d[len(first):]
            return None

        inner_attrs: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                inner_attrs.add(id(node.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and id(node) not in inner_attrs:
                d = to_package_dotted(node)
                if d:
                    self.check_dotted(frag.path, self._abs_line(frag, idx, node), d, "dotted")
            if isinstance(node, ast.Call):
                self._check_call(frag, idx, node, to_package_dotted, aliases, local_defs)

    def _check_call(self, frag, idx, node: ast.Call, to_package_dotted, aliases, local_defs) -> None:
        if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
            return
        # `f(url, ...)` is signature-summary notation, not a real call
        if any(isinstance(a, ast.Constant) and a.value is Ellipsis for a in node.args) or any(
            isinstance(k.value, ast.Constant) and k.value.value is Ellipsis for k in node.keywords
        ):
            return
        n_pos = len(node.args)
        kws = [k.arg for k in node.keywords]
        line = self._abs_line(frag, idx, node)
        d = to_package_dotted(node.func)
        if d:
            status, obj = self.t.resolve(d)
            if status != "ok":
                return
            sigs: list[FuncSig] | None = None
            bound = False
            if isinstance(obj, ClassInfo):
                sigs = self.t.constructor_sigs(obj)
                bound = True
            elif isinstance(obj, list):
                sigs = obj
                bound = any(s.is_method for s in sigs) and False
            if not sigs:
                return
            self.stats["calls_checked"] += 1
            reasons = [s.accepts(n_pos, kws, bound=bound or (isinstance(obj, ClassInfo))) for s in sigs]
            if all(r is not None for r in reasons):
                self.flag(frag.path, line, "call-signature", f"{d}(...)", f"{reasons[0]} (def {sigs[0].path}:{sigs[0].line})")
            return
        # method call on an untyped receiver: x.meth(...)
        if isinstance(node.func, ast.Attribute):
            recv = _expr_dotted(node.func.value)
            if recv is None:
                return
            first = recv.split(".")[0]
            if first in aliases and aliases[first].split(".")[0] not in self.t.top_packages:
                return  # receiver is an external module
            meth = node.func.attr
            cands = self.t.methods_by_name.get(meth, [])
            if not cands or meth.startswith("__"):
                return
            if len({c.name for c, _ in cands}) > 6:
                return  # very generic method name; too ambiguous
            self.stats["calls_checked"] += 1
            reasons = [s.accepts(n_pos, kws, bound=True) for _, s in cands]
            if all(r is not None for r in reasons):
                c, s = cands[0]
                self.flag(frag.path, line, "method-call-signature", f"{recv}.{meth}(...)", f"{reasons[0]}; no package method '{meth}' accepts it (e.g. {c.name}.{meth} at {s.path}:{s.line})")

    def check_inline(self, frag: Fragment) -> None:
        text = frag.text.strip()
        if not text or " " in text and "(" not in text:
            return
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError:
            return
        self._check_tree(frag, tree, [0])

    # docstring params ---------------------------------------------------
    def check_docstring_params(self) -> None:
        for rel, node, sig, modname in self.t.functions:
            doc = ast.get_docstring(node, clean=False)
            if not doc or sig is None:
                continue
            names = self._documented_params(doc)
            if not names:
                continue
            params = set(sig.posonly + sig.args + sig.kwonly)
            for name, offset in names:
                self.stats["params_checked"] += 1
                if name in params or sig.kwarg or (sig.vararg and name in {"args", sig.vararg_name}):
                    continue
                if name in {"self", "cls", "kwargs", "args"}:
                    continue
                if "overload" in sig.decorators:
                    continue
                line = node.body[0].lineno + offset if node.body else node.lineno
                self.flag(rel, line, "docstring-param", f"{sig.name}({name})", f"documented param '{name}' not in signature of {sig.name} ({rel}:{sig.line})")
        # class docstrings documenting __init__ params
        for rel, tree in self.t.trees.items():
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                doc = ast.get_docstring(node, clean=False)
                if not doc:
                    continue
                names = self._documented_params(doc)
                init = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
                if not names or init is None:
                    continue
                sig = _sig(init, True, rel)
                params = set(sig.posonly + sig.args + sig.kwonly)
                for name, offset in names:
                    self.stats["params_checked"] += 1
                    if name in params or sig.kwarg or (sig.vararg and name == sig.vararg_name):
                        continue
                    line = node.body[0].lineno + offset
                    self.flag(rel, line, "docstring-param", f"{node.name}.__init__({name})", f"class docstring documents '{name}', not a parameter of {node.name}.__init__ ({rel}:{init.lineno})")

    def _documented_params(self, doc: str) -> list[tuple[str, int]]:
        out = []
        for m in PARAM_PATTERN.finditer(doc):
            out.append((m.group(1), doc[: m.start()].count("\n") + (1 if doc[m.start()] == "\n" else 0)))
        lines = doc.split("\n")
        k = 0
        while k < len(lines):
            m = GOOGLE_HEADER.match(lines[k])
            if m:
                base = len(m.group(1))
                k += 1
                item_indent = None
                while k < len(lines):
                    l = lines[k]
                    if not l.strip():
                        k += 1
                        continue
                    ind = len(l) - len(l.lstrip())
                    if ind <= base:
                        break
                    if item_indent is None:
                        item_indent = ind
                    if ind == item_indent:
                        mm = re.match(r"^\s*\*{0,2}([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*:", l)
                        if mm:
                            out.append((mm.group(1), k))
                    k += 1
                continue
            k += 1
        return out


# ---------------------------------------------------------------- driver

def doc_files(repo_root: Path) -> list[Path]:
    out = []
    for p in sorted(repo_root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".md", ".rst"}:
            continue
        rel = p.relative_to(repo_root)
        if any(part in SKIP_DIRS or part in {"tests", "test", ".github"} for part in rel.parts):
            continue
        if HISTORY_FILE_PATTERN.search(p.name):
            continue
        out.append(p)
    return out


def run_repo(repo: str, repo_root: Path) -> tuple[list[Flag], dict]:
    table = SymbolTable(repo_root)
    checker = Checker(repo, table)
    frags: list[Fragment] = []
    for p in doc_files(repo_root):
        rel = str(p.relative_to(repo_root))
        text = p.read_text(encoding="utf-8", errors="replace")
        frags.extend(extract_markdown(rel, text) if p.suffix.lower() == ".md" else extract_rst(rel, text))
    # docstrings in package code
    for rel, tree in table.trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) and isinstance(node.body[0].value.value, str):
                    doc = node.body[0].value.value
                    start = node.body[0].lineno
                    frags.extend(extract_rst(rel, doc, base_line=start))
                    frags.extend(f for f in extract_markdown(rel, doc, base_line=start) if f.kind == "block")
    checker.stats["fragments"] = len(frags)
    for f in frags:
        if f.kind == "role":
            checker.check_role(f)
            checker.check_exc_names(f, f.text)
        elif f.kind == "block":
            checker.check_code(f)
            checker.check_exc_names(f, f.text)
        elif f.kind == "textblock":
            checker.check_exc_names(f, f.text)
        elif f.kind == "inline":
            checker.check_inline(f)
            checker.check_exc_names(f, f.text)
    checker.check_docstring_params()
    stats = dict(checker.stats, packages=sorted(table.top_packages), modules=len(table.modules), doc_files=len(doc_files(repo_root)))
    return checker.flags, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repos-root", type=Path, default=Path("/workspace/sweep"))
    ap.add_argument("--repos", default="starlette,httpx,click,attrs,pydantic-settings,structlog,jinja,nox,arrow,cattrs,marshmallow,werkzeug")
    ap.add_argument("--out-dir", type=Path, default=Path("results_live/baselines"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    all_flags: list[Flag] = []
    per_repo = {}
    for repo in args.repos.split(","):
        flags, stats = run_repo(repo, args.repos_root / repo)
        all_flags.extend(flags)
        per_repo[repo] = dict(stats, flags=len(flags))
        print(f"{repo}: {len(flags)} flags  {stats}", file=sys.stderr)
    (args.out_dir / "symbol_check_flags.json").write_text(json.dumps({"per_repo": per_repo, "flags": [asdict(f) for f in all_flags]}, indent=2))
    with (args.out_dir / "symbol_check_flags.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(asdict(all_flags[0]).keys()) if all_flags else ["repo"])
        w.writeheader()
        for f in all_flags:
            w.writerow(asdict(f))
    print(f"total flags: {len(all_flags)}", file=sys.stderr)


if __name__ == "__main__":
    main()
