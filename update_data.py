#!/usr/bin/env python3
"""
update_data.py — Update the data in index.html without touching the design.
Run this after scraping a new year instead of rebuild.py.

Usage:
    python update_data.py
"""
import json, gzip, base64, os, re, sys

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
HTML_FILE = os.path.join(os.path.dirname(__file__), 'index.html')

def main():
    # Load all year JSON files
    idx_path = os.path.join(DATA_DIR, 'index.json')
    if not os.path.exists(idx_path):
        print("ERROR: data/index.json not found. Run scrape.py first.")
        sys.exit(1)

    with open(idx_path) as f:
        index = json.load(f)

    all_data = {}
    for year in index['years']:
        path = os.path.join(DATA_DIR, f'{year}.json')
        if os.path.exists(path):
            with open(path) as f:
                all_data[year] = json.load(f)
            print(f"  Loaded {year}: {len(all_data[year]['draft_picks'])} picks")

    # Compress
    raw = json.dumps(all_data, separators=(',',':'))
    compressed = gzip.compress(raw.encode('utf-8'), compresslevel=9)
    new_b64 = base64.b64encode(compressed).decode('ascii')
    print(f"\n  Data: {len(raw)/1024:.1f} KB raw → {len(new_b64)/1024:.1f} KB compressed")

    # Update HTML
    with open(HTML_FILE) as f:
        html = f.read()

    # Replace the DATA_B64 value
    pattern = r'(const DATA_B64 = ")([^"]+)(")'
    if not re.search(pattern, html):
        print("ERROR: Could not find DATA_B64 in index.html")
        sys.exit(1)

    new_html = re.sub(pattern, lambda m: m.group(1) + new_b64 + m.group(3), html)

    # Update year options in the select dropdown
    years = sorted(all_data.keys(), reverse=True)
    options = '\n          '.join(
        f'<option value="{y}">{y} NFL Draft</option>' for y in years
    )
    new_html = re.sub(
        r'(<option value="">— Choose a Year —</option>\s*\n)([\s\S]*?)(\s*</select>)',
        lambda m: m.group(1) + '          ' + options + '\n        ' + m.group(3),
        new_html
    )

    with open(HTML_FILE, 'w') as f:
        f.write(new_html)

    print(f"  ✓ Updated index.html with {len(all_data)} years ({', '.join(str(y) for y in sorted(all_data.keys()))})")
    print(f"  File size: {len(new_html)/1024:.1f} KB")
    print(f"\n  Push to GitHub to publish:")
    print(f"    git add index.html && git commit -m 'Update draft data' && git push")

if __name__ == '__main__':
    print(f"\n{'='*50}")
    print(f"  NFL Draft Tracker — Data Updater")
    print(f"{'='*50}\n")
    main()
    print(f"\n{'='*50}\n")
