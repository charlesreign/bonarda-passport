"""Boundary rule 1 (spec §5.2): a module may import another module only through
its `service` or `schemas` submodule. import-linter covers the layering rules;
this test covers the per-module public-interface rule."""

import ast
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"
PUBLIC_SUBMODULES = {"service", "schemas"}


def _imported_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        if len(node.module.split(".")) == 3:  # from app.modules.x import y
            return [f"{node.module}.{alias.name}" for alias in node.names]
        return [node.module]
    return []


def find_boundary_violations(modules_root: Path) -> list[str]:
    violations = []
    for path in sorted(modules_root.rglob("*.py")):
        own_module = path.relative_to(modules_root).parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for name in _imported_names(node):
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
    )
    (tmp_path / "roster" / "bad.py").write_text(
        "from app.modules.identity.models import UserAccount\n"
        "from app.modules.identity import repository\n"
        "import app.modules.identity\n"
    )

    assert find_boundary_violations(tmp_path) == [
        "roster/bad.py: imports app.modules.identity.models",
        "roster/bad.py: imports app.modules.identity.repository",
        "roster/bad.py: imports app.modules.identity",
    ]


def test_application_modules_respect_boundaries() -> None:
    assert find_boundary_violations(MODULES_ROOT) == []
