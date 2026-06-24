"""Agent-control and bookkeeping tools: spawn/monitor sub-agents, inter-agent
messaging, plan management, finding storage, and task completion."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from .base import Tool, ToolError

if TYPE_CHECKING:
    from ..agents import Agent


# --------------------------------------------------------------------------- #
# Spawning & monitoring
# --------------------------------------------------------------------------- #
async def _h_spawn_agent(agent: "Agent", args: dict[str, Any]) -> str:
    """Create and run a specialised sub-agent for a bounded sub-task.

    Validates the requested role, enforces the spawn limits (depth / total /
    per-parent via ``session.can_spawn``), then wraps the caller's task + context
    into a tightly-scoped brief and starts the child. With ``wait=True`` (default)
    it blocks until the child finishes and returns its result; otherwise it returns
    immediately with the child's id so the caller can poll/await it later.
    To change how sub-agents are briefed, edit ``brief`` below. To change the
    spawn limits, see ``Session.can_spawn`` in session.py.
    """
    role = args.get("role", "")
    task = args.get("task", "")
    done_when = args.get("done_when", "")
    context = args.get("context", "")
    wait = args.get("wait", True)
    if not role or not task:
        raise ToolError("role and task are required")
    from ..roles import ROLES

    valid = set(agent.session.roles) or set(ROLES)
    valid.discard("orchestrator")
    if role not in valid:
        raise ToolError(f"Unknown role '{role}'. Available: {', '.join(sorted(valid))}")
    ok, why = agent.session.can_spawn(agent)
    if not ok:
        raise ToolError(f"Cannot spawn sub-agent: {why}. Do the work directly or consolidate.")
    # Compose a tightly-scoped brief so the sub-agent does exactly one task and finishes.
    ctx_block = f"CONTEXT YOU NEED (from {agent.name}):\n{context.strip()}\n\n" if context.strip() else ""
    brief = (
        f"YOUR SINGLE TASK (assigned by {agent.name}):\n{task}\n\n"
        f"{ctx_block}"
        f"DEFINITION OF DONE: {done_when or 'the task above is fully and verifiably completed'}.\n\n"
        f"Do only this task. When the definition of done is met, call `finish` with a concise "
        f"summary and the concrete evidence/results. Do not expand scope."
    )
    child = await agent.session.create_agent(role=role, task=brief, parent=agent)
    handle = agent.session.start_agent(child)
    if wait:
        agent._set_status("waiting_subagent")
        try:
            result = await handle
        finally:
            agent._set_status("running")
        return _subagent_result_text(child, result)
    return (f"Spawned sub-agent {child.name} ({role}), id={child.id}. Running in background. "
            f"When you later collect it with wait_for_agent you will need to VALIDATE it.")


def _subagent_result_text(child: "Agent", result: str) -> str:
    """Format a finished sub-agent's result for the parent, including the mandatory
    validation instruction when the child is awaiting sign-off."""
    head = f"Sub-agent {child.name} ({child.role}, id={child.id}) returned.\nResult:\n{result}"
    if child.awaiting_validation:
        return (
            head
            + f"\n\n>>> {child.name} is now AWAITING YOUR VALIDATION — it will not close until you "
            f"decide. Review the result above, then call `validate_agent` with agent_id={child.id}:\n"
            f"  • accept=true  -> the result is good; close the sub-agent for good.\n"
            f"  • accept=false + message='...'  -> send it back to keep working with more "
            f"instructions (it resumes and replies).\n"
            f"If the result is unusable, you may instead stop it and spawn a different agent."
        )
    if child.status == "error":
        return head + f"\n\n(The sub-agent ERRORED — no validation needed. Decide how to proceed.)"
    return head


async def _h_get_agent_status(agent: "Agent", args: dict[str, Any]) -> str:
    """Return another agent's id/name/role/status and a short slice of its result.
    Used by a parent to poll a background sub-agent without blocking on it."""
    aid = args.get("agent_id", "")
    target = agent.session.get_agent(aid)
    if not target:
        raise ToolError(f"No agent with id {aid}")
    lines = [f"id={target.id} name={target.name} role={target.role} status={target.status}"]
    if target.result:
        lines.append(f"result: {target.result[:500]}")
    return "\n".join(lines)


async def _h_list_agents(agent: "Agent", args: dict[str, Any]) -> str:
    """List every agent in the session (id, name, role, status, parent) as text."""
    out = []
    for a in agent.session.agents.values():
        out.append(f"{a.id} {a.name} role={a.role} status={a.status} parent={a.parent_id}")
    return "\n".join(out) if out else "(no agents)"


async def _h_wait_for_agent(agent: "Agent", args: dict[str, Any]) -> str:
    """Block until a (typically background-spawned) sub-agent finishes, then return
    its result. Delegates the actual awaiting to ``Session.wait_for``."""
    aid = args.get("agent_id", "")
    target = agent.session.get_agent(aid)
    if not target:
        raise ToolError(f"No agent with id {aid}")
    agent._set_status("waiting_subagent")
    try:
        result = await agent.session.wait_for(target)
    finally:
        agent._set_status("running")
    return _subagent_result_text(target, result)


async def _h_validate_agent(agent: "Agent", args: dict[str, Any]) -> str:
    """Validate (or send back) a sub-agent that finished and is awaiting your sign-off.

    A spawned sub-agent does not close until its parent validates it. ``accept=true`` closes it
    for good (its result becomes shared role memory). ``accept=false`` (with a ``message``) sends
    it back to keep working with extra instructions: it resumes, replies, and again awaits your
    validation. Only the agent that spawned a sub-agent may validate it."""
    aid = args.get("agent_id", "")
    accept = args.get("accept")
    message = (args.get("message") or "").strip()
    target = agent.session.get_agent(aid)
    if not target:
        raise ToolError(f"No agent with id {aid}")
    if target.parent_id != agent.id:
        raise ToolError(f"You did not spawn {target.name}; only its parent may validate it.")
    if accept is None:
        raise ToolError("accept (true|false) is required: true to close it, false to send it back.")
    if not accept:
        if not message:
            raise ToolError("To send the sub-agent back, provide a `message` with further instructions.")
        if target.is_running:
            target.deliver(f"[PARENT FEEDBACK] {message}", sender=agent.name)
            return (f"{target.name} is still active; your feedback was delivered and it will act on "
                    f"it. Collect it again with wait_for_agent, then validate.")
        # Resume the (idle, awaiting-validation) child synchronously with the new instructions; it
        # works, replies, and ends back in waiting_validation.
        target.deliver(f"[PARENT FEEDBACK] {message}", sender=agent.name)
        agent._set_status("waiting_subagent")
        try:
            new_result = await target.run_followup()
        finally:
            agent._set_status("running")
        return (f"Sent {target.name} back with your instructions. It replied:\n{new_result}\n\n"
                f"It is AWAITING YOUR VALIDATION again — call `validate_agent` with "
                f"agent_id={target.id} (accept=true) when satisfied, or send it back once more.")
    if not target.awaiting_validation and target.status != "done":
        return (f"{target.name} is not awaiting validation (status={target.status}); nothing to accept.")
    target.mark_validated()
    return f"Accepted and closed {target.name}. Its result was recorded for future agents."


async def _h_message_agent(agent: "Agent", args: dict[str, Any]) -> str:
    """Send a message to another agent's inbox. If that agent is still running it
    picks the message up on its next turn; if it has already finished, it is
    re-activated (``run_followup``) to answer synchronously and the reply is returned."""
    aid = args.get("agent_id", "")
    message = args.get("message", "")
    if not message:
        raise ToolError("message is required")
    target = agent.session.get_agent(aid)
    if not target:
        raise ToolError(f"No agent with id {aid}")
    target.deliver(message, sender=agent.name)
    if target.is_running:
        return f"Message delivered to {target.name} (active); it will process it on its next turn."
    # Re-activate a finished/idle agent to answer the query.
    reply = await target.run_followup()
    return f"Reply from {target.name}:\n{reply}"


# --------------------------------------------------------------------------- #
# Plan management
# --------------------------------------------------------------------------- #
async def _h_update_plan(agent: "Agent", args: dict[str, Any]) -> str:
    """Create or replace the engagement plan from a list of step strings.

    Routes through ``Session.submit_plan``, which sets the plan AND applies the
    human-in-the-loop plan-approval policy: depending on settings the operator may have to
    approve it before work proceeds (and can reject-with-feedback or edit it). The returned
    status string tells the orchestrator whether it was approved, rejected (revise & resubmit),
    or edited — so it must read and act on this result rather than assuming success."""
    steps = args.get("steps", [])
    if not isinstance(steps, list) or not steps:
        raise ToolError("steps must be a non-empty list of strings")
    return await agent.session.submit_plan(agent, [str(s) for s in steps])


async def _h_set_step_status(agent: "Agent", args: dict[str, Any]) -> str:
    """Update one plan step's status by index (pending|in_progress|done|failed)."""
    index = args.get("index")
    status = args.get("status", "")
    if index is None or status not in ("pending", "in_progress", "done", "failed"):
        raise ToolError("index (int) and status (pending|in_progress|done|failed) required")
    ok = agent.session.set_step_status(int(index), status)
    if not ok:
        raise ToolError(f"No plan step at index {index}")
    return f"Step {index} -> {status}"


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #
async def _h_store_finding(agent: "Agent", args: dict[str, Any]) -> str:
    """Persist a vulnerability finding (title/severity/status + evidence data).
    Generates the id and forwards to ``Session.add_finding``, which writes the JSON
    file, the DB row, and emits a finding.stored event."""
    title = args.get("title", "")
    if not title:
        raise ToolError("title is required")
    fid = "f_" + uuid.uuid4().hex[:8]
    data = {
        "location": args.get("location", ""),
        "description": args.get("description", ""),
        "evidence": args.get("evidence", ""),
        "cwe": args.get("cwe", ""),
    }
    await agent.session.add_finding(
        fid=fid,
        agent=agent,
        title=title,
        severity=args.get("severity", "medium"),
        status=args.get("status", "candidate"),
        data=data,
    )
    return f"Stored finding {fid}: {title} [{args.get('severity', 'medium')}/{args.get('status', 'candidate')}]"


