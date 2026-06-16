"""DWG парсер: ODA File Converter → ezdxf. Если ODA нет — метаданные."""
from __future__ import annotations
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ODA_PATH = Path(r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe")


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
    stat = path.stat()
    fmt = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return fmt(stat.st_ctime), fmt(stat.st_mtime)


def _dwg_to_dxf(dwg_path: Path, out_dir: Path) -> Path | None:
    """Конвертирует DWG → DXF через ODA File Converter."""
    try:
        subprocess.run(
            [str(ODA_PATH), str(dwg_path.parent), str(out_dir),
             "ACAD2018", "DXF", "0", "1", dwg_path.name],
            check=True, timeout=60, capture_output=True,
        )
        dxf = out_dir / dwg_path.with_suffix(".dxf").name
        return dxf if dxf.exists() else None
    except Exception:
        return None


def _read_dxf(dxf_path: Path) -> str:
    try:
        import ezdxf
        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        layers = [layer.dxf.name for layer in doc.layers]
        texts = [
            e.dxf.text for e in msp.query("TEXT MTEXT")
            if hasattr(e.dxf, "text") and e.dxf.text
        ]
        lines = [f"Файл: {dxf_path.stem}", f"Слои: {', '.join(layers[:20])}"]
        if texts:
            lines.append("Тексты:")
            lines.extend(f"  - {t[:120]}" for t in texts[:50])
        return "\n".join(lines)
    except Exception as e:
        return f"DWG: {dxf_path.stem}\n[Ошибка чтения DXF: {e}]"


def parse(path: Path) -> ParsedDocument:
    created_at, modified_at = _timestamps(path)

    if not ODA_PATH.exists():
        return ParsedDocument(
            source_path=str(path), file_name=path.name, format="dwg",
            text=f"DWG: {path.name}\n[Требуется ODA File Converter для извлечения текста]",
            created_at=created_at, modified_at=modified_at,
            extra={"oda_available": False},
        )

    with tempfile.TemporaryDirectory() as tmp:
        dxf = _dwg_to_dxf(path, Path(tmp))
        if dxf:
            text = _read_dxf(dxf)
            extra = {"oda_available": True, "method": "oda+ezdxf"}
        else:
            text = f"DWG: {path.name}\n[ODA конвертация не удалась]"
            extra = {"oda_available": True, "method": "oda_failed"}

    return ParsedDocument(
        source_path=str(path), file_name=path.name, format="dwg",
        text=text, created_at=created_at, modified_at=modified_at, extra=extra,
    )
