"""Select a map-balanced external cohort from public metadata before model evaluation."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import sha, write

MAPS = ("de_ancient", "de_anubis", "de_dust2", "de_inferno", "de_mirage", "de_nuke")
EVENTS = (8263, 8244, 8932)


def choose_cohort(candidates):
    variables = [(i, name) for i, row in enumerate(candidates) for name in MAPS if name in row["played_maps"]]
    rows, lower, upper = [], [], []
    def constrain(keep, lo, hi):
        rows.append([float(keep(i, name)) for i, name in variables]);lower.append(lo);upper.append(hi)
    for name in MAPS:
        constrain(lambda i, m, name=name: m == name, 2, 2)
    for event in EVENTS:
        constrain(lambda i, m, event=event: candidates[i]["event_id"] == event, 0, 4)
        for name in MAPS:
            constrain(lambda i, m, event=event, name=name: candidates[i]["event_id"] == event and m == name, 0, 1)
    for index in range(len(candidates)):
        constrain(lambda i, m, index=index: i == index, 0, 1)
    solution = milp(np.asarray([i * 100000 + j for j, (i, _) in enumerate(variables)], dtype=float),
                    integrality=np.ones(len(variables)), bounds=Bounds(0, 1),
                    constraints=LinearConstraint(np.asarray(rows), np.asarray(lower), np.asarray(upper)),
                    options={"time_limit": 15})
    if not solution.success:
        raise RuntimeError(f"No complete balanced cohort: {solution.message}")
    selected = [{**candidates[i], "selected_map": name} for value, (i, name) in zip(solution.x, variables) if value > 0.5]
    assert len(selected) == 12 and len({r['match_id'] for r in selected}) == 12
    assert Counter(r['selected_map'] for r in selected) == {name: 2 for name in MAPS}
    assert all(n <= 4 for n in Counter(r['event_id'] for r in selected).values())
    assert all(n == 1 for n in Counter((r['event_id'], r['selected_map']) for r in selected).values())
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    import requests
    from bs4 import BeautifulSoup
    if (args.cache_dir / "cohort.json").exists():
        parser.error("Cohort already exists")
    session = requests.Session();session.trust_env = False
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    source_ids = {r['series'] for r in json.loads((ROOT / 'output/tagnet/ct_deployment_inputs_p1_v03/sample_index.json').read_text())}
    candidates, receipts, failures = [], {}, []
    for event in EVENTS:
        path = args.cache_dir / f"event_{event}.html"
        if not path.exists():
            response = session.get(f"https://www.hltv.org/results?event={event}", timeout=20)
            response.raise_for_status();path.write_bytes(response.content)
        receipts[path.name] = sha(path)
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        links = {}
        for result in soup.select('.result-con'):
            anchor = result.select_one('a[href*="/matches/"]')
            if anchor:
                match_id = re.search(r'/matches/(\d+)/', anchor['href'])[1]
                links[match_id] = (anchor['href'], int(result['data-zonedgrouping-entry-unix']))
        for match_id, (href, unix_ms) in sorted(links.items(), key=lambda item: (item[1][1], int(item[0]))):
            if match_id in source_ids:
                continue
            path = args.cache_dir / f"match_{match_id}.html"
            if not path.exists():
                try:
                    response = session.get('https://www.hltv.org' + href, timeout=20)
                    response.raise_for_status()
                    if len(response.content) > 3 * 2**20:
                        raise ValueError("Metadata page too large")
                    path.write_bytes(response.content)
                    time.sleep(0.1)
                except (requests.RequestException, ValueError) as error:
                    failures.append({"match_id": match_id, "reason": type(error).__name__})
                    continue
            receipts[path.name] = sha(path)
            soup = BeautifulSoup(path.read_bytes(), 'html.parser')
            download = soup.select_one('[data-demo-link]')
            played = []
            for number, holder in enumerate(soup.select('.mapholder'), 1):
                scores = [element.get_text(strip=True) for element in holder.select('.results-team-score')]
                name = holder.select_one('.mapname')
                if name and len(scores) == 2 and all(value.isdigit() for value in scores):
                    played.append({'map': 'de_' + name.get_text(strip=True).lower().replace(' ', ''), 'map_number': number})
            if not download or not played:
                failures.append({'match_id': match_id, 'reason': 'no_download_or_completed_map'})
                continue
            candidates.append({'match_id': match_id, 'event_id': event, 'result_unix_ms': unix_ms,
                               'match_url': 'https://www.hltv.org' + href,
                               'demo_url': requests.compat.urljoin('https://www.hltv.org', download['data-demo-link']),
                               'teams': [node.get_text(strip=True) for node in soup.select('.team1-gradient .teamName, .team2-gradient .teamName')],
                               'played_maps': [row['map'] for row in played], 'map_order': played,
                               'match_html_sha256': sha(path)})
            if len(candidates) % 10 == 0:
                print(json.dumps({'metadata_candidates': len(candidates), 'event_id': event}), flush=True)
    candidates.sort(key=lambda row: (row['result_unix_ms'], int(row['match_id'])))
    write(args.cache_dir / 'metadata_audit.json', {'status': 'metadata_only_before_selection',
          'script_sha256': sha(Path(__file__)), 'candidates': candidates, 'failures': failures,
          'metadata_sha256': receipts, 'no_archives_downloaded': True})
    selected = choose_cohort(candidates)
    used = {r['match_id'] for r in selected}
    alternates = []
    for name in MAPS:
        for row in candidates:
            if row['match_id'] not in used and name in row['played_maps']:
                replaceable = [r['match_id'] for r in selected if r['selected_map'] == name and r['event_id'] == row['event_id']]
                if replaceable:
                    alternates.append({**row, 'selected_map': name, 'replaceable_primary_match_ids': replaceable});used.add(row['match_id']);break
    extra = next(({**row, 'selected_map': 'de_cache'} for row in selected if 'de_cache' in row['played_maps']), None)
    write(args.cache_dir / 'cohort.json', {'status': 'selected_by_metadata_before_download_or_model_evaluation',
          'script_sha256': sha(Path(__file__)), 'selection_rule': 'Minimum total chronological candidate rank subject to 12 unique series, two per map, four per event maximum, and one series per event/map. No score or model result enters selection.',
          'events': list(EVENTS), 'candidates': candidates, 'primary': selected, 'alternates': alternates,
          'optional_same_archive_cache': extra, 'metadata_sha256': receipts, 'failures': failures,
          'limits': ['May and October events are mixed: newly acquired series, not a chronological future-only split.', 'Shared teams remain; three event strata do not establish independent random sampling.', 'No archives or model outputs were acquired by this script.']})
    print(json.dumps({'selected': [(r['match_id'],r['event_id'],r['selected_map']) for r in selected], 'alternates': len(alternates), 'optional_cache': extra['match_id'] if extra else None}))


if __name__ == '__main__':
    main()