async def _h_list_findings(agent: "Agent", args: dict[str, Any]) -> str:
    """Return a one-line-per-finding summary of everything stored this session."""
    findings = agent.session.findings
    if not findings:
        return "(no findings yet)"
    out = []
    for f in findings.values():
        out.append(f"{f['id']} [{f['severity']}/{f['status']}] {f['title']} @ {f['data'].get('location', '?')}")
    return "\n".join(out)


async def _h_read_finding(agent: "Agent", args: dict[str, Any]) -> str:
    """Return the full JSON detail of one stored finding by id."""
    fid = args.get("finding_id", "")
    f = agent.session.findings.get(fid)
    if not f:
        raise ToolError(f"No finding {fid}")
    import json

    return json.dumps(f, indent=2)


# --------------------------------------------------------------------------- #
# Completion
# --------------------------------------------------------------------------- #
async def _h_finish(agent: "Agent", args: dict[str, Any]) -> str:
    """Mark this agent complete and record its summary as the result. The summary
    becomes the agent's shared-role memory (see ``Session.record_agent_memory``)."""
    summary = args.get("summary", "")
    agent.finish(summary)
    return "Task marked complete."


async def _h_ask_parent(agent: "Agent", args: dict[str, Any]) -> str:
    """Escalate to the spawning (parent) agent for extra scope/permission. If the
    parent is idle it is re-activated to answer; if it is busy awaiting this agent's
    result (would deadlock), the agent is told to finish and report the need instead."""
    question = args.get("question", "")
    if not question:
        raise ToolError("question is required — state what extra scope/test you need and why")
    parent = agent.session.get_agent(agent.parent_id) if agent.parent_id else None
    if not parent:
        return ("You have no parent agent (you are the root). Decide within your own judgement, "
                "or finish and report the need to the operator.")
    parent.deliver(f"[{agent.name} asks]: {question}", sender=agent.name)
    if parent.is_running:
        # Parent is active (typically blocked awaiting your result) -> can't reply now
        # without deadlock. The escalation path is to finish and report.
        return ("Your question was delivered to your parent, but it is currently busy (likely "
                "awaiting your result) and cannot reply synchronously. Either proceed strictly "
                "within your assigned scope, or call `finish` now and clearly state in your summary "
                "the additional test/scope you need so your parent can decide and re-delegate.")
    reply = await parent.run_followup()
    return f"Your parent ({parent.name}) replied:\n{reply}"


