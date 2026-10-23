"""
utils.py - Small helper functions shared by the planner, executor, verifier and tests.

  parse_json_response() - pull a JSON object out of an LLM reply (handles ```json fences)
  values_match()        - compare two "comparable_value" strings (numbers with tolerance, text after cleanup)
  format_plan()         - turn a list of steps into "1. ...\n2. ..." text
"""

import json                                                       # read JSON text
import math                                                       # isclose() for number comparison

import config                                                     # NUMBER_TOLERANCE


def parse_json_response(text):
    """Return the JSON object inside an LLM reply. Raises ValueError if there is none."""
    if not isinstance(text, str):                                 # guard against None
        raise ValueError("LLM reply is not text")
    cleaned = text.strip()                                        # remove spaces/newlines at the ends
    if cleaned.startswith("```"):                                 # reply wrapped in a markdown code block
        cleaned = cleaned.strip("`")                              # drop the backticks
        if cleaned.lower().startswith("json"):                    # drop the "json" language tag
            cleaned = cleaned[4:]
    start = cleaned.find("{")                                     # first opening brace
    end = cleaned.rfind("}")                                      # last closing brace
    if start == -1 or end == -1 or end < start:                   # no JSON object found
        raise ValueError(f"No JSON object in LLM reply: {text[:200]}")
    try:
        data = json.loads(cleaned[start:end + 1])                 # parse only the {...} part
    except json.JSONDecodeError as error:
        raise ValueError(f"LLM reply is not valid JSON: {error}") from error
    if not isinstance(data, dict):                                # we always expect an object
        raise ValueError("LLM reply JSON is not an object")
    return data


def to_number(value):
    """Turn a value into a float if possible, else return None. '1,200' -> 1200.0"""
    if isinstance(value, bool):                                   # True/False are not numbers here
        return None
    if isinstance(value, (int, float)):                           # already a number
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")                     # remove thousands separators
        try:
            return float(text)
        except ValueError:
            return None                                           # not a number
    return None


def normalize_text(value):
    """Clean a text answer so small formatting differences don't matter."""
    text = str(value).strip().lower()                             # same case, no outer spaces
    text = text.replace("\u2013", "-").replace("\u2014", "-")     # en dash / em dash -> hyphen
    text = text.replace(" ", "")                                  # ignore spaces
    parts = [part for part in text.split(";") if part]            # lists are joined with ";"
    return ";".join(sorted(parts))                                # sort so order doesn't matter


def values_match(value_a, value_b):
    """True if two comparable values mean the same answer."""
    number_a = to_number(value_a)                                 # try reading both as numbers
    number_b = to_number(value_b)
    if number_a is not None and number_b is not None:             # both numeric: compare with tolerance
        return math.isclose(number_a, number_b,
                            rel_tol=config.NUMBER_TOLERANCE,
                            abs_tol=config.NUMBER_TOLERANCE)
    return normalize_text(value_a) == normalize_text(value_b)     # otherwise compare cleaned text


def format_plan(steps):
    """['a', 'b'] -> '1. a\n2. b'"""
    return "\n".join(f"{number}. {step}" for number, step in enumerate(steps, start=1))
