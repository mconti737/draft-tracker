#!/usr/bin/env python3
"""
NFL Draft Tracker - Data Scraper
Fetches draft + combine data from free public sources for 2015-current year.
Run once per year (after the draft) to update your data.

Sources (all free, no API key needed):
  - nflverse GitHub: draft picks, combine measurements  
  - ESPN Core API: decimal height, birth state, early entrant detection
"""

import requests, csv, io, json, time, os, sys
from datetime import datetime
from collections import defaultdict

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
CURRENT_YEAR = datetime.now().year
START_YEAR = 2015
OUT_DIR = os.path.join(os.path.dirname(__file__), "data")

DRAFT_URL   = "https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv"
COMBINE_URL = "https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv"
ESPN_DRAFT  = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{year}/draft/rounds?limit=10"

TEAM_MAP = {
    "ARI":"ARI","ATL":"ATL","BAL":"BAL","BUF":"BUF","CAR":"CAR","CHI":"CHI",
    "CIN":"CIN","CLE":"CLE","DAL":"DAL","DEN":"DEN","DET":"DET","GNB":"GB",
    "GB":"GB","HOU":"HOU","IND":"IND","JAX":"JAX","JAC":"JAX","KAN":"KC",
    "KC":"KC","LAC":"LAC","LAR":"LAR","LVR":"LV","LV":"LV","MIA":"MIA",
    "MIN":"MIN","NWE":"NE","NE":"NE","NOR":"NO","NO":"NO","NYG":"NYG",
    "NYJ":"NYJ","PHI":"PHI","PIT":"PIT","SEA":"SEA","SFO":"SF","SF":"SF",
    "TAM":"TB","TB":"TB","TEN":"TEN","WAS":"WSH","WSH":"WSH","OAK":"LV",
    "SDG":"LAC","STL":"LAR",
}

WC_STATES = {"CA","OR","WA","NV","AZ","UT","ID","HI","AK"}

def log(msg): print(f"  {msg}", flush=True)

def get(url, retries=3, delay=1.0):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return r
            time.sleep(delay * (i+1))
        except Exception as e:
            if i == retries-1: raise
            time.sleep(delay)
    return None

def ht_to_decimal(ht_str):
    """Convert '6-1' or '5-11' to decimal inches."""
    if not ht_str: return None
    parts = str(ht_str).split('-')
    if len(parts) == 2:
        try: return int(parts[0]) * 12 + float(parts[1])
        except: pass
    try: return float(ht_str)
    except: return None

def val(v):
    """Return float or None."""
    if v is None or v == '': return None
    try: return float(v)
    except: return None

def fetch_nflverse():
    """Download draft picks and combine data from nflverse."""
    log("Downloading nflverse draft picks...")
    rd = get(DRAFT_URL)
    if not rd:
        raise RuntimeError("Failed to download draft picks from nflverse")
    
    log("Downloading nflverse combine data...")
    rc = get(COMBINE_URL)
    if not rc:
        raise RuntimeError("Failed to download combine data from nflverse")
    
    # Parse draft picks
    picks_by_year = defaultdict(list)
    for row in csv.DictReader(io.StringIO(rd.text)):
        yr = int(row['season'])
        if yr < START_YEAR: continue
        team_raw = row['team']
        picks_by_year[yr].append({
            'team': TEAM_MAP.get(team_raw, team_raw),
            'round': int(row['round']),
            'pick': int(row['pick']),
            'position': row['position'],
            'name': row['pfr_player_name'],
            'college': row['college'],
            'pfr_id': row['pfr_player_id'],
        })
    
    # Parse combine data — keyed by (year, name)
    combine_by_key = {}
    for row in csv.DictReader(io.StringIO(rc.text)):
        yr = row['draft_year']
        name = row['player_name']
        combine_by_key[(yr, name)] = {
            'ht_rough': ht_to_decimal(row.get('ht')),
            'wt': val(row.get('wt')),
            'forty': val(row.get('forty')),
            'vertical': val(row.get('vertical')),
            'broad': val(row.get('broad_jump')),
            'shuttle': val(row.get('shuttle')),
            'cone': val(row.get('cone')),
            'school': row.get('school',''),
        }
    
    log(f"Draft picks loaded: {sum(len(v) for v in picks_by_year.values())} across {len(picks_by_year)} years")
    log(f"Combine entries loaded: {len(combine_by_key)}")
    return picks_by_year, combine_by_key

