import json
import tempfile
import unittest
from pathlib import Path

from app.context_engineering.runtime import (
    BudgetExceeded,
    end_run,
    record_evidence,
    reserve_expert_call,
    start_run,
)
from app.evals.trajectory import evaluate_trajectory
from app.tools.evidence_tools import verify_claim_support


class ContextEngineeringTests(unittest.TestCase):
    def test_call_budget_is_a_programmatic_guardrail(self):
        with tempfile.TemporaryDirectory() as directory:
            token = start_run(directory)
            try:
                # Directly lower the test run limit without altering machine-wide environment.
                from app.context_engineering.runtime import current_state

                current_state().max_expert_calls = 1
                reserve_expert_call("market_intelligence", "test")
                with self.assertRaises(BudgetExceeded):
                    reserve_expert_call("knowledge_base", "test")
            finally:
                summary = end_run(token)
            self.assertEqual(summary["expert_calls"], 1)

    def test_claim_validator_requires_registered_evidence_and_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            token = start_run(directory)
            try:
                evidence_id = record_evidence("经营数据", {"summary": "GMV 下降 12%"})
                result = json.loads(
                    verify_claim_support.invoke(
                        {
                            "claims_json": json.dumps(
                                [{"claim": "GMV 下降 12%", "evidence_ids": [evidence_id], "evidence_quote": "GMV 下降 12%"}],
                                ensure_ascii=False,
                            )
                        }
                    )
                )
                self.assertEqual(result["review"][0]["support_level"], "direct")
                missing = json.loads(
                    verify_claim_support.invoke(
                        {"claims_json": '[{"claim":"增长","evidence_ids":["ev_missing"]}]'}
                    )
                )
                self.assertEqual(missing["review"][0]["support_level"], "insufficient")
            finally:
                end_run(token)

    def test_trajectory_eval_checks_expected_experts(self):
        result = evaluate_trajectory(
            [
                {"event": "expert_started", "expert": "market_intelligence"},
                {"event": "expert_started", "expert": "commerce_analytics"},
            ],
            {"required_experts": ["market_intelligence", "knowledge_base"]},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["missing_experts"], ["knowledge_base"])


if __name__ == "__main__":
    unittest.main()
