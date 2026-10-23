"""
agent.py - The agent loop and the user interfaces.

The loop (for each attempt, up to 1 + MAX_RETRIES attempts):
  1. PLANNER  makes a plan                      (planner.py)
  2. EXECUTOR follows the plan, Python checks math (executor.py)
  3. VERIFIER runs its checks                    (verifier.py)
     - all checks pass  -> return status "success"
     - a check fails    -> turn the failed checks into feedback and retry
  Special case: if the executor says information is missing and the independent
  solver agrees, we stop at once with status "failed" (retrying cannot add missing facts).
  After the last failed attempt -> return status "failed" with the reason.

The user only needs "answer" and "reasoning_visible_to_user".
The full working of every attempt (plans, steps, checks) goes to logs/agent_trace.jsonl, never to the user.

Interfaces:
  - solve(question) -> dict       (notebook / import use)
  - python agent.py               (CLI: type questions, get JSON back)
"""

import json                                                       # print and log JSON
import os                                                         # create the logs folder
import sys                                                        # exit codes for the CLI
from datetime import datetime, timezone                           # timestamps in the trace log

import config                                                     # MAX_RETRIES, log paths
from executor import execute_plan                                 # phase 2
from llm_client import get_client                                 # LLM provider factory
from planner import make_plan                                     # phase 1
from verifier import confirm_unsolvable, make_check, verify       # phase 3


class ReasoningAgent:
    """Planner -> Executor -> Verifier, with limited retries."""

    def __init__(self, client=None, max_retries=None, write_trace=True):
        self.client = client or get_client()                      # real LLM unless a mock is passed in
        self.max_retries = config.MAX_RETRIES if max_retries is None else max_retries
        self.write_trace = write_trace                            # tests with the mock turn this off

    def run(self, question):
        """Solve a question. Returns {"result": <user JSON>, "trace": <internal details>}."""
        question = str(question).strip()
        attempts = []                                             # internal record of every attempt
        feedback = ""                                             # failure details passed to the next attempt
        last_plan = []                                            # plan of the most recent attempt
        last_checks = []                                          # checks of the most recent attempt

        for attempt_number in range(self.max_retries + 1):        # first try + retries
            attempt = {"attempt": attempt_number + 1, "feedback_used": feedback}

            try:
                plan = make_plan(self.client, question, feedback)                 # phase 1
                attempt["plan"] = plan
                solution = execute_plan(self.client, question, plan, feedback)    # phase 2
                attempt["solution"] = solution
            except Exception as error:                            # API down, bad JSON, empty plan...
                checks = [make_check("pipeline_error", False, f"{type(error).__name__}: {error}")]
                attempt["checks"] = checks
                attempts.append(attempt)
                last_checks = checks
                feedback = self._build_feedback(checks)
                continue                                          # try again

            last_plan = plan

            if solution.get("solvable") is False:                 # executor says facts are missing
                reason = str(solution.get("missing_info") or "Information is missing.")
                check = confirm_unsolvable(self.client, question, reason)  # second opinion
                attempt["checks"] = [check]
                attempts.append(attempt)
                last_checks = [check]
                if check["passed"]:                               # both agree: stop now, no retry
                    result = self._result(
                        answer="I can't answer this: the question is missing information.",
                        status="failed",
                        reasoning=reason,
                        plan=plan, checks=[check], retries=attempt_number)
                    return self._finish(question, result, attempts)
                feedback = self._build_feedback([check])          # they disagree: retry and try to solve
                continue

            passed, checks = verify(self.client, question, plan, solution)  # phase 3
            attempt["checks"] = checks
            attempts.append(attempt)
            last_checks = checks

            if passed:                                            # verified answer
                result = self._result(
                    answer=str(solution.get("final_answer", "")).strip(),
                    status="success",
                    reasoning=str(solution.get("explanation", "")).strip(),
                    plan=plan, checks=checks, retries=attempt_number)
                return self._finish(question, result, attempts, comparable=solution.get("comparable_value"))

            feedback = self._build_feedback(checks)               # tell the next attempt what went wrong

        failed_details = "; ".join(c["details"] for c in last_checks if not c["passed"])  # why it failed
        result = self._result(
            answer="I couldn't find an answer I could verify.",
            status="failed",
            reasoning=f"Verification failed after {len(attempts)} attempts. Last problem: {failed_details}",
            plan=last_plan, checks=last_checks, retries=len(attempts) - 1)
        return self._finish(question, result, attempts)

    @staticmethod
    def _build_feedback(checks):
        """Turn failed checks into a short message for the next planner/executor call."""
        failed = [f"- {c['check_name']}: {c['details']}" for c in checks if not c["passed"]]
        return "The previous attempt failed these checks:\n" + "\n".join(failed) + "\nFix these problems."

    @staticmethod
    def _result(answer, status, reasoning, plan, checks, retries):
        """Build the output JSON in exactly the required schema."""
        return {
            "answer": answer,                                     # user-facing
            "status": status,                                     # "success" or "failed"
            "reasoning_visible_to_user": reasoning,               # short explanation only
            "metadata": {                                         # for debugging/evaluation
                "plan": " | ".join(f"{i}. {step}" for i, step in enumerate(plan, start=1)),  # abbreviated plan
                "checks": checks,                                 # checks of the final attempt
                "retries": retries,                               # 0 = solved on the first try
            },
        }

    def _finish(self, question, result, attempts, comparable=None):
        """Write the full internal trace to the log and return result + trace."""
        trace = {
            "timestamp": datetime.now(timezone.utc).isoformat(),  # when it ran
            "question": question,
            "comparable_value": comparable,                       # machine-comparable answer (used by tests)
            "llm_calls": self.client.call_count,                  # total LLM calls so far by this client
            "attempts": attempts,                                 # full working of every attempt
            "result": result,                                     # what the user got
        }
        if self.write_trace:
            os.makedirs(config.LOG_DIR, exist_ok=True)            # make logs/ if needed
            with open(config.TRACE_LOG_FILE, "a", encoding="utf-8") as file:
                file.write(json.dumps(trace, ensure_ascii=False, default=str) + "\n")  # one run per line
        return {"result": result, "trace": trace}


_default_agent = None                                             # created on first solve() call


def solve(question):
    """Notebook interface: solve(question: str) -> dict in the required schema."""
    global _default_agent
    if _default_agent is None:
        _default_agent = ReasoningAgent()                         # uses the provider from config/.env
    return _default_agent.run(question)["result"]                 # only the user JSON, no trace


def main():
    """CLI: type a question, get the JSON answer. Type 'exit' to quit."""
    print(f"Reasoning agent ({config.PROVIDER}: {config.MODEL_NAME}). Type a question, or 'exit' to quit.")
    try:
        agent = ReasoningAgent()
    except Exception as error:                                    # e.g. missing API key or package
        print(f"Could not start the LLM client: {error}")
        sys.exit(1)
    while True:
        try:
            question = input("\nQuestion> ").strip()
        except (EOFError, KeyboardInterrupt):                     # Ctrl+D / Ctrl+C
            print()
            break
        if question.lower() in ("exit", "quit"):
            break
        if not question:                                          # ignore empty lines
            continue
        output = agent.run(question)["result"]
        print(json.dumps(output, indent=2, ensure_ascii=False))   # the required JSON


if __name__ == "__main__":
    main()
