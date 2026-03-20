import argparse
import os
import sys
import pandas as pd
import json


def main():
    parser = argparse.ArgumentParser(description='Convert CSV to ChatML JSONL')
    parser.add_argument('csv', nargs='?', default='instructions_raw.csv', help='Input CSV file (default: instructions_raw.csv)')
    parser.add_argument('--out', '-o', default='bystander_chatml.jsonl', help='Output JSONL file')
    args = parser.parse_args()

    csv_path = args.csv
    out_path = args.out

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        print("Place the CSV in the finetuning folder or pass a path, e.g.:\n  python3 parse_csv_to_chatml.py instructions_raw.csv")
        sys.exit(2)

    # Read CSV with a safe encoding and disable low_memory for mixed types
    df = pd.read_csv(csv_path, encoding='utf-8', low_memory=False)

    chatml_data = []

    for index, row in df.iterrows():
        # Safely pull fields using .get to avoid KeyError for missing columns
        facility = row.get('facility_type', '') if hasattr(row, 'get') else row['facility_type'] if 'facility_type' in row else ''
        severity = row.get('severity', '') if hasattr(row, 'get') else row['severity'] if 'severity' in row else ''
        case_th = row.get('Case Name (TH)', '') if hasattr(row, 'get') else row['Case Name (TH)'] if 'Case Name (TH)' in row else ''
        keywords = row.get('Keywords', '') if hasattr(row, 'get') else row['Keywords'] if 'Keywords' in row else ''
        instructions = row.get('Instructions', '') if hasattr(row, 'get') else row['Instructions'] if 'Instructions' in row else ''

        entry = {
            "messages": [
                {
                    "role": "system",
                    "content": f"You are an emergency assistant. Category: {facility}, Severity: {severity}."
                },
                {
                    "role": "user",
                    "content": f"แจ้งเหตุ: {case_th} หรือมีอาการ {keywords}"
                },
                {
                    "role": "assistant",
                    "content": instructions
                },
                {
                    "role": "assistant",
                    "content": f"Facility type: {facility}"
                },
                {
                    "role": "assistant",
                    "content": f"Severity: {severity}"
                }
            ]
        }

        chatml_data.append(entry)

    # Save to JSONL (standard format for AI fine-tuning)
    with open(out_path, 'w', encoding='utf-8') as f:
        for item in chatml_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()