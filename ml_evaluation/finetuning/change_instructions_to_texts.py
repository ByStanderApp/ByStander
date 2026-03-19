import argparse
import csv
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, "instructions_raw_final.csv")
DEFAULT_OUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "docs", "csv_rows")

def slug(s):
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"[^0-9A-Za-zก-๙_\\-]", "", s)
    return s[:80] or "item"


def main():
    parser = argparse.ArgumentParser(description="Convert instructions CSV rows to text files.")
    parser.add_argument("--csv-path", default=DEFAULT_CSV_PATH, help="Path to source CSV")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory for text files")
    args = parser.parse_args()

    csv_path = os.path.abspath(args.csv_path)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    count = 0
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r, 1):
            title = row.get("Case Name (TH)", "") or row.get("Case Name (EN)", "") or f"case_{i}"
            text = (
                f"ชื่อเคส: {row.get('Case Name (TH)','')}\n"
                f"Keywords: {row.get('Keywords','')}\n"
                f"Severity: {row.get('severity','')}\n"
                f"Facility: {row.get('facility_type','')}\n\n"
                f"แนวทางปฐมพยาบาล:\n{row.get('Instructions','')}\n"
            )
            with open(os.path.join(out_dir, f"{i:04d}_{slug(title)}.txt"), "w", encoding="utf-8") as wf:
                wf.write(text)
            count += 1

    print(f"Done. Wrote {count} files to: {out_dir}")


if __name__ == "__main__":
    main()
