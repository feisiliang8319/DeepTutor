"""Destructive-injection harness for the 2026-08-21 grading-policy fix.

A green test suite proves nothing on its own: it has to be shown that each
test *fails* when the thing it claims to protect is taken away. Every case
below reverts one line of the fix to exactly what it said before, runs the
tests that should notice, and asserts they go red.

Run: ``.venv/bin/python scripts/verify_grading_policy_regressions.py``
Exit 0 = every guard bites. Exit 1 = at least one test is decorative.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Injection:
    name: str
    path: str
    before: str
    after: str
    tests: str
    why: str


INJECTIONS = [
    Injection(
        name="short-length-ceiling-removed",
        path="deeptutor/education/application/grading_policy.py",
        before="""    if item.item_type is ItemType.SHORT:
        return len(item.expected_answer.strip()) > SHORT_FUZZY_MAX_CHARS
    return False""",
        after="""    return False""",
        tests="deeptutor/education/tests/test_grading_policy.py",
        why="the original bug: prose reference answers treated as auto-gradable",
    ),
    Injection(
        name="blank-answer-treated-as-a-real-key",
        path="deeptutor/education/application/grading_policy.py",
        before="    if item.expected_answer is None or not item.expected_answer.strip():",
        after="    if item.expected_answer is None:",
        tests="deeptutor/education/tests/test_grading_policy.py",
        why="an empty-string column would auto-mark every reply wrong",
    ),
    Injection(
        name="record-attempt-back-to-type-whitelist",
        path="deeptutor/education/application/record_attempt.py",
        before="    if needs_judgment(item):\n        return None, None",
        after=(
            "    if item.item_type in (ItemType.MULTI_STEP, ItemType.VISUAL_MODEL,"
            " ItemType.PAPER_REF):\n        return None, None\n"
            "    if item.expected_answer is None:\n        return None, None"
        ),
        tests="deeptutor/education/tests/test_grading_policy.py",
        why="grading path disagreeing with the selector is how the bug hid",
    ),
    Injection(
        name="api-judge-routing-back-to-item-type",
        path="deeptutor/education/api/app.py",
        before="if judge is not None and needs_judgment(item):",
        after=(
            "if judge is not None and item.item_type in (\n"
            "                        __import__('deeptutor.education.domain.course',"
            " fromlist=['ItemType']).ItemType.MULTI_STEP,):"
        ),
        tests="deeptutor/education/tests/test_grading_policy.py",
        why="selector serves it, handler refuses to judge it, attempt never resolves",
    ),
    Injection(
        name="marking-focus-back-to-focus-key-only",
        path="deeptutor/education/application/llm_judge.py",
        before="""    lines = []
    for key in _RUBRIC_GUIDANCE_KEYS:
        value = rubric.get(key)
        if value in (None, "", [], {}):
            continue
        lines.append(f"- {key.replace('_', ' ')}: {value}")
    return "\\n".join(lines)""",
        after="""    return str(rubric.get("focus") or "")""",
        tests="deeptutor/education/tests/test_judge_prompt.py",
        why="AP and synthetic rubrics silently absent from the judge prompt",
    ),
    Injection(
        name="reply-text-back-to-unguarded-indexing",
        path="deeptutor/education/application/llm_judge.py",
        before="""    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(message, dict):
        return ""
    for key in ("content", "reasoning_content", "thinking"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return \"\"""",
        after="""    return str(body["choices"][0]["message"]["content"])""",
        tests="deeptutor/education/tests/test_judge_prompt.py",
        why="a reply-shape problem reported as a transport failure",
    ),
    Injection(
        name="cache-bust-prefix-removed",
        path="deeptutor/education/application/llm_judge.py",
        before='                         "content": _CACHE_BUST_PREFIX.format(nonce=nonce) + system},',
        after='                         "content": system},',
        tests="deeptutor/education/tests/test_judge_prompt.py",
        why="identical prefixes let the server cache bug empty out every reply after the first",
    ),
]


def run(tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [".venv/bin/python", "-m", "pytest", *tests.split(), "-q", "--no-header", "-x"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def main() -> int:
    baseline = run("deeptutor/education/tests deeptutor/learning/tests tests/learning")
    if baseline.returncode != 0:
        print("BASELINE IS RED — fix that before trusting any injection below")
        print(baseline.stdout[-3000:])
        return 1
    print(f"baseline: {baseline.stdout.strip().splitlines()[-1]}\n")

    failures = []
    for inj in INJECTIONS:
        target = ROOT / inj.path
        original = target.read_text()
        if inj.before not in original:
            print(f"[SKIP-BROKEN] {inj.name}: anchor text not found in {inj.path}")
            failures.append(inj.name)
            continue
        target.write_text(original.replace(inj.before, inj.after, 1))
        try:
            result = run(inj.tests)
        finally:
            target.write_text(original)
        bites = result.returncode != 0
        print(f"[{'CAUGHT' if bites else 'MISSED'}] {inj.name}\n    ({inj.why})")
        if not bites:
            failures.append(inj.name)
        else:
            first = next(
                (ln for ln in result.stdout.splitlines() if ln.startswith("FAILED")),
                result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "?",
            )
            print(f"    -> {first}")

    after = run("deeptutor/education/tests deeptutor/learning/tests tests/learning")
    print(f"\nrestored: {after.stdout.strip().splitlines()[-1]}")
    if after.returncode != 0:
        print("!! suite did not return to green — a restore failed, inspect git status")
        return 1
    if failures:
        print(f"\nUNGUARDED: {', '.join(failures)}")
        return 1
    print("\nevery injection was caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
