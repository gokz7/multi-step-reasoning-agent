"""
executor.py - Phase 2: EXECUTOR.

Follows the plan to produce an intermediate solution:
  1. The LLM writes every calculation step as an arithmetic expression plus the result it expects.
  2. Python then computes each expression itself (safe calculator) and stores it as "python_result".
The verifier later compares the LLM's "result" with "python_result" to catch arithmetic slips.
"""

from calculator import safe_eval                                  # safe arithmetic with Python
from prompts import EXECUTOR_PROMPT, fill_prompt                  # executor prompt template
from utils import format_plan, parse_json_response                # helpers


def execute_plan(client, question, plan_steps, feedback=""):
    """Return the solution dict: solvable, steps, final_answer, comparable_value, explanation."""
    prompt = fill_prompt(EXECUTOR_PROMPT,                         # build the prompt
                         QUESTION=question,
                         PLAN=format_plan(plan_steps),
                         FEEDBACK=feedback or "None (first attempt)")
    reply = client.ask(prompt)                                    # call the LLM
    solution = parse_json_response(reply)                         # the LLM's solution as a dict

    steps = solution.get("steps")                                 # list of step dicts
    if not isinstance(steps, list):                               # keep the structure predictable
        steps = []
    solution["steps"] = steps

    for step in steps:                                            # compute every expression with Python
        if not isinstance(step, dict):                            # skip malformed steps (format check reports them)
            continue
        expression = str(step.get("expression") or "").strip()    # "" means no arithmetic in this step
        if not expression:
            step["python_result"] = None                          # nothing to compute
            continue
        try:
            step["python_result"] = safe_eval(expression)         # Python's answer
        except Exception as error:                                # bad syntax, words in expression, divide by zero...
            step["python_result"] = None
            step["python_error"] = f"{type(error).__name__}: {error}"  # verifier will report this

    return solution