async def _h_load_skill(agent: "Agent", args: dict[str, Any]) -> str:
    """Pull one of the agent's offered on-demand skills into context at runtime.
    Validates the skill is in ``agent.loadable_skills``, returns its markdown body
    for the model to apply, emits an agent.skill_loaded event, and persists it so the
    chat shows the load after a restart. (Static 'always' skills are added at spawn
    time in ``Session.create_agent`` instead.)"""
    from .. import skills as skills_mod
    from ..events import E, bus

    name = args.get("name", "")
    if not name:
        raise ToolError("name is required — the skill to load")
    loadable = getattr(agent, "loadable_skills", set()) or set()
    if name not in loadable:
        avail = ", ".join(sorted(loadable)) or "(none)"
        raise ToolError(f"Skill '{name}' is not available to you. Loadable skills: {avail}")
    if name in getattr(agent, "loaded_skills", set()):
        return f"Skill '{name}' is already loaded; apply it."
    content = skills_mod.read_skill(name).strip()
    if not content:
        raise ToolError(f"Skill '{name}' has no content.")
    agent.loaded_skills.add(name)
    title = next((s["title"] for s in skills_mod.list_skills() if s["name"] == name), name)
    bus.emit(E.AGENT_SKILL_LOADED, agent.session.id, {"name": name, "title": title}, agent_id=agent.id)
    # persist so the chat shows it after a restart too
    try:
        await agent.session.db.add_message(agent.session.id, agent.id, "skill_loaded", {"name": name, "title": title})
    except Exception:  # noqa: BLE001
        pass
    return f"Loaded skill '{name}'. Apply this methodology:\n\n{content}"


