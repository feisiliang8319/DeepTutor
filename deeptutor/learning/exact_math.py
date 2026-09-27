"""Bounded rational arithmetic for answer keys; never evaluates Python code."""
from __future__ import annotations

import ast
from fractions import Fraction
import re


def _number(expression: str) -> Fraction:
    expression = expression.strip().replace("×", "*").replace("÷", "/").replace("−", "-")
    # Accept thousands separators only in groups of exactly three digits.
    expression = re.sub(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d.,])",
                        lambda m: m.group().replace(",", ""), expression)
    if not expression or len(expression) > 256 or not re.fullmatch(r"[\d\s.+*/()\-]+", expression):
        raise ValueError("not bounded arithmetic")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 64:
        raise ValueError("expression too complex")

    def walk(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Fraction(ast.get_source_segment(expression, node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            return left / right
        raise ValueError("unsupported arithmetic")

    return walk(tree.body)


def _value(answer: str) -> Fraction:
    parts = answer.split("=")
    if len(parts) > 3:
        raise ValueError("too many equalities")
    values = [_number(p) for p in parts]
    if any(v != values[0] for v in values):
        raise ValueError("false equality")
    return values[-1]


def grade_math(user: str, expected: str) -> bool | None:
    """Return None for prose keys, False for malformed mathematical replies.

    Supports rational values, arithmetic, true equality chains and comparison
    blanks. Other response schemas need an explicit item rubric/judge.
    Units are never silently discarded. `times` denotes a dimensionless ratio.
    """
    user, expected = user.strip().lower(), expected.strip().lower()
    if len(user) > 256 or len(expected) > 256:
        return False if any(c.isdigit() for c in expected) else None
    expected = re.sub(r"(?<=\d)\s+times$", "", expected)
    user = re.sub(r"(?<=\d)\s+times$", "", user)
    if expected in {"<", ">", "=", "<=", ">=", "≤", "≥"}:
        normalize = lambda value: value.replace("≤", "<=").replace("≥", ">=")
        return normalize(user) == normalize(expected)
    try:
        relation = re.fullmatch(r"([^<>]+)([<>])([^<>]+)", expected)
        if relation:
            left, op, right = relation.groups()
            a, b = _number(left), _number(right)
            if not (a < b if op == "<" else a > b):
                return False
            if user == op:
                return True
            reply = re.fullmatch(r"([^<>]+)([<>])([^<>]+)", user)
            if not reply:
                return False
            x, sign, y = reply.groups()
            return sign == op and _number(x) == a and _number(y) == b
        target = _value(expected)
    except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
        # A broken arithmetic key must not fall back to exact string matching
        # (for example accepting the same false equality on both sides).
        return False if re.fullmatch(r"[\d\s.,+*/()×÷−=<>\-]+", expected) else None
    try:
        return _value(user) == target
    except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
        return False
