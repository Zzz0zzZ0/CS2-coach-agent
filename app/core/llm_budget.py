"""A local, persistent allowance for the shared text-model entry point."""
import asyncio
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool


class ModelCallStopped(RuntimeError):
    """Safe reason code only: never relay provider messages or request content."""


def reported_total(response):
    usage = getattr(response, 'usage_metadata', None) or {}
    if not usage:
        usage = (getattr(response, 'response_metadata', None) or {}).get('token_usage', {}) or {}
    value = usage.get('total_tokens')
    return value if type(value) is int and value > 0 else None


class ModelBudget:
    def __init__(self, path, token_limit, call_limit):
        self.path = (Path(__file__).resolve().parents[2] / path).resolve()
        if not 0 <= token_limit <= 1_000_000 or not 0 <= call_limit <= 100_000:
            raise ModelCallStopped('invalid_budget_configuration')
        self.token_limit, self.call_limit = token_limit, call_limit

    def _snapshot(self, db):
        limits = db.execute('SELECT token_limit, call_limit FROM budget WHERE id=1').fetchone()
        count, reported, reserved = db.execute('''SELECT count(*), coalesce(sum(total_tokens),0),
            coalesce(sum(CASE WHEN total_tokens IS NULL THEN allowance ELSE 0 END),0) FROM calls''').fetchone()
        stopped = db.execute("SELECT status FROM calls WHERE status != 'completed' ORDER BY created_at LIMIT 1").fetchone()
        reason = stopped[0] if stopped else None
        if limits != (self.token_limit, self.call_limit):
            reason = 'configuration_mismatch'
        elif not reason and (count >= limits[1] or reported + reserved >= limits[0]):
            reason = 'budget_exhausted'
        return {'status': 'stopped' if reason else 'ready', 'stop_reason': reason,
                'token_limit': limits[0], 'call_limit': limits[1], 'calls': count,
                'reported_tokens': reported, 'unsettled_allowance': reserved,
                'remaining_local_allowance': max(0, limits[0] - reported - reserved),
                'accounting_complete': reserved == 0, 'provider_remaining_tokens': None}

    def status(self):
        if not self.path.exists():
            return {'status': 'ready' if self.token_limit and self.call_limit else 'stopped',
                    'stop_reason': None if self.token_limit and self.call_limit else 'budget_exhausted',
                    'token_limit': self.token_limit, 'call_limit': self.call_limit, 'calls': 0,
                    'reported_tokens': 0, 'unsettled_allowance': 0,
                    'remaining_local_allowance': self.token_limit,
                    'accounting_complete': True, 'provider_remaining_tokens': None}
        try:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                return self._snapshot(db)
        except sqlite3.Error:
            raise ModelCallStopped('ledger_unavailable') from None

    def reserve(self, allowance, prompt_hash):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), token_limit INTEGER, call_limit INTEGER)')
                db.execute('INSERT OR IGNORE INTO budget VALUES (1,?,?)', (self.token_limit, self.call_limit))
                db.execute('''CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, created_at REAL,
                    finished_at REAL, model TEXT, prompt_sha256 TEXT, allowance INTEGER,
                    total_tokens INTEGER, status TEXT)''')
                snapshot = self._snapshot(db)
                if snapshot['stop_reason']:
                    db.commit()
                    raise ModelCallStopped(snapshot['stop_reason'])
                if allowance > snapshot['remaining_local_allowance']:
                    db.commit()
                    raise ModelCallStopped('request_exceeds_remaining_allowance')
                request_id = uuid.uuid4().hex
                # ponytail: one in-flight call per local ledger; queue only if throughput requires it.
                db.execute('INSERT INTO calls VALUES (?,?,NULL,?,?,?,NULL,?)',
                           (request_id, time.time(), 'qwen3.8-flash', prompt_hash, allowance, 'pending'))
                return request_id
        except (OSError, sqlite3.Error):
            raise ModelCallStopped('ledger_unavailable') from None

    def finish(self, request_id, status, total=None):
        try:
            with closing(sqlite3.connect(self.path, timeout=2)) as db, db:
                updated = db.execute("UPDATE calls SET finished_at=?, status=?, total_tokens=? WHERE id=? AND status='pending'",
                                     (time.time(), status, total, request_id))
                if updated.rowcount != 1:
                    raise ModelCallStopped('ledger_unavailable')
        except sqlite3.Error:
            raise ModelCallStopped('ledger_unavailable') from None


class BudgetedChatModel(Runnable):
    """Supports existing prompt chains and tools, with one reservation per request."""
    def __init__(self, model, budget, max_tokens, timeout, schemas=None):
        if max_tokens <= 0 or not 0 < timeout <= 120:
            raise ModelCallStopped('invalid_call_configuration')
        self.model, self.budget = model, budget
        self.max_tokens, self.timeout = max_tokens, timeout
        self.schemas = schemas or []

    def bind_tools(self, tools, **kwargs):
        if kwargs:
            raise ModelCallStopped('unsupported_call_options')
        schemas = [convert_to_openai_tool(tool) for tool in tools]
        return BudgetedChatModel(self.model.bind_tools(schemas), self.budget,
                                 self.max_tokens, self.timeout, schemas)

    def _reserve(self, value, kwargs):
        if kwargs:
            raise ModelCallStopped('unsupported_call_options')
        if isinstance(value, PromptValue):
            value = value.to_messages()
        if isinstance(value, str):
            payload = value
        elif isinstance(value, list) and all(isinstance(m, BaseMessage) and isinstance(m.content, str) for m in value):
            payload = [m.model_dump(mode='json') for m in value]
        else:
            raise ModelCallStopped('unsupported_prompt_type')
        encoded = json.dumps({'prompt': payload, 'tools': self.schemas}, ensure_ascii=False).encode('utf-8')
        # UTF-8 bytes plus protocol margin are a conservative estimate, not a billing guarantee.
        allowance = len(encoded) + 2048 + self.max_tokens
        return self.budget.reserve(allowance, hashlib.sha256(encoded).hexdigest()), allowance

    def _complete(self, request_id, allowance, response):
        total = reported_total(response)
        status = 'usage_missing' if total is None else 'estimate_exceeded' if total > allowance else 'completed'
        self.budget.finish(request_id, status, total)
        if status != 'completed':
            raise ModelCallStopped(status)
        return response

    def _failed(self, request_id, error):
        status_code = getattr(error, 'status_code', None)
        reason = 'provider_rejected' if status_code in (401, 402, 403, 429) else 'request_failed'
        if isinstance(error, asyncio.CancelledError):
            reason = 'cancelled'
        self.budget.finish(request_id, reason)
        return ModelCallStopped(reason)

    def invoke(self, input, config=None, **kwargs):
        request_id, allowance = self._reserve(input, kwargs)
        try:
            response = self.model.invoke(input, config=config)
        except Exception as error:
            raise self._failed(request_id, error) from None
        return self._complete(request_id, allowance, response)

    async def ainvoke(self, input, config=None, **kwargs):
        request_id, allowance = self._reserve(input, kwargs)
        try:
            response = await asyncio.wait_for(self.model.ainvoke(input, config=config), timeout=self.timeout)
        except asyncio.CancelledError as error:
            self._failed(request_id, error)
            raise
        except Exception as error:
            raise self._failed(request_id, error) from None
        return self._complete(request_id, allowance, response)
