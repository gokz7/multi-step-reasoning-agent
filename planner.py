"""
planner.py - Phase 1: PLANNER.

Reads the question and asks the LLM for a short numbered plan (no solving).
If a previous attempt failed verification, the failure details are passed in
as feedback so the new plan can avoid the same mistake.
"""

from prompts import PLANNER_PROMPT, fill_prompt                   # planner prompt template
from utils import parse_json_response                             # read the LLM's JSON reply


def make_plan(client, question, feedback=""):
    """Return the plan as a list of step strings."""
    prompt = fill_prompt(PLANNER_PROMPT,                          # build the prompt
                         QUESTION=question,
                         FEEDBACK=feedback or "None (first attempt)")
    reply = client.ask(prompt)                                    # call the LLM
    data = parse_json_response(reply)                             # {"steps": [...]}
    steps = data.get("steps")                                     # the list of steps
    if not isinstance(steps, list) or len(steps) == 0:            # planner must return at least one step
        raise ValueError("Planner returned no steps")
    return [str(step).strip() for step in steps if str(step).strip()]  # clean text, drop empty steps
