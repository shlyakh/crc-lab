"""The upstream names crc-lab uses from crc-sdk and crc-framework, and which of them still exist.

    python tools/crc_surface.py list [--json]   # static: read src/ and tests/ with ast
    python tools/crc_surface.py check           # resolve every name in the installed packages

``list`` imports nothing from upstream. ``check`` imports upstream modules (no network) and exits 1
if any name is missing. Standard library only.

What is collected, per file:

- imports: ``import crc_sdk.x`` records ``crc_sdk.x``; ``from crc_sdk.x import a`` records
  ``crc_sdk.x.a``; imports inside functions count and bind in that function;
- names bound by those imports (and by ``m = importlib.import_module("crc_sdk.x")``), read later,
  with any attribute chain on them: ``provider.ERA5_STORES``, ``HazardDataset.crc_open``;
- string literals that are a whole dotted path under an upstream package
  (``monkeypatch.setattr("crc_sdk.workflows.ibtracs.urlopen", ...)``);
- ``(module, attribute)`` string pairs inside an assignment to ``OPTION_TABLES``
  (``src/data_source_check/adapters/crc/enumerate.py``).

Not resolved, only counted: attribute accesses on values that upstream code returned
(``plan.for_area(...).years(...)`` where ``plan = IBTrACSPlan(...)``), and parameters annotated with
an upstream type. Their target depends on runtime types.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.metadata
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGES = ("crc_sdk", "crc_framework")
SCANNED = ("src", "tests")
TABLE_NAMES = {"OPTION_TABLES"}
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def is_private(path: str) -> bool:
    """A component starts with an underscore; dunders such as ``__version__`` are public."""
    return any(
        p.startswith("_") and not (p.startswith("__") and p.endswith("__")) for p in path.split(".")
    )


def _upstream(path: str, packages: Iterable[str]) -> bool:
    return any(path == p or path.startswith(p + ".") for p in packages)


@dataclass
class Surface:
    #: dotted name -> sorted set of "file:line"
    names: dict[str, set[str]] = field(default_factory=dict)
    #: dotted paths known to be modules (from import statements and import_module strings)
    modules: set[str] = field(default_factory=set)
    #: "file:line attr" for attribute accesses on values returned by upstream code
    unresolved: list[str] = field(default_factory=list)
    files: int = 0

    def add(self, name: str, where: str) -> None:
        self.names.setdefault(name, set()).add(where)

    def module_of(self, name: str) -> str:
        """The module a name belongs to: a static guess, for grouping only.

        The longest prefix that is a known module or has no capitalised component (a class such
        as ``HazardDataset`` ends the module part). The name itself counts when it is a known
        module, or when it has no capitalised component and other names are reached through it
        (``from crc_sdk.providers import ghcnh`` then ``ghcnh.LICENCE``).
        """
        parts = name.split(".")
        has_children = any(n.startswith(name + ".") for n in self.names)
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            lower = not any(p[0].isupper() for p in parts[:i])
            if prefix in self.modules or (lower and (i < len(parts) or has_children)):
                return prefix
        return parts[0]


class _Scope:
    def __init__(self, is_class: bool = False) -> None:
        self.bound: dict[str, str] = {}  # local name -> upstream dotted path
        self.derived: set[str] = set()  # local names holding values returned by upstream code
        self.is_class = is_class


class _Collector(ast.NodeVisitor):
    def __init__(self, surface: Surface, rel: str, packages: tuple[str, ...]) -> None:
        self.s = surface
        self.rel = rel
        self.packages = packages
        self.scopes: list[_Scope] = [_Scope()]

    # -- scopes ---------------------------------------------------------------------------------

    def _visible(self) -> Iterator[_Scope]:
        yield self.scopes[-1]
        for scope in reversed(self.scopes[:-1]):
            if not scope.is_class:
                yield scope

    def _lookup(self, name: str) -> str | None:
        for scope in self._visible():
            if name in scope.bound:
                return scope.bound[name]
            if name in scope.derived:
                return None
        return None

    def _is_derived_name(self, name: str) -> bool:
        for scope in self._visible():
            if name in scope.derived:
                return True
            if name in scope.bound:
                return False
        return False

    def _prebind(self, body: list[ast.stmt]) -> None:
        """Bind this scope's imports before its body is read, so order inside the scope is moot."""
        for node in _own_statements(body):
            if isinstance(node, ast.Import | ast.ImportFrom):
                self._bind_import(node, record=False)

    def _where(self, node: ast.AST) -> str:
        return f"{self.rel}:{node.lineno}"

    # -- imports --------------------------------------------------------------------------------

    def _bind_import(self, node: ast.Import | ast.ImportFrom, record: bool) -> None:
        scope = self.scopes[-1]
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _upstream(alias.name, self.packages):
                    continue
                self.s.modules.add(alias.name)
                if alias.asname:
                    scope.bound[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    scope.bound[top] = top
                scope.derived.discard(alias.asname or alias.name.split(".")[0])
                if record:
                    self.s.add(alias.name, f"{self.rel}:{getattr(alias, 'lineno', node.lineno)}")
            return
        if node.level or not node.module or not _upstream(node.module, self.packages):
            return
        self.s.modules.add(node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            path = f"{node.module}.{alias.name}"
            local = alias.asname or alias.name
            scope.bound[local] = path
            scope.derived.discard(local)
            if record:
                self.s.add(path, f"{self.rel}:{getattr(alias, 'lineno', node.lineno)}")

    def visit_Import(self, node: ast.Import) -> None:
        self._bind_import(node, record=True)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._bind_import(node, record=True)

    # -- definitions ----------------------------------------------------------------------------

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        for d in getattr(node, "decorator_list", []):
            self.visit(d)
        args = node.args
        for default in [*args.defaults, *(d for d in args.kw_defaults if d is not None)]:
            self.visit(default)
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        every += [a for a in (args.vararg, args.kwarg) if a is not None]
        for a in every:
            if a.annotation is not None:
                self.visit(a.annotation)
        if getattr(node, "returns", None) is not None:
            self.visit(node.returns)  # type: ignore[arg-type]
        scope = _Scope()
        for a in every:
            if a.annotation is not None and self._annotation_is_upstream(a.annotation):
                scope.derived.add(a.arg)
        self.scopes.append(scope)
        if isinstance(node, ast.Lambda):
            self.visit(node.body)
        else:
            self._prebind(node.body)
            for stmt in node.body:
                self.visit(stmt)
        self.scopes.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function
    visit_Lambda = _visit_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expr in [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]:
            self.visit(expr)
        self.scopes.append(_Scope(is_class=True))
        self._prebind(node.body)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()

    def visit_Module(self, node: ast.Module) -> None:
        self._prebind(node.body)
        for stmt in node.body:
            self.visit(stmt)

    # -- names and attributes -------------------------------------------------------------------

    def _resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self._lookup(node.id)
        if isinstance(node, ast.Attribute):
            base = self._resolve(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    def _derived(self, node: ast.expr | None) -> bool:
        """The value of ``node`` came out of upstream code (a call, item or attribute of it)."""
        if node is None:
            return False
        if isinstance(node, ast.Name):
            return self._is_derived_name(node.id)
        if isinstance(node, ast.Call):
            return self._resolve(node.func) is not None or self._derived(node.func)
        if isinstance(node, ast.Attribute | ast.Subscript | ast.Starred):
            return self._derived(node.value)
        if isinstance(node, ast.Await):
            return self._derived(node.value)
        return False

    def _annotation_is_upstream(self, node: ast.expr) -> bool:
        return any(
            isinstance(n, ast.Name | ast.Attribute) and self._resolve(n) is not None
            for n in ast.walk(node)
        )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            path = self._lookup(node.id)
            if path:
                self.s.add(path, self._where(node))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        path = self._resolve(node)
        if path:
            self.s.add(path, self._where(node))
            return  # the whole chain is one name; its base is not recorded separately
        if self._derived(node.value):
            self.s.unresolved.append(f"{self._where(node)} .{node.attr}")
        self.visit(node.value)

    # -- strings --------------------------------------------------------------------------------

    def visit_Constant(self, node: ast.Constant) -> None:
        v = node.value
        if isinstance(v, str) and _DOTTED.match(v) and _upstream(v, self.packages):
            self.s.add(v, self._where(node))

    def visit_Call(self, node: ast.Call) -> None:
        # importlib.import_module("crc_sdk.x"): the string names a module
        func = node.func
        is_import_module = (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
            isinstance(func, ast.Name) and func.id == "import_module"
        )
        if is_import_module and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if _upstream(arg.value, self.packages):
                    self.s.modules.add(arg.value)
        self.generic_visit(node)

    # -- bindings that carry upstream values ----------------------------------------------------

    def _bind_targets(
        self, targets: Iterable[ast.expr], value: ast.expr | None, iterate: bool = False
    ) -> None:
        """Bind assignment targets; ``iterate``: the targets take items of ``value``, not itself."""
        scope = self.scopes[-1]
        module = None if iterate else _import_module_literal(value, self.packages)
        alias = self._resolve(value) if value is not None else None
        derived = self._derived(value) or (iterate and alias is not None)
        if iterate:
            alias = None
        for target in targets:
            for name in _target_names(target):
                scope.bound.pop(name, None)
                scope.derived.discard(name)
                if module:
                    scope.bound[name] = module
                elif alias:
                    scope.bound[name] = alias  # x = crc_sdk.workflows: another alias
                elif derived:
                    scope.derived.add(name)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for t in node.targets:
            self.visit(t)
        self._bind_targets(node.targets, node.value)
        if any(isinstance(t, ast.Name) and t.id in TABLE_NAMES for t in node.targets):
            self._table(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)
        value = node.value
        if value is None and self._annotation_is_upstream(node.annotation):
            if isinstance(node.target, ast.Name):
                self.scopes[-1].derived.add(node.target.id)
        else:
            self._bind_targets([node.target], value)
        if isinstance(node.target, ast.Name) and node.target.id in TABLE_NAMES and value:
            self._table(value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_targets([node.target], node.value)

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self._bind_targets([node.target], node.iter, iterate=True)
        for stmt in [*node.body, *node.orelse]:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind_targets([item.optional_vars], item.context_expr)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncWith = visit_With

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.visit(node.iter)
        self._bind_targets([node.target], node.iter, iterate=True)
        for cond in node.ifs:
            self.visit(cond)

    def _visit_comp(
        self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp
    ) -> None:
        for gen in node.generators:  # generators first: they bind the names the element reads
            self.visit(gen)
        for part in ("elt", "key", "value"):
            if hasattr(node, part):
                self.visit(getattr(node, part))

    visit_ListComp = _visit_comp
    visit_SetComp = _visit_comp
    visit_GeneratorExp = _visit_comp
    visit_DictComp = _visit_comp

    # -- the (module, attribute) table ----------------------------------------------------------

    def _table(self, node: ast.expr) -> None:
        for n in ast.walk(node):
            if isinstance(n, ast.Tuple) and len(n.elts) == 2:
                module, attr = n.elts
                if (
                    isinstance(module, ast.Constant)
                    and isinstance(attr, ast.Constant)
                    and isinstance(module.value, str)
                    and isinstance(attr.value, str)
                    and _upstream(module.value, self.packages)
                    and attr.value.isidentifier()
                ):
                    self.s.modules.add(module.value)
                    self.s.add(f"{module.value}.{attr.value}", self._where(attr))


def _own_statements(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Statements of a scope, without descending into nested functions or classes."""
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        stack.extend(c for c in ast.iter_child_nodes(node) if isinstance(c, ast.stmt))


def _target_names(target: ast.expr) -> Iterator[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Tuple | ast.List):
        for elt in target.elts:
            yield from _target_names(elt)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


def _import_module_literal(node: ast.expr | None, packages: tuple[str, ...]) -> str | None:
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    named = (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
        isinstance(func, ast.Name) and func.id == "import_module"
    )
    arg = node.args[0]
    if named and isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value if _upstream(arg.value, packages) else None
    return None


def collect(
    root: Path = REPO, dirs: Iterable[str] = SCANNED, packages: tuple[str, ...] = PACKAGES
) -> Surface:
    surface = Surface()
    for d in dirs:
        for path in sorted((root / d).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            _Collector(surface, path.relative_to(root).as_posix(), packages).visit(tree)
            surface.files += 1
    return surface


# -- output -------------------------------------------------------------------------------------


def installed_versions(packages: Iterable[str] = PACKAGES) -> dict[str, str]:
    out = {}
    for p in packages:
        dist = p.replace("_", "-")
        try:
            out[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            out[dist] = "not installed"
    return out


def _sort_uses(uses: Iterable[str]) -> list[str]:
    def key(u: str) -> tuple[str, int]:
        f, _, line = u.rpartition(":")
        return f, int(line)

    return sorted(uses, key=key)


def as_json(surface: Surface, packages: tuple[str, ...] = PACKAGES) -> dict:
    return {
        "versions": installed_versions(packages),
        "files": surface.files,
        "names": [
            {
                "name": name,
                "module": surface.module_of(name),
                "private": is_private(name),
                "uses": _sort_uses(uses),
            }
            for name, uses in sorted(surface.names.items())
        ],
        "unresolved_attribute_accesses": len(surface.unresolved),
        "unresolved": sorted(surface.unresolved),
    }


def as_markdown(surface: Surface, packages: tuple[str, ...] = PACKAGES) -> str:
    versions = ", ".join(f"{k} {v}" for k, v in installed_versions(packages).items())
    private = sum(is_private(n) for n in surface.names)
    lines = [
        "# Upstream names used by crc-lab",
        "",
        f"Generated by `python tools/crc_surface.py list` against {versions}.",
        "Do not edit: regenerate after a pin move; `just upstream-surface` checks the names.",
        "",
        f"{len(surface.names)} names ({private} private) in {surface.files} files under "
        f"{', '.join(f'`{d}/`' for d in SCANNED)}. "
        f"{len(surface.unresolved)} attribute accesses on values returned by upstream code were "
        "left unresolved (their target depends on runtime types; `--json` lists them).",
        "Modules are a static guess, for grouping only. A name is private if a component starts "
        "with `_` (dunders excepted).",
    ]
    groups: dict[str, list[str]] = {}
    for name in surface.names:
        groups.setdefault(surface.module_of(name), []).append(name)
    for module in sorted(groups):
        lines += ["", f"## `{module}`", "", "| Name | Private | Used at |", "| --- | --- | --- |"]
        for name in sorted(groups[module]):
            uses = ", ".join(_sort_uses(surface.names[name]))
            lines.append(f"| `{name}` | {'private' if is_private(name) else ''} | {uses} |")
    return "\n".join(lines) + "\n"


# -- check --------------------------------------------------------------------------------------


def resolve(name: str) -> str | None:
    """None if the name exists in the installed packages, else why not."""
    parts = name.split(".")
    obj = None
    for i in range(len(parts), 0, -1):
        prefix = ".".join(parts[:i])
        try:
            obj = importlib.import_module(prefix)
        except ModuleNotFoundError as error:
            if error.name and prefix.startswith(error.name):
                continue  # this prefix (or a parent) is not a module: try a shorter one
            return f"importing {prefix} failed: {error!r}"
        except Exception as error:  # an upstream module that fails to import
            return f"importing {prefix} failed: {error!r}"
        break
    else:
        return f"no module {parts[0]}"
    for j, attr in enumerate(parts[i:], start=i):
        try:
            obj = getattr(obj, attr)
        except AttributeError:
            return f"{'.'.join(parts[:j])} has no attribute {attr}"
    return None


def check(surface: Surface, packages: tuple[str, ...] = PACKAGES, out=None) -> int:
    out = out or sys.stdout
    for dist, version in installed_versions(packages).items():
        print(f"{dist} {version}", file=out)
    missing = {n: why for n in surface.names if (why := resolve(n)) is not None}
    print(
        f"{len(surface.names)} names checked, {len(missing)} missing "
        f"({len(surface.unresolved)} attribute accesses unresolved, not checked)",
        file=out,
    )
    for name in sorted(missing, key=lambda n: (not is_private(n), n)):
        tag = " [private]" if is_private(name) else ""
        print(f"\nMISSING {name}{tag}: {missing[name]}", file=out)
        for use in _sort_uses(surface.names[name]):
            print(f"  {use}", file=out)
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="names used, grouped by upstream module (static)")
    listing.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("check", help="resolve every name in the installed packages; exit 1 if missing")
    args = parser.parse_args(argv)
    surface = collect()
    if args.command == "list":
        if args.json:
            print(json.dumps(as_json(surface), indent=2))
        else:
            sys.stdout.write(as_markdown(surface))
        return 0
    return check(surface)


if __name__ == "__main__":
    sys.exit(main())
