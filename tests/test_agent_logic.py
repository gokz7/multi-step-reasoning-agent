"""
tests/test_agent_logic.py - Offline tests. No API key, no internet.

They use MockClient (scripted LLM replies) to prove the agent LOOP works:
  - success on the first try
  - an arithmetic slip is caught by Python, the agent retries and succeeds
  - an answer that never verifies ends as "failed" after the retry limit
  - a question with missing information stops early as "failed"
  - the output always follows the required JSON schema
Plus unit tests for the safe calculator and the answer comparison.

Run:  python -m unittest discover -s tests -v
"""

import json                                                       # build scripted replies
import os                                                         # path setup
import sys                                                        # path setup
import unittest                                                   # Python's built-in test framework

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # import from the project folder

from agent import ReasoningAgent                                  # noqa: E402
from calculator import safe_eval                                  # noqa: E402
from llm_client import MockClient                                 # noqa: E402
from utils import parse_json_response, values_match               # noqa: E402

QUESTION = "Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?"

PLAN = json.dumps({"steps": ["Extract red = 3", "Green = 2 x red", "Total = red + green"]})


def executor_reply(total_result, final_value):
    """Executor reply. total_result = number the LLM claims for 3+6."""
    return json.dumps({
        "solvable": True, "missing_info": "",
        "steps": [{"step": 1, "description": "Green apples", "expression": "2*3", "result": 6},
                  {"step": 2, "description": "Total", "expression": "3+6", "result": total_result}],
        "final_answer": f"Alice has {final_value} apples in total.",
        "comparable_value": str(final_value),
        "explanation": "3 red plus 6 green apples."})


RESOLVER_9 = json.dumps({"solvable": True, "comparable_value": "9", "brief_working": "3 + 6 = 9"})
REVIEW_OK = json.dumps({"approved": True, "issues": []})
REVIEW_BAD = json.dumps({"approved": False, "issues": ["Red apples were not added."]})


def check_schema(test, result):
    """Assert the output matches the required schema exactly."""
    test.assertEqual(set(result.keys()), {"answer", "status", "reasoning_visible_to_user", "metadata"})
    test.assertIn(result["status"], ("success", "failed"))
    test.assertIsInstance(result["answer"], str)
    test.assertIsInstance(result["reasoning_visible_to_user"], str)
    test.assertEqual(set(result["metadata"].keys()), {"plan", "checks", "retries"})
    test.assertIsInstance(result["metadata"]["plan"], str)
    test.assertIsInstance(result["metadata"]["retries"], int)
    for check in result["metadata"]["checks"]:
        test.assertEqual(set(check.keys()), {"check_name", "passed", "details"})
        test.assertIsInstance(check["passed"], bool)


