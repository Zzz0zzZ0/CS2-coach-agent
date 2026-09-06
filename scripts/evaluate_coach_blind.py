"""Freeze a small Coach-priority experiment, prepare anonymous review, and score human ratings.

This tests production priority selection, not retrieval quality or free-form generation.
All network calls require the explicit `run` command; prepare and score are offline.
"""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import random
import re
import sqlite3
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agentic.nodes.coach_node import _render_report, _select_priorities
from app.services.metrics_service import calculate_metrics, build_current_match_evidence

MODEL = 'qwen3.8-flash'
DIMENSIONS = ('evidence_fidelity', 'priority_relevance', 'actionability')
SOURCES = ('app/agentic/nodes/coach_node.py', 'app/agentic/tools.py', 'app/services/metrics_service.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')


def prepare(db_path, directory):
    directory.mkdir(parents=True, exist_ok=False)
    before = digest(db_path)
    cases = []
    with sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        selected = db.execute("SELECT match_id,MIN(map_name) AS map_name FROM nodes WHERE node_type='round' GROUP BY match_id ORDER BY match_id LIMIT 4").fetchall()
        for row in selected:
            rounds = {int(r['round_number']): {**json.loads(r['properties']), 'round_number':int(r['round_number']),
                      'kills':[], 'grenades':[], 'flash_blinds':[], 'plants':[]}
                      for r in db.execute("SELECT * FROM nodes WHERE node_type='round' AND match_id=? AND map_name=?", tuple(row))}
            for event in db.execute("SELECT * FROM nodes WHERE node_type='event' AND match_id=? AND map_name=? ORDER BY json_extract(properties,'$.tick'),node_id", tuple(row)):
                props = json.loads(event['properties'])
                field = {'kill':'kills', 'grenade':'grenades', 'flash':'flash_blinds', 'plant':'plants'}.get(props.get('kind'))
                if field:
                    rounds[int(event['round_number'])][field].append(props)
            ordered = [rounds[number] for number in sorted(rounds)]
            if sorted(rounds) != list(range(1, len(rounds) + 1)) or not all(r.get('participants_complete') for r in ordered):
                raise ValueError('Selected graph map has incomplete roster or non-contiguous round numbers')
            metrics = calculate_metrics(ordered)
            case = {'match_id':row['match_id'], 'map_name':row['map_name'], 'metrics':metrics, 'source':'historical_graph_reconstruction'}
            case['current_evidence'] = build_current_match_evidence(case, metrics)
            cases.append(case)
    for map_name in ('Dust2', 'Mirage'):
        path = ROOT / f'datasets/evaluation/unseen_pipeline_pilot_v1_report_2396950_{map_name}.json'
        result = json.loads(path.read_text())
        cases.append({key:result[key] for key in ('match_id','map_name','metrics','current_evidence')} | {'source':'previously_seen_pilot_report', 'source_sha256':digest(path)})
    if len(cases) != 6 or len({(c['match_id'], c['map_name']) for c in cases}) != 6:
        raise ValueError('Expected six distinct maps; no reselection after results')
    for index, case in enumerate(cases, 1):
        case['case_id'] = f'case-{index:02}'
    save(directory / 'inputs.json', cases)
    manifest = {'version':'coach-blind-v1', 'created_at':datetime.now(timezone.utc).isoformat(),
                'selection':'first four historical match IDs ascending, first map alphabetically; both maps from prior 2396950 pilot',
                'scope':'development pilot; all cases already seen; not OOD or independent generalization',
                'model':MODEL, 'max_calls':6, 'reserved_token_budget':30000, 'max_output_tokens':512,
                'min_reviewers':2, 'primary_dimension':'priority_relevance', 'analysis_unit':'mean map delta per match, then mean across matches',
                'inputs_sha256':digest(directory / 'inputs.json'), 'graph_sha256':before,
                'implementation_sha256':{path:digest(ROOT / path) for path in SOURCES},
                'harness_sha256':digest(__file__), 'cases':[{'case_id':c['case_id'],'match_id':c['match_id'],'map_name':c['map_name']} for c in cases]}
    if digest(db_path) != before:
        raise ValueError('Graph changed during freeze')
    save(directory / 'manifest.json', manifest)
    return manifest


