"""
calculator.py - A small, SAFE arithmetic evaluator.

The executor LLM writes each calculation as an expression like "(18*60+5) - (14*60+30)".
We compute it here with Python instead of trusting the LLM's arithmetic.

We do NOT use Python's eval(), because eval() would run any code the LLM writes.
Instead, we parse the expression into a tree (ast) and only allow:
numbers, + - * / // % **, brackets, and the functions min, max, abs, round.
Anything else raises an error.
"""

import ast                                                        # turns text into a syntax tree
import operator                                                   # plain functions for + - * / etc.

BINARY_OPERATORS = {                                              # allowed two-number operations
    ast.Add: operator.add,                                        # a + b
    ast.Sub: operator.sub,                                        # a - b
    ast.Mult: operator.mul,                                       # a * b
    ast.Div: operator.truediv,                                    # a / b
    ast.FloorDiv: operator.floordiv,                              # a // b (whole-number division)
    ast.Mod: operator.mod,                                        # a % b (remainder)
    ast.Pow: operator.pow,                                        # a ** b
}

UNARY_OPERATORS = {                                               # allowed one-number operations
    ast.USub: operator.neg,                                       # -a
    ast.UAdd: operator.pos,                                       # +a
}

ALLOWED_FUNCTIONS = {                                             # allowed function calls
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
}

MAX_EXPONENT = 10                                                 # stops huge numbers like 9**999999


def safe_eval(expression):
    """Compute an arithmetic expression safely. Raises ValueError if it is not allowed."""
    if not isinstance(expression, str) or not expression.strip():  # must be non-empty text
        raise ValueError("Expression is empty")
    tree = ast.parse(expression.strip(), mode="eval")             # parse; raises SyntaxError for bad text
    return _evaluate(tree.body)                                   # walk the tree and compute


def _evaluate(node):
    """Compute one node of the tree (calls itself for the parts inside)."""
    if isinstance(node, ast.Constant):                            # a plain value like 60 or 2.5
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):  # reject True/False and strings
            raise ValueError(f"Only numbers are allowed, got: {value!r}")
        return value

    if isinstance(node, ast.BinOp):                               # something like a + b
        operation = BINARY_OPERATORS.get(type(node.op))           # look up the operator
        if operation is None:
            raise ValueError(f"Operator not allowed: {type(node.op).__name__}")
        left = _evaluate(node.left)                               # compute the left side
        right = _evaluate(node.right)                             # compute the right side
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:  # protect against huge powers
            raise ValueError("Exponent too large")
        return operation(left, right)                             # ZeroDivisionError can happen here

    if isinstance(node, ast.UnaryOp):                             # something like -a
        operation = UNARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise ValueError(f"Operator not allowed: {type(node.op).__name__}")
        return operation(_evaluate(node.operand))

    if isinstance(node, ast.Call):                                # something like max(30, 45)
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            raise ValueError("Only min, max, abs and round can be called")
        if node.keywords:                                         # no name=value arguments
            raise ValueError("Keyword arguments are not allowed")
        arguments = [_evaluate(argument) for argument in node.args]  # compute each argument
        return ALLOWED_FUNCTIONS[node.func.id](*arguments)

    raise ValueError(f"Not allowed in an expression: {type(node).__name__}")  # names, strings, lists, etc.
