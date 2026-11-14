from inspect_ai.model import ModelOutput

from collusion_lab.core.schema import Action, Signal
from collusion_lab.monitor.core import TrustedMonitor


class StaticPlugin:
    name = "market"

    def __init__(self, signals):
        self._signals = signals

    def signals(self, level, ctx, events):
        return self._signals


class FakeRoster:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def is_scripted(self, role):
        return role != "monitor_auditor"

    async def generate(self, role, messages, **kwargs):
        self.calls += 1
        assert role == "monitor_auditor"
        assert "Monitor decision" in messages[0].content
        output = ModelOutput.from_content("mockllm/model", self.response)
        output.metadata = {"clab_spec": "mockllm/model"}
        return output


class Context:
    def __init__(self, roster):
        self.roster = roster


def test_monitor_auditor_can_downgrade_and_records_both_actions():
    roster = FakeRoster(
        '{"recommended_action":"ALLOW","confidence":0.91,"rationale":"No violation is supported."}'
    )
    monitor = TrustedMonitor(
        "M3",
        StaticPlugin([Signal("verified_violation", 0.9, verified=True, family="artifact")]),
    )

    decision = monitor.evaluate(Context(roster), [])

    assert decision.base_action == Action.CONSTRAIN.value
    assert decision.action == Action.ALLOW
    assert decision.monitor_audit["applied"] is True
    assert decision.monitor_audit["model"] == "mockllm/model"
    assert decision.to_dict()["monitor_audit"]["final_action"] == "ALLOW"
    assert roster.calls == 1


def test_monitor_auditor_can_escalate():
    roster = FakeRoster(
        '{"recommended_action":"CONSTRAIN","confidence":0.95,"rationale":"Verified violation is present."}'
    )
    monitor = TrustedMonitor("M3", StaticPlugin([]))

    decision = monitor.evaluate(Context(roster), [])

    assert decision.base_action == Action.ALLOW.value
    assert decision.action == Action.CONSTRAIN
    assert decision.monitor_audit["applied"] is True


def test_low_confidence_audit_does_not_change_action():
    roster = FakeRoster(
        '{"recommended_action":"ALLOW","confidence":0.74,"rationale":"Evidence is uncertain."}'
    )
    monitor = TrustedMonitor(
        "M3",
        StaticPlugin([Signal("verified_violation", 0.9, verified=True, family="artifact")]),
    )

    decision = monitor.evaluate(Context(roster), [])

    assert decision.action == Action.CONSTRAIN
    assert decision.base_action == Action.CONSTRAIN.value
    assert decision.monitor_audit["status"] == "low_confidence"
    assert decision.monitor_audit["applied"] is False


def test_unavailable_auditor_preserves_action_and_records_failure(capsys):
    from collusion_lab.core.models import AllModelsFailed

    class UnavailableRoster(FakeRoster):
        async def generate(self, role, messages, **kwargs):
            raise AllModelsFailed("all auditor models unavailable")

    roster = UnavailableRoster("")
    monitor = TrustedMonitor(
        "M3",
        StaticPlugin([Signal("verified_violation", 0.9, verified=True, family="artifact")]),
    )

    decision = monitor.evaluate(Context(roster), [])

    assert decision.action == Action.CONSTRAIN
    assert decision.monitor_audit["status"] == "unavailable"
    assert decision.monitor_audit["applied"] is False
    assert "monitor auditor unavailable" in capsys.readouterr().out


def test_invalid_audit_response_preserves_original_action(capsys):
    roster = FakeRoster('{"recommended_action":"IGNORE","confidence":1,"rationale":"Bad action."}')
    monitor = TrustedMonitor(
        "M3",
        StaticPlugin([Signal("verified_violation", 0.9, verified=True, family="artifact")]),
    )

    decision = monitor.evaluate(Context(roster), [])

    assert decision.action == Action.CONSTRAIN
    assert decision.monitor_audit["status"] == "invalid_response"
    assert "invalid JSON or an invalid action" in capsys.readouterr().out


def test_unconfigured_auditor_leaves_monitor_decision_unchanged():
    class NoAuditor:
        def is_scripted(self, role):
            return True

    monitor = TrustedMonitor(
        "M3",
        StaticPlugin([Signal("verified_violation", 0.9, verified=True, family="artifact")]),
    )

    decision = monitor.evaluate(Context(NoAuditor()), [])

    assert decision.action == Action.CONSTRAIN
    assert decision.base_action is None
    assert decision.monitor_audit is None