async def _h_load_memory(agent: "Agent", args: dict[str, Any]) -> str:
    """Pull one memory file (master memory, a role's memory, or a note) into context in full.
    The agent SELECTS which memory it wants beyond what was auto-injected. Validates the name
    against the session's available memory files and returns the file's content."""
    from ..events import E, bus

    name = (args.get("name") or "").strip()
    if not name:
        raise ToolError("name is required — the memory file to load (see 'MEMORY FILES YOU MAY LOAD')")
    available = agent.session._loadable_memory_files()
    # be lenient: accept "master" for "master.md", etc.
    if name not in available:
        alt = name if name.endswith(".md") else f"{name}.md"
        if alt in available:
            name = alt
        else:
            raise ToolError(f"No memory file '{name}'. Available: {', '.join(available) or '(none)'}")
    content = agent.session.read_memory_file(name).strip()
    if not content:
        return f"Memory file '{name}' is empty."
    bus.emit(E.AGENT_MEMORY_LOADED, agent.session.id,
             {"files": [f"memory/{name}"], "on_demand": True, "chars": len(content)}, agent_id=agent.id)
    try:
        await agent.session.db.add_message(agent.session.id, agent.id, "memory_loaded",
                                           {"files": [f"memory/{name}"], "on_demand": True})
    except Exception:  # noqa: BLE001
        pass
    return f"Loaded memory/{name}:\n\n{content}"


async def _h_notify_user(agent: "Agent", args: dict[str, Any]) -> str:
    """Post a plain-language progress update to the operator's chat (the orchestrator's
    narration channel). Emits agent.narration and persists it to the discussion feed."""
    message = args.get("message", "")
    if not message:
        raise ToolError("message is required")
    from ..events import E, bus

    bus.emit(E.AGENT_NARRATION, agent.session.id, {"message": message,
             "role": agent.role, "name": agent.name}, agent_id=agent.id)
    # Persist so the narration survives a restart and reloads with the discussion.
    await agent.session.db.add_message(agent.session.id, agent.id, "narration", {"message": message})
    return "Operator notified."


