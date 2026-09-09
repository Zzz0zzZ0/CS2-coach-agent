"""Guided, read-only questions over one saved input; no model or external tools."""
import hashlib
import json
import re
from typing import Literal

from app.services.metrics_service import build_current_round_evidence, calculate_metrics

QuestionKind = Literal['opening_losses', 'post_plant_losses', 'round', 'player']
SourceDetail = Literal['full', 'compact']
MAX_ROUNDS = 1000
MAX_SOURCES = 20


class QuestionUnavailable(ValueError):
    def __init__(self, status_code, message):
        self.status_code = status_code
        super().__init__(message)


def answer_question(store, task_id, kind: QuestionKind, round_number=None, player=None, max_steps=2,
                    detail: SourceDetail = 'full', expected_payload_sha256=None):
    if kind not in {'opening_losses', 'post_plant_losses', 'round', 'player'} or max_steps not in (1, 2):
        raise QuestionUnavailable(422, 'Unsupported question or step limit')
    if detail not in {'full', 'compact'} or (expected_payload_sha256 is not None
            and not re.fullmatch(r'[a-f0-9]{64}', expected_payload_sha256)):
        raise QuestionUnavailable(422, 'Invalid source detail or input version')
    if ((kind == 'round') != (round_number is not None)
            or (kind == 'player') != (player is not None)
            or (kind == 'player' and not player.strip())):
        raise QuestionUnavailable(422, 'Supply only the parameter required by this question')
    response = dict(task_id=task_id, kind=kind, status='unknown', answer='', facts=[], sources=[],
                    scope='current_match', query_version='current_match_questions_v1', trace=[], provenance={}, complete=False,
                    matched_rounds=0, unknown_rounds=0, truncated=False,
                    budget={'max_steps': max_steps, 'steps_used': 0, 'model_calls': 0})

    def step(name):
        if response['budget']['steps_used'] >= max_steps:
            response.update(status='budget_exhausted', answer='本次查询已达到步骤上限，未生成结论。')
            return False
        response['budget']['steps_used'] += 1
        response['trace'].append({'tool': name, 'status': 'completed'})
        return True

    step('read_saved_input')
    saved = store.read_input(task_id)
    if saved is None:
        raise QuestionUnavailable(404, 'Saved analysis not found')
    if saved['status'] != 'SUCCESS':
        raise QuestionUnavailable(409, 'Questions require a completed saved analysis')
    encoded = saved['input_json']
    try:
        metadata = json.loads(saved['metadata'])
        if not encoded or hashlib.sha256(encoded.encode()).hexdigest() != metadata.get('payload_sha256'):
            raise QuestionUnavailable(409, 'Saved input is missing or failed its integrity check')
        if expected_payload_sha256 is not None and expected_payload_sha256 != metadata['payload_sha256']:
            raise QuestionUnavailable(409, '比赛输入版本已变化，请重新打开报告后查询。')
        match = json.loads(encoded)
        rounds = match['rounds']
        if not isinstance(rounds, list) or not all(isinstance(r, dict) for r in rounds):
            raise ValueError('Invalid rounds')
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        if isinstance(error, QuestionUnavailable):
            raise
        raise QuestionUnavailable(409, 'Saved input cannot be read') from None
    response['provenance'] = dict(match_id=match.get('match_id'), map_name=match.get('map_name'),
        payload_sha256=metadata['payload_sha256'], code_commit=saved['code_commit'])
    if not step('query_current_match'):
        return response
    if not rounds or len(rounds) > MAX_ROUNDS:
        response['answer'] = f'当前输入没有回合或超过 {MAX_ROUNDS} 回合的查询上限，无法可靠回答。'
        return response

    numbers = [r.get('round_number') for r in rounds]
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in numbers):
        response['answer'] = '当前输入没有可靠的回合编号，无法唯一关联来源。'
        return response
    if len(set(numbers)) != len(numbers):
        response['answer'] = '当前输入包含重复回合编号，无法唯一关联来源。'
        return response
    try:
        metrics = calculate_metrics(rounds)
    except (TypeError, ValueError, KeyError, AttributeError):
        raise QuestionUnavailable(409, 'Saved input has invalid event structure') from None
    summaries = metrics['round_summaries']
    selected = []
    unknown = 0
    if kind == 'round':
        selected = [i for i, r in enumerate(summaries) if r['round_number'] == round_number]
        response['answer'] = f'当前解析记录中{"找到" if selected else "未找到"} R{round_number}。'
    elif kind == 'player':
        stats = metrics['players'].get(player)
        if stats is None:
            response['answer'] = '有效交战事件中没有该精确选手名，无法给出个人数据；这不等于此人未参赛。'
            return response
        selected = [i for i, r in enumerate(summaries)
                    if any(player in (e['killer'], e['victim']) for e in r['kill_sequence'])]
        response['facts'] = [{'player': player, **stats}]
        response['answer'] = (f"{player}：有效交战击杀 {stats['kills']}，死亡 {stats['deaths']}，"
                              f"首杀 {stats['first_kills']}。仅限当前输入，不代表历史水平；未计算 ADR 或战术能力。")
    else:
        for i, r in enumerate(summaries):
            actors = [r['opening_team']] if kind == 'opening_losses' else r['plant_teams']
            if kind == 'post_plant_losses' and not r['plants']:
                continue
            if not actors or not all(actors) or not r['winner_team']:
                unknown += 1
            elif r['winner_team'] not in actors:
                selected.append(i)
        label = '首杀后失利' if kind == 'opening_losses' else '下包后失利'
        response['answer'] = f'当前解析记录中确认 {len(selected)} 个{label}回合；另有 {unknown} 个回合信息不足。未归因于战术失误。'
    response.update(status='found' if selected else 'unknown' if unknown else 'not_found',
                    matched_rounds=len(selected), unknown_rounds=unknown, complete=not unknown,
                    truncated=len(selected) > MAX_SOURCES)
    for i in selected[:MAX_SOURCES]:
        source = build_current_round_evidence(match, summaries[i], include_content=detail == 'full')
        citation = f'C{i + 2}'
        response['sources'].append({'citation': citation, **source})
        if kind != 'player':
            fact = {**summaries[i], 'citation': citation}
            if detail == 'compact':
                fact.pop('kill_sequence', None)
            response['facts'].append(fact)
    if response['truncated']:
        response['answer'] += f' 来源仅展示前 {MAX_SOURCES} 个回合，计数覆盖全部输入回合。'
    return response
