#!/usr/bin/env python3
"""Convert Nasdaq 100 xlsx history exports to CSV.

This intentionally has no backtest logic. Run this first, then pass the CSV to
scripts/invest_backtest.py.
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


DEFAULT_SOURCE = Path("基金/纳指100/SODHist_19850131-20260430_NDX.xlsx")


def parse_excel_date(value: str) -> str:
    return (date(1899, 12, 30) + timedelta(days=int(float(value)))).isoformat()


def xlsx_column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if match is None:
        raise ValueError(f"invalid cell reference: {cell_ref}")
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def xlsx_shared_strings(zip_file: ZipFile) -> list[str]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.findall("m:si", ns):
        strings.append("".join(text.text or "" for text in item.findall(".//m:t", ns)))
    return strings


def read_first_xlsx_sheet(path: Path) -> list[list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as zip_file:
        shared_strings = xlsx_shared_strings(zip_file)
        root = ET.fromstring(zip_file.read("xl/worksheets/sheet1.xml"))

    rows: list[list[str]] = []
    for row in root.findall(".//m:sheetData/m:row", ns):
        values: dict[int, str] = {}
        for cell in row.findall("m:c", ns):
            value_node = cell.find("m:v", ns)
            value = "" if value_node is None else value_node.text or ""
            if cell.attrib.get("t") == "s" and value:
                value = shared_strings[int(value)]
            values[xlsx_column_index(cell.attrib["r"])] = value
        if values:
            rows.append([values.get(index, "") for index in range(max(values) + 1)])
    return rows


def is_all_zero_or_blank(values: list[str]) -> bool:
    for value in values:
        value = value.strip()
        if not value:
            continue
        try:
            if float(value) != 0.0:
                return False
        except ValueError:
            return False
    return True


def drop_all_zero_columns(header: list[str], rows: list[list[str]], *, required_columns: set[str]) -> tuple[list[str], list[list[str]]]:
    keep_indexes = []
    for index, name in enumerate(header):
        column_values = [row[index] for row in rows]
        if name in required_columns or not is_all_zero_or_blank(column_values):
            keep_indexes.append(index)

    return (
        [header[index] for index in keep_indexes],
        [[row[index] for index in keep_indexes] for row in rows],
    )


def convert_nasdaq_xlsx_to_csv(source: Path, output: Path) -> Path:
    rows = read_first_xlsx_sheet(source)
    if not rows:
        raise SystemExit(f"empty xlsx: {source}")

    header = rows[0]
    try:
        date_col = header.index("Trade Date")
    except ValueError as exc:
        raise SystemExit(f"{source} missing column: Trade Date") from exc

    output_rows = []
    for row in rows[1:]:
        normalized = row + [""] * (len(header) - len(row))
        normalized = normalized[: len(header)]
        if not any(normalized):
            continue
        if normalized[date_col]:
            normalized[date_col] = parse_excel_date(normalized[date_col])
        output_rows.append(normalized)

    header, output_rows = drop_all_zero_columns(
        header,
        output_rows,
        required_columns={"Trade Date", "Index Value"},
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(output_rows)

    print(f"wrote: {output}")
    print(f"summary: rows={len(output_rows):,}, columns={', '.join(header)}")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Nasdaq 100 xlsx history to CSV.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=None, help="defaults to source path with .csv suffix")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or args.source.with_suffix(".csv")
    convert_nasdaq_xlsx_to_csv(args.source, output)


if __name__ == "__main__":
    main()
