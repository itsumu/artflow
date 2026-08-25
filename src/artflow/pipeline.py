"""Validation for version-controlled Artflow pipeline definitions."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any


SCHEMA_VERSION = 1
STEP_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
RETRY_POLICIES = {"safe", "manual"}


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _matches_allowed(command: list[str], allowed_commands: list[Any]) -> bool:
    return any(
        isinstance(allowed, list)
        and len(command) == len(allowed)
        and all(expected == actual or expected == "{asset_id}" for expected, actual in zip(allowed, command, strict=True))
        for allowed in allowed_commands
    )


def _capability_mode(command: list[str], capabilities: dict[str, Any]) -> str | None:
    for capability in capabilities.get("commands", []):
        pattern = capability.get("argv") if isinstance(capability, dict) else None
        if not isinstance(pattern, list) or len(pattern) != len(command):
            continue
        matches = True
        for expected, actual in zip(pattern, command, strict=True):
            if not isinstance(expected, str):
                matches = False
                break
            if expected.startswith("<") and expected.endswith(">"):
                continue
            if "|" in expected and actual in expected.split("|"):
                continue
            if expected != actual:
                matches = False
                break
        if matches:
            mode = capability.get("mode")
            return mode if mode in {"read", "write"} else None
    return None


def _transitive_dependencies(step_id: str, dependencies: dict[str, list[str]]) -> set[str]:
    result: set[str] = set()
    pending = list(dependencies.get(step_id, []))
    while pending:
        dependency = pending.pop()
        if dependency in result:
            continue
        result.add(dependency)
        pending.extend(dependencies.get(dependency, []))
    return result


def validate_pipeline_definition(
    pipeline_id: str,
    pipeline: dict[str, Any],
    *,
    asset_id: str,
    artifact_ids: set[str],
    allowed_commands: list[Any],
    capabilities: dict[str, Any] | None,
    capabilities_error: str | None = None,
) -> dict[str, Any]:
    """Validate a pipeline without starting Aseprite, Godot, or an export."""

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    steps = pipeline.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append(_issue("pipeline.steps", f"pipelines.{pipeline_id}.steps", "管线必须至少声明一个步骤。"))
        steps = []

    if capabilities_error:
        errors.append(_issue("executor.capabilities", "executors.artctl", capabilities_error))
    elif not isinstance(capabilities, dict) or capabilities.get("machine_interface") != "artctl-json-v1":
        errors.append(_issue("executor.capabilities", "executors.artctl", "artctl capabilities 未返回受支持的机器接口。"))

    by_id: dict[str, dict[str, Any]] = {}
    positions: dict[str, int] = {}
    dependencies: dict[str, list[str]] = {}
    outputs: dict[str, set[str]] = {}
    write_paths: dict[str, str] = {}
    command_steps: list[tuple[str, dict[str, Any], str]] = []

    for index, raw_step in enumerate(steps):
        path = f"pipelines.{pipeline_id}.steps[{index}]"
        if not isinstance(raw_step, dict):
            errors.append(_issue("step.shape", path, "步骤必须是对象。"))
            continue
        step_id = raw_step.get("id")
        if not isinstance(step_id, str) or not STEP_ID.fullmatch(step_id):
            errors.append(_issue("step.id", f"{path}.id", "步骤 id 必须是小写 snake_case。"))
            continue
        if step_id in by_id:
            errors.append(_issue("step.id.duplicate", f"{path}.id", f"步骤 id `{step_id}` 重复。"))
            continue
        by_id[step_id] = raw_step
        positions[step_id] = index
        kind = raw_step.get("kind")
        if kind not in {"read", "command"}:
            errors.append(_issue("step.kind", f"{path}.kind", "步骤 kind 必须是 `read` 或 `command`。"))
        if not isinstance(raw_step.get("label"), str) or not raw_step["label"].strip():
            errors.append(_issue("step.label", f"{path}.label", "步骤必须声明可读标签。"))
        raw_dependencies = raw_step.get("depends_on", [])
        if not isinstance(raw_dependencies, list) or not all(isinstance(value, str) for value in raw_dependencies):
            errors.append(_issue("step.dependencies", f"{path}.depends_on", "depends_on 必须是步骤 id 列表。"))
            raw_dependencies = []
        dependencies[step_id] = list(raw_dependencies)
        raw_outputs = raw_step.get("outputs")
        if not isinstance(raw_outputs, list) or not raw_outputs or not all(isinstance(value, str) and value for value in raw_outputs):
            errors.append(_issue("step.outputs", f"{path}.outputs", "步骤必须声明非空输出 id 列表。"))
            raw_outputs = []
        if len(set(raw_outputs)) != len(raw_outputs):
            errors.append(_issue("step.outputs.duplicate", f"{path}.outputs", "同一步骤内的输出 id 不能重复。"))
        outputs[step_id] = set(raw_outputs)

    for step_id, step in by_id.items():
        path = f"pipelines.{pipeline_id}.steps[{positions[step_id]}]"
        for dependency in dependencies[step_id]:
            if dependency not in by_id:
                errors.append(_issue("dependency.missing", f"{path}.depends_on", f"步骤 `{step_id}` 依赖不存在的步骤 `{dependency}`。"))
            elif dependency == step_id:
                errors.append(_issue("dependency.self", f"{path}.depends_on", "步骤不能依赖自身。"))

        raw_inputs = step.get("inputs")
        if not isinstance(raw_inputs, list) or not raw_inputs or not all(isinstance(value, str) for value in raw_inputs):
            errors.append(_issue("step.inputs", f"{path}.inputs", "步骤必须声明非空输入选择器列表。"))
            raw_inputs = []
        for selector in raw_inputs:
            if selector.startswith("artifact."):
                artifact_id = selector.removeprefix("artifact.")
                if artifact_id not in artifact_ids:
                    errors.append(_issue("input.artifact", f"{path}.inputs", f"输入 `{selector}` 没有对应的资产证据。"))
                continue
            if selector.startswith("step."):
                parts = selector.split(".")
                if len(parts) != 3 or not parts[1] or not parts[2]:
                    errors.append(_issue("input.step", f"{path}.inputs", f"输入 `{selector}` 不是合法的步骤输出选择器。"))
                    continue
                producer, output_id = parts[1:]
                if producer not in by_id or output_id not in outputs.get(producer, set()):
                    errors.append(_issue("input.producer", f"{path}.inputs", f"输入 `{selector}` 没有对应的上游输出。"))
                elif producer not in _transitive_dependencies(step_id, dependencies):
                    errors.append(_issue("input.dependency", f"{path}.inputs", f"输入 `{selector}` 的生产步骤未被声明为依赖。"))
                continue
            errors.append(_issue("input.selector", f"{path}.inputs", f"输入 `{selector}` 必须以 `artifact.` 或 `step.` 开头。"))

        if step.get("kind") != "command":
            if any(key in step for key in ("command", "executor", "write_paths", "locks", "timeout_seconds", "retry_policy")):
                errors.append(_issue("read.command_fields", path, "只读步骤不能声明执行器或写入字段。"))
            continue

        executor = step.get("executor")
        if executor != "artctl":
            errors.append(_issue("command.executor", f"{path}.executor", "一期命令步骤必须明确使用 `artctl` 执行器。"))
        raw_command = step.get("command")
        if not isinstance(raw_command, list) or not raw_command or not all(isinstance(value, str) and value for value in raw_command):
            errors.append(_issue("command.argv", f"{path}.command", "命令步骤必须声明非空 command 列表。"))
            continue
        command = [value.replace("{asset_id}", asset_id) for value in raw_command]
        if not _matches_allowed(command, allowed_commands):
            errors.append(_issue("command.allowlist", f"{path}.command", f"命令 `{' '.join(command)}` 不在项目适配器白名单内。"))
        mode = _capability_mode(command, capabilities or {})
        if mode is None:
            errors.append(_issue("command.capability", f"{path}.command", f"artctl capabilities 未声明命令 `{' '.join(command)}`。"))
            mode = "unknown"
        command_steps.append((step_id, step, mode))
        timeout = step.get("timeout_seconds")
        if not isinstance(timeout, int) or timeout < 1:
            errors.append(_issue("command.timeout", f"{path}.timeout_seconds", "命令步骤必须声明正整数 timeout_seconds。"))
        retry_policy = step.get("retry_policy")
        if retry_policy not in RETRY_POLICIES:
            errors.append(_issue("command.retry", f"{path}.retry_policy", "retry_policy 必须为 `safe` 或 `manual`。"))
        raw_write_paths = step.get("write_paths", [])
        if not isinstance(raw_write_paths, list) or not all(isinstance(value, str) for value in raw_write_paths):
            errors.append(_issue("command.write_paths", f"{path}.write_paths", "write_paths 必须是路径选择器列表。"))
            raw_write_paths = []
        for selector in raw_write_paths:
            if selector == "asset.runtime_path":
                pass
            elif selector.startswith("artifact.") and selector.removeprefix("artifact.") in artifact_ids:
                pass
            else:
                errors.append(_issue("command.path_selector", f"{path}.write_paths", f"不支持的写入路径选择器 `{selector}`。"))
            previous = write_paths.get(selector)
            if previous:
                errors.append(_issue("command.path_conflict", f"{path}.write_paths", f"写入路径 `{selector}` 已由步骤 `{previous}` 声明。"))
            else:
                write_paths[selector] = step_id
        raw_locks = step.get("locks", [])
        if not isinstance(raw_locks, list) or not all(isinstance(value, str) and value for value in raw_locks):
            errors.append(_issue("command.locks", f"{path}.locks", "locks 必须是资源锁列表。"))
            raw_locks = []
        is_write = mode == "write"
        if is_write and not step.get("requires_approval", False):
            errors.append(_issue("approval.write", f"{path}.requires_approval", "写入命令必须声明 requires_approval=true。"))
        if is_write and not raw_write_paths:
            errors.append(_issue("command.write_paths.required", f"{path}.write_paths", "写入命令必须声明写入路径。"))
        if is_write and not raw_locks:
            errors.append(_issue("command.locks.required", f"{path}.locks", "写入命令必须声明资源锁。"))
        if mode == "read" and raw_write_paths:
            errors.append(_issue("command.read_writes", f"{path}.write_paths", "只读命令不能声明写入路径。"))
        if mode == "read" and step.get("requires_approval", False):
            warnings.append(_issue("approval.read", f"{path}.requires_approval", "只读命令不需要人工确认。"))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            errors.append(_issue("dag.cycle", f"pipelines.{pipeline_id}", f"检测到包含 `{step_id}` 的循环依赖。"))
            return
        visiting.add(step_id)
        for dependency in dependencies.get(step_id, []):
            if dependency in by_id:
                visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in by_id:
        visit(step_id)

    indegree = {step_id: 0 for step_id in by_id}
    children: dict[str, list[str]] = defaultdict(list)
    for step_id, values in dependencies.items():
        for dependency in values:
            if dependency in by_id:
                indegree[step_id] += 1
                children[dependency].append(step_id)
    ready = deque(step_id for step_id in by_id if indegree[step_id] == 0)
    execution_order: list[str] = []
    while ready:
        step_id = ready.popleft()
        execution_order.append(step_id)
        for child in children[step_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    command_count = len(command_steps)
    write_count = sum(1 for _step_id, _step, mode in command_steps if mode == "write")
    return {
        "schema_version": SCHEMA_VERSION,
        "asset_id": asset_id,
        "pipeline_id": pipeline_id,
        "status": "passed" if not errors else "failed",
        "ok": not errors,
        "checks": [
            {"id": "dag", "label": "依赖、输入和输出", "ok": not any(error["code"].startswith(("dag", "dependency", "input", "step")) for error in errors)},
            {"id": "commands", "label": "白名单与 capabilities", "ok": not any(error["code"].startswith(("command", "executor")) for error in errors)},
            {"id": "approval", "label": "审批门与资源锁", "ok": not any(error["code"].startswith("approval") for error in errors)},
        ],
        "command_count": command_count,
        "write_count": write_count,
        "execution_order": execution_order if len(execution_order) == len(by_id) else [],
        "errors": errors,
        "warnings": warnings,
    }