class MeteredModel:
    """Reserve a conservative per-call allowance and journal attempts before network I/O."""
    def __init__(self, llm, directory, budget, max_calls):
        self.llm, self.directory = llm, directory
        self.budget, self.max_calls = budget, max_calls
        self.reserved, self.calls = 0, 0
        self.error_type = None
        self.case_id = None

    def bind_tools(self, tools):
        self.bound = self.llm.bind_tools(tools)
        self.schema_bytes = len(json.dumps([tool.args_schema.model_json_schema() for tool in tools]).encode())
        return self

    async def ainvoke(self, prompt):
        reserve = len(prompt.encode()) + self.schema_bytes + 2048 + 512
        if self.calls >= self.max_calls or self.reserved + reserve > self.budget:
            self.error_type = 'LocalBudgetLimit'
            raise ValueError('Local experiment budget reached')
        self.calls += 1
        self.reserved += reserve
        # Existence of this receipt prevents a normal rerun from duplicating an uncertain call.
        save(self.directory / f'{self.case_id}.attempt.json', {'case_id':self.case_id, 'reserved_tokens':reserve,
             'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(), 'status':'attempted; inspect result before any new run'})
        try:
            return await self.bound.ainvoke(prompt)
        except Exception as error:
            self.error_type = type(error).__name__
            raise


def check_frozen(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if digest(directory / 'inputs.json') != manifest['inputs_sha256'] or manifest['model'] != MODEL:
        raise ValueError('Frozen inputs or model changed')
    if digest(__file__) != manifest['harness_sha256'] or any(digest(ROOT / path) != sha for path, sha in manifest['implementation_sha256'].items()):
        raise ValueError('Frozen implementation changed; create a separately versioned experiment')
    return manifest, json.loads((directory / 'inputs.json').read_text())


async def run(directory, output, llm):
    manifest, cases = check_frozen(directory)
    if llm is None:
        raise ValueError('Configured model unavailable; no model experiment was performed')
    output.mkdir(parents=True, exist_ok=False)
    meter = MeteredModel(llm, output, manifest['reserved_token_budget'], manifest['max_calls'])
    results = []
    for case in cases:
        meter.case_id = case['case_id']
        baseline, _, _ = await _select_priorities(None, case['metrics'])
        started = time.perf_counter()
        selected, source, usage = await _select_priorities(meter, case['metrics'])
        record = {'case_id':case['case_id'], 'baseline':baseline, 'selected':selected, 'selection_source':source,
                  'usage':usage, 'latency_ms':round((time.perf_counter()-started)*1000, 2), 'error_type':meter.error_type}
        save(output / f"{case['case_id']}.result.json", record)
        results.append(record)
        if source != 'qwen_tool_call' or not usage.get('total_tokens'):
            break  # Includes quota/timeout/invalid tool response and uncertain accounting; never retry.
    complete = len(results) == len(cases) and all(r['selection_source'] == 'qwen_tool_call' and r['usage'].get('total_tokens') for r in results)
    report = {'status':'awaiting_human_review' if complete else 'stopped', 'model':MODEL,
              'planned_cases':len(cases), 'completed_model_cases':sum(r['selection_source']=='qwen_tool_call' for r in results),
              'calls':meter.calls, 'reserved_token_allowance':meter.reserved,
              'reported_tokens':sum(r['usage'].get('total_tokens',0) for r in results),
              'accounting_complete':all(bool(r['usage'].get('total_tokens')) for r in results),
              'stop_reason':None if complete else results[-1]['error_type'] or 'invalid_tool_response_or_missing_usage',
              'latency_p50_ms':statistics.median(r['latency_ms'] for r in results),
              'identical_priority_lists':sum(r['baseline']==r['selected'] for r in results),
              'quality_metrics':None, 'manifest_sha256':digest(directory / 'manifest.json'),
              'limitations':['reported usage is this run only; provider free-quota balance is unavailable',
                             'reserved allowance is a conservative estimate, not provider billing or a global quota ledger',
                             'selection differences are not quality gains; independent human ratings are pending']}
    if complete:
        packet, key = build_packet(cases, results)
        review_dir = output / 'review'
        review_dir.mkdir()
        save(review_dir / 'packet.json', packet)
        packet_sha = digest(review_dir / 'packet.json')
        save(output / 'method_key.json', {'packet_sha256':packet_sha, 'assignments':key})
        for index in (1,2):
            save(review_dir / f'reviewer_{index}.json', {'reviewer_id':'', 'reviewed_at':'',
                 'independent_review_attestation':False, 'method_key_not_seen_attestation':False,
                 'packet_sha256':packet_sha, 'method_key_sha256':digest(output / 'method_key.json'), 'ratings':[{'case_id':case['case_id'],
                    'A':{name:None for name in DIMENSIONS}, 'B':{name:None for name in DIMENSIONS},
                    'preference':None, 'rationale':''} for case in cases]})
        (review_dir / 'review.html').write_text(render_packet(packet), encoding='utf-8')
        report['packet_sha256'] = packet_sha
        report['method_key_sha256'] = digest(output / 'method_key.json')
    save(output / 'run_report.json', report)
    return report


def build_packet(cases, results):
    packet, key = [], {}
    rng = random.SystemRandom()
    for case, result in zip(cases, results):
        order = ['rule', 'model']
        rng.shuffle(order)
        candidates = {}
        key[case['case_id']] = dict(zip(('A','B'), order))
        for label, method in key[case['case_id']].items():
            candidates[label] = _render_report(case['metrics'], result['baseline' if method=='rule' else 'selected'])
            cited = set(re.findall(r'\[C(\d+)\]', candidates[label]))
            if any(int(index) not in range(1, len(case['current_evidence'])+1) for index in cited):
                raise ValueError('Rendered candidate has an invalid citation')
        packet.append({'case_id':case['case_id'], 'match_id':case['match_id'], 'map_name':case['map_name'],
                       'metrics':case['metrics'], 'current_evidence':case['current_evidence'], 'candidates':candidates})
    return packet, key


def render_packet(packet):
    body = ['<!doctype html><html lang="zh"><meta charset="utf-8"><title>Coach 优先级匿名评审</title><style>body{font:16px/1.7 system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#203046}section{border-top:1px solid #ccd6e0;margin-top:32px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{padding:20px;background:#f3f6fa}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.8 system-ui}details{margin:18px 0}summary{cursor:pointer}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style><h1>Coach 优先级匿名评审</h1><p>请仅查看 review 目录，不打开方法映射或运行日志。独立完成 reviewer 文件，不与其他评审讨论评分。1–5 分分别评价事实与引用一致性、优先级适切性、可执行性；1=明显不合适，3=部分有用但需修改，5=证据充分且明确有用。另选 A / B / tie 并填写依据；相同内容应给相同评分。优先级适切性是主要指标。两组均需人工录像复核，不把统计关联当成因果。</p><p>填写 reviewer_1.json 或 reviewer_2.json；保留 packet_sha256，填写自己的评审标识、ISO 日期及独立性声明。不要把身份映射提供给评审者。</p>']
    for case in packet:
        body.append(f"<section><h2>{html.escape(case['case_id'])} · {html.escape(case['map_name'])} · {html.escape(str(case['match_id']))}</h2><div class='pair'>")
        for label, report in case['candidates'].items():
            rendered = html.escape(report.replace('**',''))
            rendered = re.sub(r'\[C(\d+)\]', lambda match: f'<a href="#{case["case_id"]}-C{match[1]}">[C{match[1]}]</a>', rendered)
            body.append(f'<article><h3>{label}</h3><pre>{rendered}</pre></article>')
        body.append('</div><details><summary>共同事实与指标</summary><pre>'+html.escape(json.dumps(case['metrics'],ensure_ascii=False,indent=2))+'</pre></details>')
        for index, evidence in enumerate(case['current_evidence'],1):
            body.append(f'<details id="{case["case_id"]}-C{index}"><summary>[C{index}] {html.escape(evidence["source_id"])}</summary><pre>{html.escape(evidence["content"])}</pre></details>')
        body.append('</section>')
    return ''.join(body)+'</html>'


def score(packet_path, key_path, review_paths):
    packet = json.loads(packet_path.read_text())
    key = json.loads(key_path.read_text())
    packet_sha = digest(packet_path)
    if key['packet_sha256'] != packet_sha or set(key['assignments']) != {c['case_id'] for c in packet}:
        raise ValueError('Packet or method key mismatch')
    pending, reviewers, ratings = [], set(), []
    for path in review_paths:
        review = json.loads(path.read_text())
        if review.get('packet_sha256') != packet_sha or review.get('method_key_sha256') != digest(key_path):
            raise ValueError('Review belongs to another packet')
        reviewer = review.get('reviewer_id','').strip()
        if reviewer and reviewer in reviewers:
            raise ValueError('Duplicate reviewer')
        if not reviewer or not review.get('reviewed_at') or review.get('independent_review_attestation') is not True or review.get('method_key_not_seen_attestation') is not True:
            pending.append('reviewer identity, date or independent/blind attestation missing')
        else:
            datetime.fromisoformat(review['reviewed_at'].replace('Z','+00:00'))
            reviewers.add(reviewer)
        rows = review.get('ratings',[])
        if len(rows) != len(packet) or {r['case_id'] for r in rows} != {c['case_id'] for c in packet}:
            raise ValueError('Incomplete, duplicate or unknown cases')
        for row in rows:
            if not row.get('rationale','').strip() or row.get('preference') not in ('A','B','tie'):
                pending.append('case rationale or preference missing')
            for method in ('A','B'):
                for dimension in DIMENSIONS:
                    value = row.get(method,{}).get(dimension)
                    if value is None:
                        pending.append('unrated case')
                    elif type(value) is not int or not 1 <= value <= 5:
                        raise ValueError('Ratings must be integer 1 through 5')
        ratings.append(rows)
    if len(reviewers) < 2 or pending or not packet:
        return {'status':'pending_review', 'quality_metrics':None, 'complete_reviewers':len(reviewers), 'pending_reasons':sorted(set(pending or ['two complete independent reviewers required']))}
    by_match = {c['case_id']:str(c['match_id']) for c in packet}
    deltas = {dimension:defaultdict(list) for dimension in DIMENSIONS}
    preferences = {'model':0,'rule':0,'tie':0}
    for rows in ratings:
        for row in rows:
            assignment = key['assignments'][row['case_id']]
            if set(assignment) != {'A','B'} or set(assignment.values()) != {'rule','model'}:
                raise ValueError('Invalid method assignment')
            reverse = {method:label for label,method in assignment.items()}
            for dimension in DIMENSIONS:
                deltas[dimension][by_match[row['case_id']]].append(row[reverse['model']][dimension]-row[reverse['rule']][dimension])
            preferences['tie' if row['preference']=='tie' else assignment[row['preference']]] += 1
    matched = {dimension:{match:statistics.mean(values) for match,values in matches.items()} for dimension,matches in deltas.items()}
    return {'status':'descriptive_review_complete', 'reviewers':len(reviewers), 'maps':len(packet), 'matches':len(set(by_match.values())),
            'quality_metrics':{'model_minus_rule_by_match':matched,
                               'mean_match_delta':{dimension:statistics.mean(matches.values()) for dimension,matches in matched.items()},
                               'preference_counts':preferences},
            'limitations':['reviewer independence and blinding are attestations, not machine-verifiable facts', 'small development pilot; no causal, significance or generalization claim']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    p = commands.add_parser('prepare'); p.add_argument('--graph-db',type=Path,default=ROOT/'data/graph/cs2_graph.sqlite'); p.add_argument('--output',type=Path,required=True)
    p = commands.add_parser('run'); p.add_argument('--frozen',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p = commands.add_parser('score'); p.add_argument('--packet',type=Path,required=True); p.add_argument('--key',type=Path,required=True); p.add_argument('--reviews',type=Path,nargs='+',required=True); p.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.graph_db,args.output)
        print(json.dumps({'cases':len(result['cases']), 'model':result['model'], 'max_calls':result['max_calls']}))
    elif args.command == 'run':
        from app.core.config import settings
        from app.core.providers import get_llm
        if settings.MODEL_NAME != MODEL:
            raise ValueError('Configured model differs from frozen model')
        settings.LLM_MAX_TOKENS = 512
        settings.LLM_TIMEOUT_SECONDS = 45
        settings.LLM_ENABLE_THINKING = False
        result = asyncio.run(run(args.frozen,args.output,get_llm()))
        print(json.dumps(result,ensure_ascii=False))
    else:
        result = score(args.packet,args.key,args.reviews)
        save(args.output,result)
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
