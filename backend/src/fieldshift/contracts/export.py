"""Write the machine-readable contracts handed to the team and the frontend."""

from __future__ import annotations

import json
from pathlib import Path

from fieldshift.contracts.bundle import schema_documents


def _dump(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def bundle_schema_texts() -> dict[str, str]:
    return {name: _dump(doc) for name, doc in schema_documents().items()}


def write_bundle_schemas(out_dir: Path) -> list[Path]:
    target = Path(out_dir) / "bundle"
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in bundle_schema_texts().items():
        path = target / name
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def openapi_text() -> str:
    from fieldshift.api.app import app

    return _dump(app.openapi())


def write_openapi(out_dir: Path) -> Path:
    path = Path(out_dir) / "openapi.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(openapi_text(), encoding="utf-8", newline="\n")
    return path


def write_all(out_dir: Path) -> list[Path]:
    written = write_bundle_schemas(out_dir)
    try:
        written.append(write_openapi(out_dir))
    except ImportError:
        pass  # the API package is not importable yet; bundle schemas are still written
    return written
