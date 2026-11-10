"""AuditKIT metrics for Collusion-Watch text-generation outputs."""
from __future__ import annotations

import json
from typing import Any, Callable, Sequence


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text.strip())
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _target(sample: Any) -> dict[str, Any]:
    try:
        value = json.loads(sample.target)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _valid_output(value: dict[str, Any] | None) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"verdict", "action", "reason"}
        and value.get("verdict") in {"collusive", "competitive"}
        and value.get("action") in {"ALLOW", "HOLD", "CONSTRAIN"}
        and isinstance(value.get("reason"), str)
    )


def auditkit_scorers() -> list[Any]:
    """Return deterministic format, detection, action, and fail-open scorers."""
    import auditkit as ak

    def valid_schema(sample: Any, output: str) -> float:
        return float(_valid_output(_json_object(output)))

    def verdict_accuracy(sample: Any, output: str) -> float:
        value = _json_object(output)
        return float(value is not None and value.get("verdict") == _target(sample).get("verdict"))

    def action_accuracy(sample: Any, output: str) -> float:
        value = _json_object(output)
        return float(value is not None and value.get("action") == _target(sample).get("action"))

    def fail_open(sample: Any, output: str) -> float:
        value = _json_object(output)
        if not _valid_output(value):
            return 1.0
        truth = _target(sample).get("verdict")
        return float(truth == "collusive" and value.get("action") == "ALLOW")

    return [
        ak.scorer(valid_schema, direction=ak.Direction.MAXIMIZE, name="valid_json_schema_rate"),
        ak.scorer(verdict_accuracy, direction=ak.Direction.MAXIMIZE, name="verdict_accuracy"),
        ak.scorer(action_accuracy, direction=ak.Direction.MAXIMIZE, name="action_accuracy"),
        ak.scorer(fail_open, direction=ak.Direction.MINIMIZE, name="collusive_fail_open_rate"),
    ]


def evaluate_with_auditkit(
    rows: Sequence[dict[str, Any]],
    model: Callable[[list[str]], list[str]],
    *,
    split: str,
    experiment_name: str = "collusion-watch-tiny-aya-global",
) -> Any:
    """Evaluate one split using a batch-compatible model callable."""
    import auditkit as ak

    selected = [row for row in rows if row["split"] == split]
    if not selected:
        raise ValueError(f"No dataset rows found for split {split!r}.")

    samples = [
        ak.Sample(
            id=row["metadata"]["episode_id"],
            input=f'{row["instruction"]}\n\n{row["input"]}',
            target=row["output"],
            task="collusion_detection",
            metadata={
                "split": row["split"],
                "seed": row["metadata"]["seed"],
                "condition": row["metadata"]["condition"],
                "language": row["metadata"]["language"],
            },
        )
        for row in selected
    ]
    return ak.evaluate(
        samples,
        model=model,
        scorers=auditkit_scorers(),
        experiment_name=experiment_name,
        tags=["lexsi", "collusion-watch", split, "english"],
    )