def fetch_espn_year(year):
    """Fetch ESPN draft data for one year: decimal height, birth state, early entrant."""
    log(f"  ESPN: fetching {year} draft...")
    url = ESPN_DRAFT.format(year=year)
    r = get(url)
    if not r: return {}
    
    data = r.json()
    espn_map = {}  # name -> {ht, hs_state, is_early_entrant, college_name}
    
    all_picks = []
    for rnd in data.get('items', []):
        for pick in rnd.get('picks', []):
            all_picks.append(pick)
    
    for pick in all_picks:
        try:
            athlete_url = pick['athlete']['$ref'].replace('http://','https://')
            r2 = get(athlete_url, delay=0.15)
            if not r2: continue
            d = r2.json()
            
            name = d.get('fullName','')
            ht = d.get('height')  # decimal inches
            wt = d.get('weight')
            
            # Get inner athlete for birthPlace + experience
            inner_ref = d.get('athlete',{}).get('$ref','').replace('http://','https://')
            hs_state = None
            is_early = False
            college_name = d.get('team',{})
            
            if inner_ref:
                r3 = get(inner_ref, delay=0.15)
                if r3:
                    d3 = r3.json()
                    bp = d3.get('birthPlace',{})
                    hs_state = bp.get('state','') or bp.get('country','')
                    exp = d3.get('experience',{}).get('displayValue','').lower()
                    is_early = 'sophomore' in exp or 'junior' in exp or 'freshman' in exp
                    # Get college name
                    cref = d3.get('college',{}).get('$ref','').replace('http://','https://')
                    if cref:
                        r4 = get(cref, delay=0.1)
                        if r4 and r4.status_code == 200:
                            college_name = r4.json().get('name','')
            
            espn_map[name] = {
                'ht': float(ht) if ht else None,
                'wt_espn': float(wt) if wt else None,
                'hs_state': hs_state,
                'is_early_entrant': is_early,
                'college_espn': college_name if isinstance(college_name, str) else '',
            }
            time.sleep(0.1)
            
        except Exception as e:
            continue
    
    log(f"  ESPN: got data for {len(espn_map)} players in {year}")
    return espn_map

def build_year_data(year, picks, combine_map, espn_map):
    """Merge all sources into final player records for one year."""
    merged = []
    
    conf_counts = defaultdict(int)
    pos_avg = defaultdict(lambda: defaultdict(list))
    
    for p in sorted(picks, key=lambda x: (x['round'], x['pick'])):
        name = p['name']
        yr_str = str(year)
        
        # Combine data
        c = combine_map.get((yr_str, name), {})
        # ESPN data
        e = espn_map.get(name, {})
        
        # Height: ESPN decimal > nflverse rough
        ht = e.get('ht') or c.get('ht_rough')
        
        # Detect transfer from college name containing "via" or multiple schools
        college = p['college']
        is_transfer = bool(college and (' via ' in college.lower() or college.count(',') >= 1))
        
        # Conference detection from college name
        conf = detect_conference(college, year)
        conf_counts[conf] += 1
        
        # HS state from ESPN birthPlace
        hs_state = e.get('hs_state','')
        
        player = {
            'team': p['team'],
            'round': p['round'],
            'pick': p['pick'],
            'position': normalize_pos(p['position']),
            'name': name,
            'high_school': '',  # not available from free sources
            'hs_state': hs_state or '',
            'college': college,
            'height_inches': round(ht, 3) if ht else None,
            'weight': int(c.get('wt') or e.get('wt_espn') or 0) or None,
            'hand': None,   # not available free
            'arm': None,    # not available free
            'wingspan': None, # not available free
            'forty': c.get('forty'),
            'vertical': c.get('vertical'),
            'broad': int(c.get('broad')) if c.get('broad') else None,
            'shuttle': c.get('shuttle'),
            'cone': c.get('cone'),
            'conference': conf,
            'recruiting_stars': None,  # not available free
            'is_transfer': is_transfer,
            'is_early_entrant': e.get('is_early_entrant', False),
            'is_west_coast': hs_state in WC_STATES if hs_state else False,
        }
        merged.append(player)
        
        # Accumulate for averages
        pos = player['position']
        if player['height_inches']: pos_avg[pos]['ht'].append(player['height_inches'])
        if player['weight']:        pos_avg[pos]['wt'].append(player['weight'])
        if player['forty']:         pos_avg[pos]['forty'].append(player['forty'])
        if player['vertical']:      pos_avg[pos]['vertical'].append(player['vertical'])
        if player['broad']:         pos_avg[pos]['broad'].append(player['broad'])
        if player['shuttle']:       pos_avg[pos]['shuttle'].append(player['shuttle'])
    
    # Build averages
    def avg(lst): return round(sum(lst)/len(lst), 3) if lst else None
    avg_by_pos = {}
    for pos, fields in pos_avg.items():
        avg_by_pos[pos] = {k: avg(v) for k,v in fields.items()}
    
    combine_summary = {
        'total_participants': sum(1 for p in merged if p['forty'] or p['vertical']),
        'by_conference': dict(sorted(conf_counts.items(), key=lambda x:-x[1])),
        'avg_by_position': avg_by_pos,
    }
    
    return {'year': year, 'draft_picks': merged, 'combine_summary': combine_summary}

