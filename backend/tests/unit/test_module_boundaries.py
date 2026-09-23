"""Boundary rule 1 (spec §5.2): a module may import another module only through
its `service` or `schemas` submodule. import-linter covers the layering rules;
this test covers the per-module public-interface rule."""

import ast
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"
PUBLIC_SUBMODULES = {"service", "schemas"}


def _resolve_relative_module(node: ast.ImportFrom, package: str) -> str | None:
    """Resolve a relative `ImportFrom` (node.level > 0) to an absolute dotted
    module name, given the dotted package of the file it appears in."""
    pkg_parts = package.split(".")
    drop = node.level - 1
    if drop > 0:
        pkg_parts = pkg_parts[:-drop] if drop < len(pkg_parts) else []
    if node.module:
        return ".".join([*pkg_parts, node.module])
    return ".".join(pkg_parts) if pkg_parts else None


def _imported_names(node: ast.AST, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        module = node.module if node.level == 0 else _resolve_relative_module(node, package)
        if not module:
            return []
        if len(module.split(".")) == 3:  # from app.modules.x import y
            return [f"{module}.{alias.name}" for alias in node.names]
        return [module]
    return []


def find_boundary_violations(modules_root: Path) -> list[str]:
    violations = []
    for path in sorted(modules_root.rglob("*.py")):
        rel_parts = path.relative_to(modules_root).parts
        own_module = rel_parts[0]
        package = ".".join(["app", "modules", *rel_parts[:-1]])
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for name in _imported_names(node, package):
                parts = name.split(".")
                if parts[:2] != ["app", "modules"] or len(parts) < 3 or parts[2] == own_module:
                    continue
                if len(parts) == 3 or parts[3] not in PUBLIC_SUBMODULES:
                    rel = path.relative_to(modules_root).as_posix()
                    violations.append(f"{rel}: imports {name}")
    return violations


def test_checker_catches_private_imports(tmp_path: Path) -> None:
    (tmp_path / "roster").mkdir()
    (tmp_path / "roster" / "ok.py").write_text(
        "from app.modules.identity.service import CurrentActor\n"
        "from app.modules.identity import schemas\n"
        "from app.modules.roster.models import X\n"
        "from . import schemas\n"
        "from ..identity import service\n"
    )
    (tmp_path / "roster" / "bad.py").write_text(
        "from app.modules.identity.models import UserAccount\n"
        "from app.modules.identity import repository\n"
        "import app.modules.identity\n"
        "from ..identity.models import UserAccount\n"
        "from ..identity import repository\n"
    )

    assert find_boundary_violations(tmp_path) == [
        "roster/bad.py: imports app.modules.identity.models",
        "roster/bad.py: imports app.modules.identity.repository",
        "roster/bad.py: imports app.modules.identity",
        "roster/bad.py: imports app.modules.identity.models",
        "roster/bad.py: imports app.modules.identity.repository",
    ]


def test_application_modules_respect_boundaries() -> None:
    assert find_boundary_violations(MODULES_ROOT) == []