class TestAgentLoop(unittest.TestCase):

    def run_agent(self, replies, max_retries=2):
        client = MockClient(replies)                              # fake LLM with scripted replies
        agent = ReasoningAgent(client=client, max_retries=max_retries, write_trace=False)
        return agent.run(QUESTION), client

    def test_success_first_try(self):
        output, client = self.run_agent([PLAN, executor_reply(9, 9), RESOLVER_9, REVIEW_OK])
        result = output["result"]
        check_schema(self, result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metadata"]["retries"], 0)
        self.assertTrue(all(c["passed"] for c in result["metadata"]["checks"]))
        self.assertEqual(client.call_count, 4)                    # plan, execute, resolve, review

    def test_arithmetic_slip_is_caught_then_retry_succeeds(self):
        replies = [PLAN, executor_reply(10, 10),                  # attempt 1: LLM claims 3+6 = 10
                   PLAN, executor_reply(9, 9), RESOLVER_9, REVIEW_OK]  # attempt 2: correct
        output, client = self.run_agent(replies)
        result = output["result"]
        check_schema(self, result)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metadata"]["retries"], 1)
        first_attempt_checks = output["trace"]["attempts"][0]["checks"]
        arithmetic = [c for c in first_attempt_checks if c["check_name"] == "arithmetic_check"][0]
        self.assertFalse(arithmetic["passed"])                    # Python caught the slip
        self.assertEqual(len(first_attempt_checks), 2)            # LLM checks skipped after a code-check failure
        self.assertIn("arithmetic_check", client.prompts_seen[2])  # feedback reached the next planner prompt

    def test_never_verified_ends_failed(self):
        bad_attempt = [PLAN, executor_reply(6, 6), RESOLVER_9, REVIEW_BAD]  # arithmetic fine, answer wrong
        output, _ = self.run_agent(bad_attempt * 3, max_retries=2)
        result = output["result"]
        check_schema(self, result)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metadata"]["retries"], 2)
        self.assertIn("Verification failed after 3 attempts", result["reasoning_visible_to_user"])

    def test_missing_information_stops_early(self):
        executor_unsolvable = json.dumps({"solvable": False, "missing_info": "No ages are given.",
                                          "steps": [], "final_answer": "", "comparable_value": "",
                                          "explanation": ""})
        resolver_unsolvable = json.dumps({"solvable": False, "comparable_value": "", "brief_working": "No ages."})
        output, client = self.run_agent([PLAN, executor_unsolvable, resolver_unsolvable])
        result = output["result"]
        check_schema(self, result)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metadata"]["retries"], 0)       # no pointless retries
        self.assertEqual(client.call_count, 3)

    def test_bad_json_from_llm_is_retried(self):
        replies = ["sorry, I cannot do JSON",                     # attempt 1: planner reply is not JSON
                   PLAN, executor_reply(9, 9), RESOLVER_9, REVIEW_OK]
        output, _ = self.run_agent(replies)
        result = output["result"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metadata"]["retries"], 1)
        self.assertEqual(output["trace"]["attempts"][0]["checks"][0]["check_name"], "pipeline_error")

    def test_chain_of_thought_not_shown_to_user(self):
        output, _ = self.run_agent([PLAN, executor_reply(9, 9), RESOLVER_9, REVIEW_OK])
        visible = output["result"]["answer"] + output["result"]["reasoning_visible_to_user"]
        self.assertNotIn("2*3", visible)                          # raw expressions stay in the trace
        self.assertIn("steps", output["trace"]["attempts"][0]["solution"])


class TestCalculator(unittest.TestCase):

    def test_time_arithmetic(self):
        self.assertEqual(safe_eval("(18*60+5)-(14*60+30)"), 215)
        self.assertEqual(safe_eval("(1*60+40)+1440-(23*60+15)"), 145)

    def test_functions_and_decimals(self):
        self.assertEqual(safe_eval("max(30, 45, 60)"), 60)
        self.assertAlmostEqual(safe_eval("800*0.75*1.10"), 660)

    def test_rejects_unsafe_code(self):
        for bad in ["__import__('os')", "x + 1", "'a' * 3", "[1, 2]", "2 ** 100000", "14:30"]:
            with self.assertRaises(Exception):
                safe_eval(bad)

    def test_divide_by_zero_raises(self):
        with self.assertRaises(ZeroDivisionError):
            safe_eval("5 / 0")


class TestHelpers(unittest.TestCase):

    def test_values_match(self):
        self.assertTrue(values_match("215", "215.0"))
        self.assertTrue(values_match("1,200", 1200))
        self.assertTrue(values_match("13:15-14:00; 09:00-09:45", "09:00 - 09:45;13:15\u201314:00"))  # order, spaces, en dash
        self.assertFalse(values_match("215", "216"))
        self.assertFalse(values_match("11:00-12:00", "09:00-09:30"))

    def test_parse_json_with_code_fence(self):
        self.assertEqual(parse_json_response('```json\n{"a": 1}\n```'), {"a": 1})
        with self.assertRaises(ValueError):
            parse_json_response("no json here")


if __name__ == "__main__":
    unittest.main()