async def _h_select_tools(agent: "Agent", args: dict[str, Any]) -> str:
    """(tool_selector agents only) Record the chosen subset of candidate tool names.
    Filters to known candidates, clamps to the budget, stores them on
    ``agent.selected_tools`` (read back by ``Session._budget_tools``), and finishes.
    An empty list is valid and means 'give the target agent only its mandatory tools'."""
    names = args.get("tool_names", [])
    if not isinstance(names, list):
        raise ToolError("tool_names must be a list of tool-name strings (use [] if none are relevant)")
    candidates: set[str] = getattr(agent, "selection_candidates", set()) or set()
    budget = int(getattr(agent, "selection_budget", len(names)) or len(names))
    chosen = [str(n) for n in names if str(n) in candidates]
    unknown = [str(n) for n in names if str(n) not in candidates]
    if len(chosen) > budget:
        chosen = chosen[:budget]
    # An empty selection is valid: the selector decided none of the optional tools fit.
    agent.selected_tools = chosen
    if chosen:
        agent.finish(f"Selected {len(chosen)} tools: {', '.join(chosen)}")
        msg = f"Recorded selection of {len(chosen)} tool(s): {', '.join(chosen)}."
    else:
        agent.finish("Selected no optional tools (none were relevant to the task).")
        msg = "Recorded an empty selection — no optional tools given to the agent."
    if unknown:
        msg += f" Ignored {len(unknown)} unknown name(s): {', '.join(unknown[:6])}."
    return msg


async def _h_request_file_load(agent: "Agent", args: dict[str, Any]) -> str:
    """Pause and ask the operator to provide/load a file (e.g. a binary to open in
    Ghidra). Blocks via ``Session.request_input`` until the operator answers in the UI;
    returns their reply (typically a path)."""
    reason = args.get("reason", "")
    suggested = args.get("suggested_path", "")
    if not reason:
        raise ToolError("reason is required — explain why you need the file loaded")
    message = (
        f"The {agent.name} agent requests that you load a file into the reverse tool.\n"
        f"Reason: {reason}"
    )
    if suggested:
        message += f"\nSuggested path: {suggested}"
    answer = await agent.session.request_input(agent, message, kind="file", suggestion=suggested)
    if not answer:
        return "Operator did not provide a file (request cancelled or empty). Proceed without it or ask again."
    return f"Operator response: {answer}"


async def _h_ask_user(agent: "Agent", args: dict[str, Any]) -> str:
    """Ask the human operator a question and BLOCK until they answer in the UI. Use this whenever
    you genuinely need a decision, a credential, missing scope, or clarification only the operator
    can give. Raising the request alerts the operator. Returns their typed answer (empty if they
    skip)."""
    question = (args.get("question") or "").strip()
    if not question:
        raise ToolError("question is required — ask the operator a specific, answerable question")
    suggestion = (args.get("suggestion") or "").strip()
    answer = await agent.session.request_input(agent, question, kind="question", suggestion=suggestion)
    if not answer:
        return ("The operator did not answer (they skipped or cancelled). Proceed with your best "
                "judgement within scope, or `finish` and report that you needed operator input.")
    return f"The operator answered: {answer}"


def _spawn_tool() -> Tool:
    """Build the spawn_agent Tool definition (kept separate because its schema/description
    is the longest). Edit the description here to change how the model is told to delegate."""
    return Tool(
        name="spawn_agent",
        description="Spawn a specialised pentest sub-agent to handle a sub-task. Roles: "
        "recon (host/service discovery & attack-surface mapping), "
        "web_app (web application testing), "
        "network (network/infrastructure & service testing), "
        "exploitation (exploit validated, in-scope findings), "
        "post_exploit (scoped post-exploitation). "
        "By default waits for the sub-agent to finish and returns its result. Give each "
        "sub-agent ONE narrow task, an explicit `done_when`, and the `context` it needs. "
        "IMPORTANT: when it finishes it will AWAIT YOUR VALIDATION — you must review its result "
        "and call `validate_agent` to accept (close it), send it back with more instructions, or "
        "discard it. It does not close on its own.",
        input_schema={
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Sub-agent role to spawn (see the available roles listed in your system prompt)."},
                "task": {"type": "string", "description": "One specific, bounded task for the sub-agent."},
                "done_when": {
                    "type": "string",
                    "description": "Explicit completion criterion the sub-agent must meet before finishing.",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant background the sub-agent needs: target details, what is known "
                    "so far, prior findings, file paths/addresses — so it doesn't have to ask you back.",
                },
                "wait": {"type": "boolean", "description": "Wait for completion (default true)."},
            },
            "required": ["role", "task", "done_when"],
        },
        handler=_h_spawn_agent,
    )


