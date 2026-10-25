"""Resolve native clan abbreviations by exact five-player public lineup matching."""

import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.acquire_ct_independent_demos import digest, resolved_primary
from scripts.confirm_ct_generalization import write
from app.services.team_identity_service import canonical_team


def match_rosters(native, published):
    def normalized(names):
        aliases={'naf-fly':'naf','techno4k':'techno'}
        return [aliases.get(str(n).strip().casefold(),str(n).strip().casefold()) for n in names]
    published={team:normalized(names) for team,names in published.items()}
    matches={}
    for tag,names in native.items():
        names=normalized(names)
        assert len(names)==len(set(names))==5
        candidates=[team for team,roster in published.items() if set(names)==set(roster)]
        assert len(candidates)==1, f'Five-player lineup unresolved: {tag}'
        matches[tag]=candidates[0]
    assert len(matches)==len(set(matches.values()))==2
    return matches


def main():
    import psutil
    from bs4 import BeautifulSoup
    from demoparser2 import DemoParser

    root=ROOT/'output/tagnet/ct_independent_inputs';qa=json.loads((root/'report.json').read_text(encoding='utf-8'))
    if not qa['unresolved_team_identities']:
        if qa.get('identity_checks_sha256'):
            assert digest(root/'identity_checks.json')==qa['identity_checks_sha256']
        return
    manifest=json.loads((ROOT/'output/tagnet/ct_independent_demos/acquisition.json').read_text(encoding='utf-8'))
    cohort=json.loads((ROOT/'datasets/selections/ct_independent_cohort.json').read_text(encoding='utf-8'))
    selected={r['match_id']:r for r in resolved_primary(cohort,manifest.get('replacements',{}))}
    proofs=[]
    for mid in qa['unresolved_team_identities']:
        source=next(r for r in manifest['files'] if r['match_id']==mid)
        html=ROOT/f'output/tagnet/ct_independent_metadata_v1/match_{mid}.html'
        assert digest(html)==selected[mid]['match_html_sha256']
        soup=BeautifulSoup(html.read_bytes(),'html.parser');published={}
        for lineup in soup.select('.lineup'):
            team=canonical_team(lineup.select_one('.box-headline a[href^="/team/"]').get_text(strip=True))
            names=[p.get_text(strip=True).casefold() for p in lineup.select('.players td.player:not(.player-image)')]
            assert len(names)==len(set(names))==5
            published[team]=names
        assert set(published)=={canonical_team(t) for t in selected[mid]['teams']}
        assert psutil.virtual_memory().available>2*2**30
        path=ROOT/source['demo_path'];assert digest(path)==source['sha256']
        raw=json.loads((root/mid/'snapshots.json').read_text(encoding='utf-8'))
        window=next(r for r in raw['rounds'] if r['side']=='CT' and r['status']=='ok')
        tick=window['snapshots'][0]['tick']
        native=DemoParser(str(path)).parse_ticks(['team_clan_name'],ticks=[tick]);groups={}
        for tag,frame in native.groupby('team_clan_name'):
            groups[canonical_team(tag)]=sorted(frame['name'].str.casefold().tolist())
        mapping=match_rosters(groups,published)
        proofs.append({'match_id':mid,'demo_sha256':source['sha256'],'match_html_sha256':digest(html),
            'tick':tick,'native_nicknames':groups,'published_nicknames':published,'confirmed_mapping':mapping})
    report={'status':'exact_normalized_five_player_lineup_identity_checks','script_sha256':digest(Path(__file__)),
        'nickname_normalization':'Trim and casefold; only NAF-FLY -> NAF and Techno4K -> Techno explicit aliases, checked before model inference.',
        'alias_primary_sources':{'naf-fly':'https://teamliquid.com/news/2018/02/05/csgo-roster-update-liquidnaf',
                                 'techno4k':'https://blast.tv/article/csgo/rmr-mvp-vote'},
        'proofs':proofs,'limits':'Public nicknames and source/archive provenance establish the recorded match correspondence; no global alias service or model features were changed.'}
    proof_path=root/'identity_checks.json';write(proof_path,report)
    qa['identity_checks_sha256']=digest(proof_path)
    qa['lexical_team_mismatches_before_lineup_checks']=qa['unresolved_team_identities']
    qa['unresolved_team_identities']=[]
    write(root/'report.json',qa)


if __name__=='__main__':main()
