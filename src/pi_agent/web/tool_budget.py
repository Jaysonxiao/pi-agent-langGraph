"""Persistent per-user-turn budgets; a resumed tool node never consumes twice."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from pi_agent.tools.approval_store import DurableProposal
from pi_agent.web.store import WebStore


def initialize_tool_budgets(store: WebStore) -> None:
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS web_tool_turns (
                session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                limits_json TEXT NOT NULL, tools_json TEXT NOT NULL,
                PRIMARY KEY(session_id, turn_id));
            CREATE TABLE IF NOT EXISTS web_tool_calls (
                session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                message_id TEXT NOT NULL, tool_call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL, allowed INTEGER NOT NULL,
                PRIMARY KEY(session_id, turn_id, message_id, tool_call_id));
            CREATE INDEX IF NOT EXISTS web_tool_call_usage
                ON web_tool_calls(session_id, turn_id, tool_name, allowed);
        """)


@dataclass(frozen=True, slots=True)
class WebToolBudget:
    store: WebStore
    session_id: str
    turn_id: str
    limits: Mapping[str, int]
    tools: tuple[str, ...]

    def reserve(self, *, message_id: str, tool_call_id: str, tool_name: str) -> bool:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT tool_name,allowed FROM web_tool_calls "
                "WHERE session_id=? AND turn_id=? AND message_id=? AND tool_call_id=?",
                (self.session_id, self.turn_id, message_id, tool_call_id),
            ).fetchone()
            if existing is not None:
                if existing["tool_name"] != tool_name:
                    raise ValueError("Tool operation identity changed.")
                return bool(existing["allowed"])
            used = int(
                db.execute(
                    "SELECT COUNT(*) FROM web_tool_calls "
                    "WHERE session_id=? AND turn_id=? AND tool_name=? AND allowed=1",
                    (self.session_id, self.turn_id, tool_name),
                ).fetchone()[0]
            )
            allowed = used < self.limits.get(tool_name, 0)
            db.execute(
                "INSERT INTO web_tool_calls VALUES (?,?,?,?,?,?)",
                (self.session_id, self.turn_id, message_id, tool_call_id, tool_name, int(allowed)),
            )
        return allowed


def open_tool_budget(
    store: WebStore,
    session_id: str,
    turn_id: str,
    limits: Mapping[str, int],
    tools: tuple[str, ...],
    *,
    history: Sequence[AnyMessage] = (),
    proposals: Sequence[DurableProposal] = (),
) -> WebToolBudget:
    """Freeze new-turn settings, or reopen the exact budget used before an interruption."""
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        inserted = db.execute(
            "INSERT OR IGNORE INTO web_tool_turns VALUES (?,?,?,?)",
            (session_id, turn_id, json.dumps(dict(limits)), json.dumps(tools)),
        ).rowcount
        if inserted:
            # Pre-upgrade checkpoints have no budget. Preserve identifiable past
            # attempts; an approved operation keeps its reservation even over the new cap.
            for message, call, tool, allowed in _legacy_attempts(history, proposals):
                db.execute(
                    "INSERT OR IGNORE INTO web_tool_calls VALUES (?,?,?,?,?,?)",
                    (session_id, turn_id, message, call, tool, int(allowed)),
                )
        row = db.execute(
            "SELECT limits_json,tools_json FROM web_tool_turns WHERE session_id=? AND turn_id=?",
            (session_id, turn_id),
        ).fetchone()
        assert row is not None
        return WebToolBudget(
            store,
            session_id,
            turn_id,
            json.loads(row["limits_json"]),
            tuple(json.loads(row["tools_json"])),
        )


def _legacy_attempts(
    messages: Sequence[AnyMessage], proposals: Sequence[DurableProposal]
) -> list[tuple[str, str, str, bool]]:
    last_user = next(
        (
            index
            for index in reversed(range(len(messages)))
            if isinstance(messages[index], HumanMessage)
        ),
        -1,
    )
    known = {(proposal.message_id, proposal.tool_call_id) for proposal in proposals}
    attempts: list[tuple[str, str, str, bool]] = []
    for index in range(last_user + 1, len(messages)):
        message = messages[index]
        if not isinstance(message, AIMessage) or not message.id:
            continue
        results: dict[str, ToolMessage] = {}
        for following in messages[index + 1 :]:
            if not isinstance(following, ToolMessage):
                break
            results[following.tool_call_id] = following
        prefix = max(
            (
                i
                for i, call in enumerate(message.tool_calls)
                if (message.id, call.get("id")) in known
            ),
            default=-1,
        )
        for i, call in enumerate(message.tool_calls):
            call_id = call.get("id")
            if not call_id or (i > prefix and call_id not in results):
                continue
            allowed = True
            result = results.get(call_id)
            if result is not None and result.status == "error" and isinstance(result.content, str):
                try:
                    payload = json.loads(result.content)
                    allowed = not (
                        isinstance(payload, dict)
                        and payload.get("code") in {"tool_call_limit", "tool_round_limit"}
                    )
                except ValueError:
                    pass
            attempts.append((message.id, call_id, call["name"], allowed))
    return attempts