CONF_KEYWORDS = {
    'SEC': ['Alabama','Auburn','Florida','Georgia','Kentucky','LSU','Mississippi','Ole Miss','Missouri',
            'South Carolina','Tennessee','Texas A&M','Vanderbilt','Arkansas','Texas'],
    'BIG 10': ['Michigan','Ohio State','Penn State','Iowa','Illinois','Indiana','Maryland','Minnesota',
               'Nebraska','Northwestern','Purdue','Rutgers','Wisconsin','Michigan State','Oregon','Washington','UCLA','USC'],
    'ACC': ['Clemson','Florida State','North Carolina','NC State','Virginia Tech','Miami','Boston College',
            'Duke','Georgia Tech','Louisville','Pittsburgh','Syracuse','Virginia','Wake Forest'],
    'BIG 12': ['Oklahoma','Texas','Kansas','Kansas State','Iowa State','Baylor','TCU','West Virginia',
               'Oklahoma State','Texas Tech','Cincinnati','BYU','UCF','Houston','Colorado','Arizona','Utah','Arizona State'],
    'PAC 12': ['Oregon','Washington','UCLA','USC','Arizona','Utah','Colorado','Washington State','Oregon State','Arizona State','Cal','Stanford'],
    'MWC': ['Boise State','San Diego State','Nevada','Wyoming','Air Force','Colorado State','Utah State','Fresno State','UNLV','Hawaii'],
    'AAC': ['UCF','Cincinnati','Houston','Memphis','Tulsa','SMU','Navy','Tulane','East Carolina','Temple'],
    'IND': ['Notre Dame','BYU','Army','Navy'],
    'MAC': ['Toledo','Ball State','Bowling Green','Buffalo','Central Michigan','Eastern Michigan','Kent State','Miami Ohio','Ohio','Western Michigan','Akron'],
    'CUSA': ['Marshall','Western Kentucky','Louisiana Tech','Middle Tennessee','North Texas','Southern Miss','UAB','UTEP','UTSA','Charlotte','FIU','FAU'],
    'SUN BELT': ['Appalachian State','Louisiana','South Alabama','Georgia State','Georgia Southern','ULL','Troy','Arkansas State','Coastal Carolina','Old Dominion'],
}

def detect_conference(college, year):
    if not college: return 'UNK'
    # Take primary school (before "via")
    primary = college.split(' via ')[0].split(',')[0].strip()
    for conf, schools in CONF_KEYWORDS.items():
        for s in schools:
            if s.lower() in primary.lower():
                return conf
    # FCS/Small school
    return 'FCS/DII'

