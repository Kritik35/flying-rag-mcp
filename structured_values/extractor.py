from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


DEFAULT_RECORD_PATTERN = re.compile(
    r"\b[А-ЯA-Z]{1,3}\d?-[А-ЯA-Z0-9]{2,}-\d{2}-\d{2}(?:\s*\([^)]{1,40}\))?\b",
    re.IGNORECASE,
)
NUMBER_UNIT_PATTERN = re.compile(
    r"(?P<value>-?\d+(?:[,.]\d+)?)\s*(?P<unit>Па|кПа|м3/ч|м³/ч|м/с|кВт|Вт|мм|м|кг|%)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedValue:
    record: str
    label: str
    value: float
    unit: str
    confidence: float
    evidence: str
    line_no: int


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\xa0", " ")).strip()


def _parse_number(line: str) -> tuple[float, str] | None:
    match = NUMBER_UNIT_PATTERN.search(line)
    if not match:
        return None
    try:
        value = float(match.group("value").replace(",", "."))
    except ValueError:
        return None
    return value, (match.group("unit") or "").strip()


def _contains_label(line: str, labels: Iterable[str]) -> str | None:
    lowered = line.casefold()
    for label in labels:
        if label.casefold() in lowered:
            return label
    return None


def extract_labeled_values(
    text: str,
    labels: list[str],
    record_pattern: re.Pattern[str] = DEFAULT_RECORD_PATTERN,
    lookahead_lines: int = 3,
) -> list[ExtractedValue]:
    lines = [_normalize_line(line) for line in text.splitlines()]
    rows: list[ExtractedValue] = []
    current_record = ""

    for index, line in enumerate(lines):
        if not line:
            continue

        record_match = record_pattern.search(line)
        if record_match:
            current_record = record_match.group(0)

        label = _contains_label(line, labels)
        if not label or not current_record:
            continue

        same_line_value = _parse_number(line)
        if same_line_value is not None and not record_pattern.search(line):
            value, unit = same_line_value
            rows.append(
                ExtractedValue(
                    record=current_record,
                    label=label,
                    value=value,
                    unit=unit,
                    confidence=0.82,
                    evidence=line,
                    line_no=index + 1,
                )
            )
            continue

        evidence_lines = [line]
        for offset in range(1, lookahead_lines + 1):
            if index + offset >= len(lines):
                break
            candidate = lines[index + offset]
            if not candidate:
                continue
            if record_pattern.search(candidate):
                break
            if _contains_label(candidate, labels):
                break
            evidence_lines.append(candidate)
            parsed = _parse_number(candidate)
            if parsed is None:
                continue
            value, unit = parsed
            rows.append(
                ExtractedValue(
                    record=current_record,
                    label=label,
                    value=value,
                    unit=unit,
                    confidence=0.88 if unit else 0.72,
                    evidence=" | ".join(evidence_lines),
                    line_no=index + offset + 1,
                )
            )
            break

    return rows
