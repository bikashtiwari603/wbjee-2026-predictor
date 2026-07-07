import csv
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_DIR = ROOT / 'counselling data csv files'
OUT_FILE = ROOT / 'wbjee_predictor_data.js'

YEAR_FILES = {
    2022: CSV_DIR / 'wbjee_2022.csv',
    2023: CSV_DIR / 'wbjee_2023.csv',
    2024: CSV_DIR / 'wbjee_2024.csv',
    2025: CSV_DIR / 'wbjee_2025.csv',
}


def detect_header(rows):
    for idx, row in enumerate(rows):
        if not row:
            continue
        lowered = [cell.strip().lower() for cell in row]
        if any('institute' in cell for cell in lowered) and any('program' in cell for cell in lowered) and any('category' in cell for cell in lowered):
            return idx
    raise ValueError('Could not locate CSV header row')


def normalize_text(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def normalize_key(value):
    return re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()


def parse_round(value):
    match = re.search(r'(\d+)', str(value or ''))
    return int(match.group(1)) if match else 1


def to_int(value):
    text = str(value or '').replace(',', '').strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def load_year_rows(year, path):
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.reader(fh))

    header_idx = detect_header(rows)
    header = [normalize_key(c) for c in rows[header_idx]]
    data_rows = []
    for row in rows[header_idx + 1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        item = {}
        for i, key in enumerate(header):
            if i < len(row):
                item[key] = normalize_text(row[i])
        if not item:
            continue
        data_rows.append(item)

    normalized = []
    for item in data_rows:
        institute = item.get('institute') or item.get('institute ▲▼') or ''
        program = item.get('program') or item.get('program ▲▼') or ''
        stream = item.get('stream') or item.get('stream ▲▼') or ''
        seat = item.get('seat type') or item.get('seat type ▲▼') or 'ANY'
        quota = item.get('quota') or item.get('quota ▲▼') or ''
        category = item.get('category') or item.get('category ▲▼') or ''
        opening = to_int(item.get('opening rank') or item.get('opening rank ▲▼'))
        closing = to_int(item.get('closing rank') or item.get('closing rank ▲▼'))
        round_no = parse_round(item.get('round') or item.get('round ▲▼'))
        if not institute or not program or not closing:
            continue
        normalized.append({
            'year': year,
            'round': round_no,
            'institute': institute,
            'program': program,
            'stream': stream,
            'seat': seat,
            'quota': quota,
            'category': category,
            'opening': opening,
            'closing': closing,
        })
    return normalized


def build_payload():
    rows_by_year = []
    for year, path in YEAR_FILES.items():
        if not path.exists():
            raise FileNotFoundError(path)
        rows_by_year.append(load_year_rows(year, path))

    institutions = []
    programs = []
    streams = []
    seats = []
    quotas = []
    categories = []

    def add_unique(values, value):
        if value is not None and value not in values:
            values.append(value)

    branch_map = {}
    for year_rows in rows_by_year:
        for row in year_rows:
            key = (
                row['institute'],
                row['program'],
                row['stream'],
                row['seat'],
                row['quota'],
                row['category'],
            )
            bucket = branch_map.setdefault(key, {})
            current = bucket.get(row['year'])
            if current is None or row['round'] > current['round']:
                bucket[row['year']] = {
                    'round': row['round'],
                    'closing': row['closing'],
                    'opening': row['opening'],
                }

            add_unique(institutions, row['institute'])
            add_unique(programs, row['program'])
            add_unique(streams, row['stream'])
            add_unique(seats, row['seat'])
            add_unique(quotas, row['quota'])
            add_unique(categories, row['category'])

    # Make the arrays stable and predictable for the UI.
    institutions.sort(key=lambda x: x.lower())
    programs.sort(key=lambda x: x.lower())
    streams.sort(key=lambda x: x.lower())
    seats.sort(key=lambda x: x.lower())
    quotas.sort(key=lambda x: x.lower())
    categories.sort(key=lambda x: x.lower())

    recs = []
    years = [2022, 2023, 2024, 2025]
    weights = [0.10, 0.20, 0.30, 0.40]

    for key in sorted(branch_map):
        inst, prog, stream, seat, quota, category = key
        values = []
        for year in years:
            entry = branch_map[key].get(year)
            if entry:
                values.append(entry['closing'])
            else:
                values.append(None)

        present = [(year, value) for year, value in zip(years, values) if value is not None]
        if not present:
            continue

        latest_year, latest_value = present[-1]
        if len(present) >= 2:
            prev_value = present[-2][1]
            if latest_value < prev_value:
                trend = 1
            elif latest_value > prev_value:
                trend = -1
            else:
                trend = 0
        else:
            trend = 0

        weighted_total = 0.0
        weight_total = 0.0
        for (year, value), weight in zip(present, [weights[years.index(y)] for y, v in present if v is not None]):
            weighted_total += value * weight
            weight_total += weight
        avg = round(weighted_total / weight_total) if weight_total else latest_value

        recs.append([
            institutions.index(inst),
            programs.index(prog),
            streams.index(stream),
            seats.index(seat),
            quotas.index(quota),
            categories.index(category),
            avg,
            latest_value,
            latest_year,
            trend,
            values[0],
            values[1],
            values[2],
            values[3],
        ])

    # Keep the list sorted by average closing rank for the UI.
    recs.sort(key=lambda r: r[6])

    return {
        'insts': institutions,
        'progs': programs,
        'streams': streams,
        'seats': seats,
        'quotas': quotas,
        'cats': categories,
        'recs': recs,
    }


def main():
    payload = build_payload()
    content = 'window.WBJEE_DATA = ' + json.dumps(payload, ensure_ascii=False, indent=2) + ';\n'
    OUT_FILE.write_text(content, encoding='utf-8')
    print(f'Wrote {OUT_FILE} with {len(payload["recs"])} records.')


if __name__ == '__main__':
    main()