POS_MAP = {
    'OL':'OL','OT':'OT','G':'OG','OG':'OG','C':'OC','OC':'OC','IOL':'IOL',
    'DL':'DT','DT':'DT','NT':'DT','DE':'EDGE',
    'LB':'LB','ILB':'LB','OLB':'LB','MLB':'LB',
    'DB':'CB','CB':'CB','S':'SAF','SS':'SAF','FS':'SAF','SAF':'SAF',
    'QB':'QB','RB':'RB','FB':'RB','WR':'WR','TE':'TE',
    'K':'K','P':'P','LS':'LS','ST':'LS',
}

def normalize_pos(pos):
    return POS_MAP.get(pos, pos)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Parse args — support: scrape.py [year ...] [--force]
    args = sys.argv[1:]
    force = '--force' in args
    args = [a for a in args if a != '--force']

    if args:
        years = [int(y) for y in args]
    else:
        years = list(range(START_YEAR, CURRENT_YEAR + 1))

    print(f"\n{'='*50}")
    print(f"  NFL Draft Tracker - Data Scraper")
    print(f"  Years requested: {years}")
    print(f"  Force re-scrape: {force}")
    print(f"  Output: {OUT_DIR}")
    print(f"{'='*50}\n")

    # Skip years that already have data (unless --force)
    years_to_scrape = []
    for y in years:
        path = os.path.join(OUT_DIR, f"{y}.json")
        if os.path.exists(path) and not force:
            log(f"Skipping {y} — data/index.html already exists (use --force to re-scrape)")
        else:
            years_to_scrape.append(y)

    if not years_to_scrape:
        print("Nothing to scrape. All requested years already have data.")
        print("Use --force to re-scrape existing years.")
        # Still need to update the index with all existing years
        years_to_scrape = []

    # Load existing year data so we can merge it into the index
    existing_data = {}
    for y in years:
        path = os.path.join(OUT_DIR, f"{y}.json")
        if os.path.exists(path) and y not in years_to_scrape:
            with open(path) as f:
                existing_data[y] = json.load(f)

    # Step 1: Download bulk nflverse data (only if we have years to scrape)
    picks_by_year, combine_map = {}, {}
    if years_to_scrape:
        print("[1/3] Fetching nflverse data (draft picks + combine)...")
        picks_by_year, combine_map = fetch_nflverse()
    else:
        print("[1/3] No new years to scrape — skipping nflverse download")

    # Step 2: Fetch ESPN data per year
    if years_to_scrape:
        print("\n[2/3] Fetching ESPN data (height, birth state, early entrant)...")
        print("  Note: This makes many API calls and may take a few minutes per year.")
        print("  ESPN is free but rate-limited — we pause between requests.\n")
    else:
        print("\n[2/3] No new years to scrape — skipping ESPN fetch")

    all_year_data = {**existing_data}
    for year in years_to_scrape:
        print(f"\n  Processing {year}...")
        picks = picks_by_year.get(year, [])
        if not picks:
            log(f"No picks found for {year} in nflverse — draft may not be published yet")
            continue

        espn_map = fetch_espn_year(year)
        year_data = build_year_data(year, picks, combine_map, espn_map)
        all_year_data[year] = year_data

        out_path = os.path.join(OUT_DIR, f"{year}.json")
        with open(out_path, 'w') as f:
            json.dump(year_data, f, indent=2)
        log(f"Saved {year}.json ({len(year_data['draft_picks'])} picks)")

        time.sleep(0.5)

    # Step 3: Save index
    print("\n[3/3] Saving index file...")
    index = {
        'years': sorted(all_year_data.keys()),
        'generated': datetime.now().isoformat(),
        'sources': ['nflverse', 'ESPN Core API'],
    }
    with open(os.path.join(OUT_DIR, 'index.json'), 'w') as f:
        json.dump(index, f, indent=2)
    
    print(f"\n{'='*50}")
    print(f"  ✓ Done! Data saved to: {OUT_DIR}/")
    print(f"  Years scraped: {sorted(all_year_data.keys())}")
    print(f"  Next step: run  python build.py  to generate index.html")
    print(f"{'='*50}\n")

if __name__ == '__main__':
    main()
