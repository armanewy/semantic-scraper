from __future__ import annotations

import ast
import fnmatch
import re
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
MISSING = object()
NON_LITERAL = object()
RANKER_REFERENCE_RE = re.compile(r"candidate-ranker-[A-Za-z0-9_-]+(?:\.json)?")


def main() -> int:
    errors = check_release_consistency(ROOT)
    if errors:
        for error in errors:
            print(f"release consistency error: {error}", file=sys.stderr)
        return 1
    print("Release consistency checks passed.")
    return 0


def check_release_consistency(root: Path) -> list[str]:
    errors: list[str] = []
    pyproject = _load_pyproject(root / "pyproject.toml", errors)
    project_version = _project_version(pyproject, errors)
    package_data = _semscrape_package_data(pyproject, errors)

    if "assets/*.json" not in package_data:
        errors.append("pyproject.toml must include semscrape package-data entry 'assets/*.json'")

    init_version = _literal_assignment(root / "src" / "semscrape" / "__init__.py", "__version__", root, errors)
    if init_version is not MISSING:
        if init_version is NON_LITERAL or not isinstance(init_version, str):
            errors.append("src/semscrape/__init__.py __version__ must be a string literal")
        elif project_version is not None and init_version != project_version:
            errors.append(f"pyproject project.version {project_version!r} != semscrape.__version__ {init_version!r}")

    default_ranker = _literal_assignment(root / "src" / "semscrape" / "assets.py", "DEFAULT_RANKER_NAME", root, errors)
    if default_ranker is NON_LITERAL or not isinstance(default_ranker, str):
        errors.append("src/semscrape/assets.py DEFAULT_RANKER_NAME must be a string literal")
        return errors
    if default_ranker is MISSING:
        errors.append("src/semscrape/assets.py must define DEFAULT_RANKER_NAME")
        return errors

    default_asset = root / "src" / "semscrape" / "assets" / default_ranker
    if not default_asset.is_file():
        errors.append(f"DEFAULT_RANKER_NAME points to missing asset: {default_asset.relative_to(root)}")

    asset_package_path = f"assets/{default_ranker}"
    if package_data and not any(fnmatch.fnmatch(asset_package_path, pattern) for pattern in package_data):
        errors.append(f"DEFAULT_RANKER_NAME {default_ranker!r} is not covered by pyproject package-data")

    _check_release_checklist(root / "RELEASE_CHECKLIST.md", default_ranker, errors)
    return errors


def _load_pyproject(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        errors.append("pyproject.toml is missing")
        return {}
    except tomllib.TOMLDecodeError as exc:
        errors.append(f"pyproject.toml is not valid TOML: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append("pyproject.toml did not parse to a table")
        return {}
    return data


def _project_version(pyproject: dict[str, Any], errors: list[str]) -> str | None:
    version = pyproject.get("project", {}).get("version")
    if not isinstance(version, str):
        errors.append("pyproject.toml must define [project].version as a string")
        return None
    return version


def _semscrape_package_data(pyproject: dict[str, Any], errors: list[str]) -> list[str]:
    raw = pyproject.get("tool", {}).get("setuptools", {}).get("package-data", {}).get("semscrape")
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append("pyproject.toml must define [tool.setuptools.package-data].semscrape as a string list")
        return []
    return raw


def _literal_assignment(path: Path, name: str, root: Path, errors: list[str]) -> object:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except FileNotFoundError:
        errors.append(f"{_display_path(path, root)} is missing")
        return MISSING
    except SyntaxError as exc:
        errors.append(f"{_display_path(path, root)} is not valid Python: {exc}")
        return MISSING

    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(_is_name(target, name) for target in node.targets):
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and _is_name(node.target, name):
            value_node = node.value

        if value_node is None:
            continue
        try:
            return ast.literal_eval(value_node)
        except (ValueError, SyntaxError):
            return NON_LITERAL
    return MISSING


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _check_release_checklist(path: Path, default_ranker: str, errors: list[str]) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        errors.append("RELEASE_CHECKLIST.md is missing")
        return

    for line_number, line in enumerate(lines, start=1):
        lowered = line.lower()
        if not ("packaged" in lowered or "default" in lowered or "src/semscrape/assets" in lowered):
            continue
        for reference in RANKER_REFERENCE_RE.findall(line):
            normalized = reference if reference.endswith(".json") else f"{reference}.json"
            if normalized != default_ranker:
                errors.append(
                    "RELEASE_CHECKLIST.md references "
                    f"{reference!r} on line {line_number}, but DEFAULT_RANKER_NAME is {default_ranker!r}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
