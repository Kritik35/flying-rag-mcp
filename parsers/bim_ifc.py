from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import ifcopenshell
except ImportError:
    ifcopenshell = None  # type: ignore

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None  # type: ignore

# ---------------------------------------------------------------------------
# Types for IFC property-set extraction (оставлено без изменений)
# ---------------------------------------------------------------------------

TARGET_TYPES: tuple[str, ...] = (
    "IfcWall",
    "IfcColumn",
    "IfcBeam",
    "IfcSlab",
    "IfcDoor",
    "IfcWindow",
    "IfcStair",
    "IfcRailing",
    "IfcPlate",
    "IfcMember",
    "IfcBuildingElementProxy",
)


def extract_psets(model: Any) -> list[dict[str, Any]]:
    """Извлечь Property Sets для элементов TARGET_TYPES."""
    if ifcopenshell is None:
        return []

    results: list[dict[str, Any]] = []
    for ifc_type in TARGET_TYPES:
        elements = model.by_type(ifc_type)
        for elem in elements:
            psets = ifcopenshell.util.element.get_psets(elem)
            results.append(
                {"id": elem.id(), "type": ifc_type, "name": elem.Name, "psets": psets}
            )
    return results


# ---------------------------------------------------------------------------
# ParsedDocument (как в parsers/pdf.py)
# ---------------------------------------------------------------------------


@dataclass
class ParsedDocument:
    source_path: str
    file_name: str
    format: str
    text: str
    created_at: str
    modified_at: str
    extra: dict = field(default_factory=dict)


def _timestamps(path: Path) -> tuple[str, str]:
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    stat = path.stat()
    return fmt(stat.st_ctime), fmt(stat.st_mtime)


def _build_elements_table(model: Any) -> tuple[list[list[str]], int]:
    """Собрать таблицу элементов IFC для Markdown-представления."""
    rows: list[list[str]] = []
    headers = ["ID", "Type", "Name", "GlobalId", "ObjectType"]
    for ifc_type in TARGET_TYPES:
        elements = model.by_type(ifc_type)
        for elem in elements:
            rows.append(
                [
                    str(elem.id()),
                    ifc_type,
                    elem.Name or "",
                    elem.GlobalId or "",
                    elem.ObjectType or "",
                ]
            )
    return rows, len(rows)


def parse_ifc(path: Path) -> Any:
    """Открыть IFC-файл и вернуть модель ifcopenshell."""
    if ifcopenshell is None:
        raise ImportError(
            "ifcopenshell не установлен. Установите: pip install ifcopenshell"
        )
    return ifcopenshell.open(str(path))


# ---------------------------------------------------------------------------
# Main parse
# ---------------------------------------------------------------------------


def parse(path: Path) -> ParsedDocument:
    try:
        created_at, modified_at = _timestamps(path)
    except Exception as e:
        return ParsedDocument(
            source_path=str(path),
            file_name=path.name,
            format="ifc",
            text="",
            created_at="",
            modified_at="",
            extra={"error": str(e)},
        )

    try:
        model = parse_ifc(path)
        schema = getattr(model, "schema", "") or getattr(model, "schema_identifier", "")

        rows, count = _build_elements_table(model)
        if tabulate is not None:
            text = tabulate(rows, headers=["ID", "Type", "Name", "GlobalId", "ObjectType"], tablefmt="github")
        else:
            # fallback без tabulate — простой Markdown
            header = "| ID | Type | Name | GlobalId | ObjectType |\n|---|---|---|---|---|"
            body = "\n".join(f"| {' | '.join(r)} |" for r in rows)
            text = f"{header}\n{body}" if rows else header

        extra: dict[str, Any] = {
            "element_count": count,
            "schema": schema,
        }
    except Exception as e:
        text = ""
        extra = {"error": str(e)}

    return ParsedDocument(
        source_path=str(path),
        file_name=path.name,
        format="ifc",
        text=text,
        created_at=created_at,
        modified_at=modified_at,
        extra=extra,
    )


if __name__ == "__main__":
    import sys
    print("parsers/bim_ifc.py ready")
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            doc = parse(p)
            print(f"Format: {doc.format}")
            print(f"Elements: {doc.extra.get('element_count', 0)}")
            print(f"Schema: {doc.extra.get('schema', '?')}")
            print(f"Text preview ({len(doc.text)} chars):")
            print(doc.text[:500])
        else:
            print(f"File not found: {p}")
    else:
        print("Usage: python parsers/bim_ifc.py <path.ifc>")
