"""Acquire the frozen CT cohort serially with the project's isolated browser recipe."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.confirm_ct_generalization import write


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def selected_member(listing, map_name):
    members = []
    for line in listing.splitlines():
        fields = line.split(maxsplit=8)
        if len(fields) != 9 or not fields[8].lower().endswith('.dem'):
            continue
        name = fields[8];path = PurePosixPath(name.replace('\\', '/'))
        if fields[0][0] != '-' or path.is_absolute() or '..' in path.parts or any(c in name for c in ':*?\x00'):
            raise ValueError('Unsafe or nonregular demo member')
        size = int(fields[4])
        if size < 1:
            raise ValueError('Empty demo member')
        members.append((name, size))
    matching = [row for row in members if re.search(r'(?:^|[-_])' + re.escape(map_name.removeprefix('de_')) + r'\.dem$', row[0], re.I)]
    if len(matching) == 1:
        return matching[0]
    if len(members) == 1:
        return members[0]  # Header/map equality is mandatory during native input extraction.
    raise ValueError('Archive does not identify exactly one requested map')


def resolved_primary(cohort, replacements):
    primary = {r['match_id']:r for r in cohort['primary']}
    assert set(replacements) <= set(primary)
    result = []
    for original in cohort['primary']:
        row = original
        if original['match_id'] in replacements:
            replacement = replacements[original['match_id']]
            row = next(r for r in cohort['alternates'] if r['match_id']==replacement['match_id'])
            assert original['match_id'] in row['replaceable_primary_match_ids']
            assert row['event_id']==original['event_id'] and row['selected_map']==original['selected_map']
            assert replacement['reason']
        result.append(row)
    assert len({r['match_id'] for r in result})==len(result)
    return result


def main():
    import psutil
    from DrissionPage import ChromiumPage, ChromiumOptions
    # shortcut: private packet/wait APIs match DrissionPage 4.1.1.4; recheck when upgrading it.
    from DrissionPage._units.waiter import wait_mission

    protocol_path = ROOT / 'datasets/selections/ct_independent_confirmation.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    cohort_path = ROOT / protocol['cohort_path']
    assert digest(cohort_path) == protocol['inputs_sha256'][protocol['cohort_path']]
    cohort = json.loads(cohort_path.read_text(encoding='utf-8'))
    limits = protocol['acquisition_limits']
    out = ROOT / 'output/tagnet/ct_independent_demos'
    ledger_path = out / 'acquisition.json'
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
        assert ledger['protocol_sha256'] == digest(protocol_path)
    else:
        if out.exists() and any(out.iterdir()):
            raise ValueError('Refusing to reset the acquisition budget in a nonempty directory')
        out.mkdir(parents=True, exist_ok=True)
        ledger = {'status': 'acquiring', 'protocol_sha256': digest(protocol_path),
                  'cohort_sha256': digest(cohort_path), 'script_sha256': digest(Path(__file__)),
                  'attempts': [], 'files': [], 'failures': []}
        write(ledger_path, ledger)
    ledger['status'] = 'acquiring'
    ledger.setdefault('script_revisions', []).append(digest(Path(__file__)))
    write(ledger_path, ledger)
    assert psutil.virtual_memory().available > 2500 * 2**20, 'Browser start RAM guard'
    page = None
    try:
        for row in resolved_primary(cohort, ledger.get('replacements', {})):
            match_id, map_name = row['match_id'], row['selected_map']
            assert re.fullmatch('[0-9]+', match_id) and map_name in ('de_ancient','de_anubis','de_dust2','de_inferno','de_mirage','de_nuke')
            completed = next((r for r in ledger['files'] if r['match_id'] == match_id), None)
            if completed:
                assert digest(ROOT / completed['demo_path']) == completed['sha256']
                continue
            archive = out / f'archive_{match_id}.rar'
            if not archive.exists():
                assert psutil.virtual_memory().available > 2500 * 2**20, 'Browser start RAM guard'
                co = ChromiumOptions();co.auto_port();co.headless(False)
                co.set_argument('--window-position=-2000,-2000');co.set_argument('--blink-settings=imagesEnabled=false')
                co.set_argument('--disable-component-update');co.set_timeouts(base=10,page_load=20)
                page = ChromiumPage(co)
                page.set.load_mode.eager();page.set.download_path(str(out.resolve()))
                page.get(row['match_url'], retry=0)
                for _ in range(10):
                    if 'data-demo-link' in page.html:
                        break
                    time.sleep(2)
                assert 'data-demo-link' in page.html, 'Match origin unavailable before HEAD'
                page.listen.start(targets=True, method='HEAD')
                page.run_js("fetch(arguments[0],{method:'HEAD',mode:'no-cors',credentials:'include'}).catch(()=>{});", row['demo_url'])
                packet = page.listen.wait(timeout=20)
                if not packet:
                    raise RuntimeError(f'No archive HEAD metadata: {match_id}')
                response = packet._raw_response or {}
                extra = packet._responseExtraInfo or {}
                assert urlsplit(packet.url).hostname == 'r2-demos.hltv.org'
                assert packet._raw_request.get('redirectResponse', {}).get('url') == row['demo_url']
                headers = {k.lower(): v for k, v in {**response.get('headers', {}), **extra.get('headers', {})}.items()}
                expected = int(headers.get('content-length', 0))
                status = response.get('status', extra.get('statusCode'))
                reserved = sum(r['reserved_bytes'] for r in ledger['attempts'])
                known_length = status == 200 and expected > 0
                if not known_length:
                    expected = min(limits['single_archive_bytes_max'], limits['archive_bytes_max'] - reserved)
                assert 0 < expected <= limits['single_archive_bytes_max']
                assert len(ledger['attempts']) < limits['archive_GET_attempts_max']
                assert reserved + expected <= limits['archive_bytes_max'], 'Cumulative archive budget exhausted'
                attempt = {'match_id': match_id, 'reserved_bytes': expected, 'state': 'reserved_before_GET',
                           'script_sha256': digest(Path(__file__)), 'HEAD_status':status,
                           'initial_reservation_bytes':expected, 'HEAD_length_known':known_length}
                ledger['attempts'].append(attempt);write(ledger_path, ledger)
                page.listen.stop()
                page.set.download_file_name(name=f'archive_{match_id}', suffix='rar')
                page.browser._dl_mgr.set_flag('browser', True)
                page.get(row['demo_url'], retry=0)
                mission = wait_mission(page.browser, 'browser', 30)
                if not mission:
                    raise RuntimeError(f'Archive download did not begin: {match_id}; title={page.title}')
                deadline = time.monotonic() + 900;last_progress = 0
                while not mission.is_done:
                    if (time.monotonic() > deadline or psutil.virtual_memory().available < limits['RAM_guard_bytes_min']
                            or (mission.total_bytes or 0) > expected or mission.received_bytes > expected):
                        mission.cancel();raise RuntimeError('Download stopped by time, memory or byte guard')
                    if time.monotonic() - last_progress > 30:
                        print(json.dumps({'match_id':match_id, 'received_MiB':round(mission.received_bytes/2**20,1),
                                          'expected_MiB':round(expected/2**20,1)}), flush=True)
                        last_progress = time.monotonic()
                    time.sleep(.2)
                assert mission.state == 'completed' and Path(mission.final_path).resolve() == archive.resolve()
                actual = archive.stat().st_size
                assert 0 < actual <= expected and actual == mission.total_bytes
                assert not known_length or actual == expected
                attempt.update(state='completed', actual_bytes=actual, reserved_bytes=actual, sha256=digest(archive));write(ledger_path, ledger)
                page.quit();page = None
            else:
                prior = next((a for a in ledger['attempts'] if a['match_id'] == match_id and a.get('state') == 'completed'), None)
                assert prior and digest(archive) == prior['sha256'], 'Unverified existing archive'
            listing = subprocess.run(['tar','-tvf',str(archive)], capture_output=True, check=True).stdout.decode('mbcs' if os.name=='nt' else 'utf-8')
            member, size = selected_member(listing, map_name)
            assert size <= limits['single_demo_bytes_max']
            assert sum(r['bytes'] for r in ledger['files']) + size <= limits['retained_demo_bytes_max']
            assert psutil.disk_usage(str(out)).free > size + 2 * 2**30
            target = out / f'{match_id}__{map_name}.dem';partial = target.with_suffix('.dem.part')
            assert not target.exists() and not partial.exists()
            process = subprocess.Popen(['tar','-xOf',str(archive),member], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            written = 0
            try:
                with partial.open('xb') as stream:
                    while chunk := process.stdout.read(2**20):
                        if written + len(chunk) > size:
                            raise ValueError('Extraction exceeds declared member size')
                        stream.write(chunk);written += len(chunk)
                assert process.wait() == 0 and written == size, 'Incomplete extraction'
            finally:
                if process.poll() is None:
                    process.terminate();process.wait()
            partial.rename(target)
            ledger['files'].append({'match_id':match_id,'event_id':row['event_id'],'map':map_name,
                'demo_path':target.relative_to(ROOT).as_posix(),'sha256':digest(target),'bytes':size,
                'archive_sha256':digest(archive),'archive_member':member})
            write(ledger_path, ledger)
            print(json.dumps({'retained_demos':len(ledger['files']),'match_id':match_id,'map':map_name,
                              'reserved_archive_GiB':round(sum(a['reserved_bytes'] for a in ledger['attempts'])/2**30,3)}), flush=True)
        ledger['status'] = 'primary_archives_acquired_pending_native_QA';write(ledger_path, ledger)
    except Exception as error:
        ledger['status'] = 'stopped_pending_resolution'
        ledger['failures'].append({'type':type(error).__name__, 'match_id':row['match_id'] if 'row' in locals() else None})
        write(ledger_path, ledger)
        raise
    finally:
        if page:
            page.quit()


if __name__ == '__main__':
    main()