def control_tools() -> dict[str, Tool]:
    """All agent-control / bookkeeping tools, keyed by name. These are 'internal'
    (mandatory) tools — they are never trimmed by the tool_selector. To add one, write
    an ``_h_*`` handler above and add a ``Tool(...)`` entry here (or use custom.py)."""
    return {
        "spawn_agent": _spawn_tool(),
        "get_agent_status": Tool(
            name="get_agent_status",
            description="Get the current status and latest result of another agent.",
            input_schema={
                "type": "object",
                "properties": {"agent_id": {"type": "string"}},
                "required": ["agent_id"],
            },
            handler=_h_get_agent_status,
        ),
        "list_agents": Tool(
            name="list_agents",
            description="List all agents in this session with their status.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=_h_list_agents,
        ),
        "wait_for_agent": Tool(
            name="wait_for_agent",
            description="Block until a background sub-agent finishes, then return its result.",
            input_schema={
                "type": "object",
                "properties": {"agent_id": {"type": "string"}},
                "required": ["agent_id"],
            },
            handler=_h_wait_for_agent,
        ),
        "message_agent": Tool(
            name="message_agent",
            description="Send a message/question to another agent. If that agent has already "
            "finished, it is re-activated to answer (use to query the reverse-analysis agent "
            "for more information while building a PoC).",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["agent_id", "message"],
            },
            handler=_h_message_agent,
        ),
        "update_plan": Tool(
            name="update_plan",
            description="Create or replace the reverse-engineering plan as an ordered list of steps.",
            input_schema={
                "type": "object",
                "properties": {"steps": {"type": "array", "items": {"type": "string"}}},
                "required": ["steps"],
            },
            handler=_h_update_plan,
        ),
        "set_step_status": Tool(
            name="set_step_status",
            description="Update the status of a plan step by its index.",
            input_schema={
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "done", "failed"]},
                },
                "required": ["index", "status"],
            },
            handler=_h_set_step_status,
        ),
        "store_finding": Tool(
            name="store_finding",
            description="Persist a vulnerability finding to the session's findings store. "
            "Use status='validated' only after static confirmation.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "low", "medium", "high", "critical"]},
                    "status": {"type": "string", "enum": ["candidate", "validated", "rejected"]},
                    "location": {"type": "string", "description": "Function/address/file."},
                    "description": {"type": "string"},
                    "evidence": {"type": "string", "description": "Decompiled code or reasoning supporting the finding."},
                    "cwe": {"type": "string"},
                },
                "required": ["title"],
            },
            handler=_h_store_finding,
        ),
        "list_findings": Tool(
            name="list_findings",
            description="List all stored findings in this session.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=_h_list_findings,
        ),
        "read_finding": Tool(
            name="read_finding",
            description="Read the full detail of a stored finding by id.",
            input_schema={
                "type": "object",
                "properties": {"finding_id": {"type": "string"}},
                "required": ["finding_id"],
            },
            handler=_h_read_finding,
        ),
        "request_file_load": Tool(
            name="request_file_load",
            description="Ask the operator to load a specific file into the reverse-engineering tool "
            "(e.g. a binary/library to open in Ghidra) when you need one that isn't available yet. "
            "Clearly explain why. This pauses you until the operator answers via the chat; their reply "
            "(typically a file path) is returned to you. Use this whenever progress depends on a file "
            "only the operator can provide.",
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why you need this file / what you'll do with it."},
                    "suggested_path": {"type": "string", "description": "A path you expect, if known."},
                },
                "required": ["reason"],
            },
            handler=_h_request_file_load,
        ),
        "load_skill": Tool(
            name="load_skill",
            description="Load one of the on-demand skills listed in your system prompt (a markdown "
            "playbook of methodology) when a task would benefit from it. Its guidance is returned to "
            "you and applied for the rest of your work. Only skills offered to you can be loaded.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "The skill name to load."}},
                "required": ["name"],
            },
            handler=_h_load_skill,
        ),
        "ask_parent": Tool(
            name="ask_parent",
            description="Ask the agent that spawned you for guidance or permission to go beyond your "
            "assigned task — use this instead of expanding your own scope. If your parent is busy "
            "awaiting your result, you'll be told to finish and report the need in your summary so it "
            "can decide. Returns the parent's reply when it can answer.",
            input_schema={
                "type": "object",
                "properties": {"question": {"type": "string",
                               "description": "What extra scope/test you need and why."}},
                "required": ["question"],
            },
            handler=_h_ask_parent,
        ),
        "notify_user": Tool(
            name="notify_user",
            description="Post a short, plain-language progress update to the operator's chat so a "
            "human can follow what is happening / has happened. Use it liberally to narrate the "
            "engagement: the plan, each delegation, each sub-agent's result, findings, and the wrap-up. "
            "This is one-way (no answer expected) — to ASK the operator something, use `ask_user`.",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string", "description": "The update, written for a human."}},
                "required": ["message"],
            },
            handler=_h_notify_user,
        ),
        "load_memory": Tool(
            name="load_memory",
            description="Load one memory file into your context in full — master memory, another "
            "role's memory, or a specific note an earlier agent wrote. The engagement's MASTER "
            "MEMORY is already injected for you; use this to pull additional memory you decide is "
            "relevant to your task. Pass the file name shown under 'MEMORY FILES YOU MAY LOAD'.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string",
                               "description": "Memory file name, e.g. master.md, role_recon.md, notes_creds.md."}},
                "required": ["name"],
            },
            handler=_h_load_memory,
        ),
        "ask_user": Tool(
            name="ask_user",
            description="Ask the human OPERATOR a question and wait for their answer (this alerts "
            "them). Use it when you need a decision, a credential, extra/clarified scope, or "
            "guidance only a human can give — for example before a potentially impactful action, or "
            "when you're blocked (e.g. the Kali container is down). Ask one specific, answerable "
            "question. Returns the operator's reply. (To escalate to the agent that spawned you "
            "instead, use `ask_parent`; to just narrate progress, use `notify_user`.)",
            input_schema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "A specific question for the operator."},
                    "suggestion": {"type": "string", "description": "Optional default/suggested answer to pre-fill."},
                },
                "required": ["question"],
            },
            handler=_h_ask_user,
        ),
        "select_tools": Tool(
            name="select_tools",
            description="(Tool-selector agents only) Return the subset of CANDIDATE TOOLS chosen "
            "for the target agent, by their exact names. Calling this completes your task.",
            input_schema={
                "type": "object",
                "properties": {
                    "tool_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact names of the chosen tools (at most the stated budget).",
                    },
                    "reasoning": {"type": "string", "description": "Optional brief justification."},
                },
                "required": ["tool_names"],
            },
            handler=_h_select_tools,
        ),
        "validate_agent": Tool(
            name="validate_agent",
            description="Validate a sub-agent you spawned that has finished and is AWAITING YOUR "
            "VALIDATION. accept=true closes it for good (its result is kept as shared memory). "
            "accept=false WITH a `message` sends it back to keep working with your extra "
            "instructions (it resumes, replies, and again awaits your validation). A finished "
            "sub-agent will NOT close until you validate it — review its result first.",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Id of the sub-agent to validate."},
                    "accept": {"type": "boolean", "description": "true = accept & close; false = send back."},
                    "message": {"type": "string", "description": "Required when accept=false: further instructions for the sub-agent."},
                },
                "required": ["agent_id", "accept"],
            },
            handler=_h_validate_agent,
        ),
        "finish": Tool(
            name="finish",
            description="Signal that YOUR task is complete. Provide a concise summary of what was "
            "accomplished and the key results/evidence. If you are a sub-agent, finishing hands "
            "your result to your parent for VALIDATION — your parent may accept it (you close) or "
            "send it back with more instructions for you to continue, so make the summary complete.",
            input_schema={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            },
            handler=_h_finish,
        ),
    }
