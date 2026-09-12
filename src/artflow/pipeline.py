"""Validate resolved definitions without invoking production tools."""
import re

ID = re.compile(r"[a-z][a-z0-9_-]*\Z")


def validate_pipeline_definition(pipeline, artifacts, executors):
    errors = []

    def issue(path, message):
        errors.append({"path": path, "message": message})

    steps = pipeline.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return {"ok": False, "errors": [{"path": "steps", "message": "Expected nonempty steps array"}], "execution_order": []}
    by_id = {}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("id"), str) or not ID.fullmatch(step["id"]):
            issue(f"steps[{index}]", "Expected a valid id")
            continue
        sid = step["id"]
        if sid in by_id:
            issue(sid, "Duplicate step id")
        by_id[sid] = step
        if not isinstance(step.get("label"), str) or not step["label"]:
            issue(sid, "Missing label")
        for field in ("inputs", "outputs", "depends_on", "locks", "approval_artifacts"):
            values = step.get(field, [])
            if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
                issue(f"{sid}.{field}", "Expected string array")
            elif len(set(values)) != len(values):
                issue(f"{sid}.{field}", "Duplicate entries")
            elif field in {"inputs", "outputs", "approval_artifacts"}:
                for value in values:
                    if value not in artifacts:
                        issue(f"{sid}.{field}", f"Unknown artifact: {value}")
        kind = step.get("kind")
        if kind not in {"read", "command"}:
            issue(sid, "kind must be read or command")
        if kind == "command":
            executor = executors.get(step.get("executor"))
            argv = step.get("command")
            if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
                issue(sid, "command must be a nonempty string array")
            if not executor:
                issue(sid, "Unknown executor")
            elif argv not in executor.get("allowed_commands", []):
                issue(sid, "Command is not in the resolved executor allowlist")
            if type(step.get("timeout_seconds")) is not int or step["timeout_seconds"] <= 0:
                issue(sid, "timeout_seconds must be a positive integer")
            if step.get("retry_policy") not in {"safe", "manual"}:
                issue(sid, "retry_policy must be safe or manual")
            if type(step.get("writes")) is not bool:
                issue(sid, "Explicit writes boolean required")
            if step.get("writes"):
                if step.get("requires_approval") is not True:
                    issue(sid, "Write steps require approval")
                if not step.get("outputs") or not step.get("locks"):
                    issue(sid, "Write steps must declare outputs and locks")
                if not step.get("approval_artifacts"):
                    issue(sid, "Write steps must identify reviewed input artifacts")
        elif any(key in step for key in ("command", "executor")):
            issue(sid, "Read checkpoints cannot execute commands")
    if errors:
        return {"ok": False, "errors": errors, "execution_order": []}
    order, visiting, visited = [], set(), set()

    def visit(sid):
        if sid in visited:
            return
        if sid in visiting:
            issue(sid, "Dependency cycle")
            return
        visiting.add(sid)
        for dep in by_id[sid].get("depends_on", []):
            if dep not in by_id:
                issue(sid, f"Unknown dependency: {dep}")
            else:
                visit(dep)
        visiting.remove(sid)
        visited.add(sid)
        order.append(sid)
    for sid in by_id:
        visit(sid)

    def ancestors(sid, seen=None):
        seen = set() if seen is None else seen
        for dep in by_id[sid].get("depends_on", []):
            if dep in by_id and dep not in seen:
                seen.add(dep)
                ancestors(dep, seen)
        return seen

    producers = {}
    for sid, step in by_id.items():
        for artifact in step.get("outputs", []):
            if step.get("writes"):
                path = artifacts[artifact]["path"]
                for previous in producers.get(path, []):
                    issue(sid, f"Output {artifact} already owned by {previous}; use a distinct versioned path")
                producers.setdefault(path, []).append(sid)
        for artifact in step.get("inputs", []):
            for producer, other in by_id.items():
                if producer != sid and artifact in other.get("outputs", []) and producer not in ancestors(sid):
                    issue(sid, f"Input {artifact} requires dependency on {producer}")
    actions = pipeline.get("actions", {})
    if not isinstance(actions, dict) or not actions:
        issue("actions", "Declare at least one action with target steps")
        actions = {}
    for aid, action in actions.items():
        if not ID.fullmatch(aid) or not isinstance(action, dict):
            issue(f"actions.{aid}", "Invalid action")
            continue
        selected = action.get("steps")
        if not isinstance(selected, list) or not selected or not all(isinstance(s, str) and s in by_id for s in selected):
            issue(f"actions.{aid}", "steps must name existing steps")
            continue
        if len(set(selected)) != len(selected):
            issue(f"actions.{aid}", "Duplicate steps")
        if not isinstance(action.get("label"), str) or not action["label"]:
            issue(f"actions.{aid}", "Missing label")
        published = action.get("publish_artifacts", [])
        if not isinstance(published, list) or not all(isinstance(a, str) and a in artifacts for a in published):
            issue(f"actions.{aid}", "publish_artifacts must reference existing artifacts")
        produced = set()
        for sid in order:
            if sid not in selected:
                continue
            step = by_id[sid]
            if not set(step.get("approval_artifacts", [])).issubset(step.get("inputs", [])):
                issue(sid, "approval_artifacts must be declared inputs")
            if produced.intersection(step.get("approval_artifacts", [])):
                issue(f"actions.{aid}", "Split action at review: newly generated artifacts need fresh approval")
            produced.update(step.get("outputs", []))
    return {"ok": not errors, "errors": errors, "execution_order": order,
            "command_count": sum(s["kind"] == "command" for s in steps),
            "write_count": sum(bool(s.get("writes")) for s in steps)}
