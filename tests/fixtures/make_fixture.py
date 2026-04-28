"""Run once to (re)generate tests/fixtures/sample_retailers.xlsx."""

from pathlib import Path

from openpyxl import Workbook

NAMES = ["Target", "Best Buy", "Sephora", "B&H Photo", "Crate & Barrel"]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["name"])
    for n in NAMES:
        ws.append([n])
    out = Path(__file__).parent / "sample_retailers.xlsx"
    wb.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
