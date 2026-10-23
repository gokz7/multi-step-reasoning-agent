"""
verifier.py - Phase 3: VERIFIER.

Re-checks the executor's solution with four checks, cheapest first:
  1. format_check          (code) - all required fields are present and non-empty
  2. arithmetic_check      (code) - Python re-computes every expression and compares with the LLM's result
  3. independent_resolve   (LLM)  - a fresh LLM call solves the question WITHOUT seeing the solution; answers must match
  4. llm_review            (LLM)  - an LLM reviews the solution for logic, units and constraint mistakes

If a code check fails, the LLM checks are skipped (the attempt is already wrong,
so we save API calls and retry sooner).

Each check returns {"check_name": str, "passed": bool, "details": str}, the format the output schema needs.
"""

import json                                                       # to send the solution to the reviewer as text
import math                                                       # isclose() for numbers

import config                                                     # NUMBER_TOLERANCE
from prompts import RESOLVER_PROMPT, VERIFIER_PROMPT, fill_prompt  # verifier prompt templates
from utils import format_plan, parse_json_response, to_number, values_match  # helpers


def make_check(name, passed, details):
    """Build one check result in the required shape."""
    return {"check_name": name, "passed": bool(passed), "details": details}


def check_format(solution):
    """Code check: the executor returned every field we need."""
    problems = []                                                 # collect every missing piece
    for field in ("final_answer", "comparable_value", "explanation"):
        if not str(solution.get(field) or "").strip():            # missing or empty
            problems.append(f"'{field}' is empty")
    if not solution.get("steps"):                                 # no working at all
        problems.append("'steps' is empty")
    if problems:
        return make_check("format_check", False, "; ".join(problems))
    return make_check("format_check", True, "All required fields are present.")


def check_arithmetic(solution):
    """Code check: every expression, computed by Python, equals the result the LLM claimed."""
    problems = []                                                 # one message per bad step
    checked = 0                                                   # how many expressions we verified
    for step in solution.get("steps", []):
        if not isinstance(step, dict):                            # malformed step
            problems.append("A step is not a JSON object")
            continue
        expression = str(step.get("expression") or "").strip()
        if not expression:                                        # no arithmetic in this step
            continue
        number = step.get("step", "?")                            # step number for messages
        if step.get("python_error"):                              # Python could not compute it
            problems.append(f"Step {number}: expression '{expression}' could not be computed ({step['python_error']})")
            continue
        claimed = to_number(step.get("result"))                   # what the LLM said
        actual = step.get("python_result")                        # what Python computed
        if claimed is None:
            problems.append(f"Step {number}: result '{step.get('result')}' is not a number")
            continue
        checked += 1
        if not math.isclose(claimed, actual, rel_tol=config.NUMBER_TOLERANCE, abs_tol=config.NUMBER_TOLERANCE):
            problems.append(f"Step {number}: '{expression}' = {actual}, but the LLM wrote {claimed}")
    if problems:
        return make_check("arithmetic_check", False, "; ".join(problems))
    if checked == 0:
        return make_check("arithmetic_check", True, "No arithmetic expressions to check.")
    return make_check("arithmetic_check", True, f"All {checked} expressions match Python's results.")


def resolve_independently(client, question):
    """Ask the LLM to solve the question from scratch. Returns the resolver's dict."""
    prompt = fill_prompt(RESOLVER_PROMPT, QUESTION=question)      # the solution is NOT included
    return parse_json_response(client.ask(prompt))                # {"solvable", "comparable_value", "brief_working"}


def check_independent_resolve(client, question, solution):
    """LLM check: a second, independent solve must give the same comparable value."""
    try:
        second = resolve_independently(client, question)
    except Exception as error:                                    # API or JSON problem counts as a failed check
        return make_check("independent_resolve", False, f"Independent solve failed: {error}")
    if second.get("solvable") is False:                           # checker thinks info is missing
        return make_check("independent_resolve", False,
                          f"Independent solver says the question cannot be answered: {second.get('brief_working', '')}")
    first_value = solution.get("comparable_value", "")
    second_value = second.get("comparable_value", "")
    if values_match(first_value, second_value):
        return make_check("independent_resolve", True,
                          f"Independent solve agrees: '{second_value}'.")
    return make_check("independent_resolve", False,
                      f"Mismatch: executor got '{first_value}', independent solve got '{second_value}' "
                      f"({second.get('brief_working', '')})")


def check_llm_review(client, question, plan_steps, solution):
    """LLM check: a reviewer looks for logic, unit and constraint mistakes."""
    shown = {key: value for key, value in solution.items() if key != "missing_info"}  # keep the reviewer's input short
    prompt = fill_prompt(VERIFIER_PROMPT,
                         QUESTION=question,
                         PLAN=format_plan(plan_steps),
                         SOLUTION=json.dumps(shown, ensure_ascii=False))
    try:
        review = parse_json_response(client.ask(prompt))         # {"approved": bool, "issues": [...]}
    except Exception as error:
        return make_check("llm_review", False, f"Review failed: {error}")
    approved = review.get("approved") is True                     # only a real true counts as approval
    issues = review.get("issues") or []
    if approved:
        return make_check("llm_review", True, "Reviewer approved the solution.")
    return make_check("llm_review", False,
                      "Reviewer found issues: " + ("; ".join(str(issue) for issue in issues) or "no reason given"))


def verify(client, question, plan_steps, solution):
    """Run all checks, cheapest first. Returns (all_passed, list_of_checks)."""
    checks = [check_format(solution), check_arithmetic(solution)]  # free code checks first
    if not all(check["passed"] for check in checks):              # already wrong: skip the LLM checks
        return False, checks
    checks.append(check_independent_resolve(client, question, solution))
    checks.append(check_llm_review(client, question, plan_steps, solution))
    return all(check["passed"] for check in checks), checks


def confirm_unsolvable(client, question, executor_reason):
    """The executor said information is missing. Ask the independent solver if it agrees."""
    try:
        second = resolve_independently(client, question)
    except Exception as error:
        return make_check("unsolvable_confirmation", False, f"Could not confirm: {error}")
    if second.get("solvable") is False:                           # both agree it can't be answered
        return make_check("unsolvable_confirmation", True,
                          f"Executor and independent solver both say information is missing. Executor: {executor_reason}")
    return make_check("unsolvable_confirmation", False,
                      f"Executor said the question cannot be answered, but the independent solver answered "
                      f"'{second.get('comparable_value', '')}'. Try solving it.")
