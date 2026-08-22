"""record_attempt — the one-answer transaction (P0-DESIGN.md §3).

Implements steps 1-6 of the design's 8-step sequence:

    1. validate learner / course_version / node / item exist and are legal
    2. deterministic grading where the item type supports it
    3. INSERT student_attempts            <- committed on its own, first
    4. optional judgment (LLM/human verdict, passed in pre-computed)
    5. recompute mastery_snapshots from attempts + judgments
    6. update review_states

Step 7 ("同步 DeepTutor 原生 LearningProgress 兼容视图") and step 8's wider
orchestration are **not** implemented here: this task's hard constraints
forbid touching ``deeptutor/learning`` in this phase, and P0-DESIGN.md §9
itself defers that adapter. See the package docstring.

Failure semantics (P0-DESIGN.md §3): step 3 failing means the whole
attempt fails and the caller should retry — nothing before step 3 has
touched the database, and step 3 is its own transaction, so there is
nothing to roll back beyond what SQLite already does for a single failed
INSERT. Steps 4-6 failing must **not** undo the attempt: it stays
committed, the affected learner+node is marked ``pending_recompute``
(reusing ``mastery_snapshots.status`` — see ``domain.learner``), and a
structured error is logged. ``application.rebuild_mastery.rebuild_learner_node``
is the idempotent command that heals a ``pending_recompute`` node; the
backlog of nodes waiting for it is queryable via
``storage.repositories.MasterySnapshotRepository.list_pending_recompute``
(2026-08-14 audit finding: writing the status without a read path meant
nothing would ever actually consume it).

Idempotency (2026-08-14 audit finding, fixed): test #11 requires that
resubmitting "the same attempt" produces exactly one row.
``AttemptRepository.insert``'s ``INSERT OR IGNORE`` dedup was always
correct, but this function used to generate a fresh ``uuid4()`` id on
*every* call, so the dedup key could never repeat and the guarantee was
unreachable from this entry point. ``NewAttemptInput.client_attempt_id``
is the caller-supplied idempotency key that fixes this — see its
docstring. When a retry is detected (the id already existed), this
function short-circuits before steps 4-6 so a retry cannot also duplicate
a ``judgment_records`` row.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sqlite3
import time
import uuid

from deeptutor.education.application import to_iso_timestamp
from deeptutor.education.application.grading_policy import needs_judgment
from deeptutor.education.application.rebuild_mastery import POLICY_VERSION, rebuild_learner_node
from deeptutor.education.application.review_scheduler import (
    FSRS_PARAMS_VER,
    ReviewMath,
    math_from_state,
    step_review,
)
from deeptutor.education.domain.course import AssessmentItem, ItemStatus, ItemType
from deeptutor.education.domain.evidence import (
    EvidenceStrength,
    JudgeKind,
    JudgmentRecord,
    Provenance,
    StudentAttempt,
    Verdict,
)
from deeptutor.education.domain.learner import MasterySnapshot, ReviewState
from deeptutor.education.storage.repositories import (
    AssessmentItemRepository,
    AttemptRepository,
    CourseRepository,
    JudgmentRepository,
    KnowledgeGraphRepository,
    LearnerRepository,
    MasterySnapshotRepository,
    ReviewStateRepository,
)
from deeptutor.education.storage.sqlite import transaction
from deeptutor.learning.grading import grade_answer

# Never format an exception's raw message into this logger, and never log
# an AssessmentItem's expected_answer/rubric_json — this is the log-side
# half of the "expected_answer 泄露闸门" (P0-DESIGN.md §2.4.2, test #9).
logger = logging.getLogger("deeptutor.education.alerts")

_NUMERIC_TOLERANCE = 1e-6

# Scheduling now runs on real FSRS-6 via py-fsrs; the placeholder that used
# to live here (``p0-internal-v1``, stability × a hand-picked factor, no
# notion of elapsed time) was replaced 2026-08-14. See
# ``application/review_scheduler.py`` for the two configuration decisions
# that matter — fuzzing disabled, and scheduling driven by the attempt's
# ``submitted_at`` rather than the wall clock — both for replayability.


class ValidationError(ValueError):
    """Step 1 failure: a referenced id does not exist or is in an illegal
    state. Raised before any write."""


@dataclass(frozen=True, slots=True)
class JudgmentInput:
    judge_kind: JudgeKind
    judge_ref: str
    verdict: Verdict
    confidence: float | None = None
    rationale: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None


@dataclass(frozen=True, slots=True)
class NewAttemptInput:
    learner_id: str
    assessment_item_id: str
    response: str
    started_at: str
    submitted_at: str
    source: str
    hint_count: int = 0
    retry_index: int = 0
    duration_ms: int | None = None
    evidence_strength: EvidenceStrength = EvidenceStrength.SYSTEM_GRADED
    provenance: Provenance = Provenance.NATIVE
    grader_version: str = "p0-v1"
    # For item types the deterministic grader cannot score (multi_step /
    # visual_model / paper_ref), or a caller that already has a human
    # result (e.g. a paper_ref outcome phoned in by a parent).
    manual_is_correct: bool | None = None
    manual_score: float | None = None
    # A pre-computed judgment to attach (e.g. an LLM's Feynman-check
    # verdict obtained by the caller *before* calling this function — this
    # module never calls an LLM provider itself, see the package's hard
    # "no LLM-provider-coupled code" constraint).
    judgment: JudgmentInput | None = None
    # The idempotency key: becomes ``student_attempts.id`` verbatim. A
    # caller that retries the same logical submission (lost response,
    # duplicate network delivery, etc.) MUST pass the same value here for
    # AttemptRepository's ``INSERT OR IGNORE`` dedup (test #11) to actually
    # apply on this entry point — see the 2026-08-14 audit finding this
    # field closes: without it, ``record_attempt`` generated a fresh
    # ``uuid4()`` per call, so the storage-layer dedup key could never
    # repeat and two "identical" submissions silently produced two attempts.
    # If omitted, a fresh uuid4 is generated and **no idempotency guarantee
    # applies** — that is a deliberate opt-in, not a safe default, because
    # this function cannot know a caller's retry semantics for it.
    client_attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class RecordAttemptResult:
    attempt: StudentAttempt
    mastery_snapshot: MasterySnapshot | None
    pending_recompute: bool
    error: str | None = None


def _grade(item: AssessmentItem, response: str) -> tuple[bool | None, float | None]:
    """Deterministic grading for the items that support it.

    ``(None, None)`` means nothing here can settle this item and a
    human/LLM judgment has to: an open task, an item with no reference
    answer, or a ``short`` item whose reference answer is prose rather than
    an exact-match key. That last case used to fall through to
    ``grade_answer`` and come back ``False`` for every possible reply —
    see ``grading_policy`` for what that cost.
    """
    if needs_judgment(item):
        return None, None
    if item.item_type is ItemType.NUMERIC:
        try:
            correct = abs(float(response) - float(item.expected_answer)) <= _NUMERIC_TOLERANCE
        except (TypeError, ValueError):
            correct = False
        return correct, (1.0 if correct else 0.0)
    question_type = "choice" if item.item_type is ItemType.CHOICE else "short"
    correct = grade_answer(response, item.expected_answer, question_type)
    return correct, (1.0 if correct else 0.0)


def _safe_error_text(exc: Exception) -> str:
    """A log-safe error description: only the exception's *class name*, a
    static template around it. Never interpolates ``str(exc)`` — an
    exception raised deep inside grading/mastery code could in principle
    carry item content in its args, and this is the one place P0-DESIGN.md
    §2.4.2's "日志脱敏清单必须含 expected_answer" gate is enforced for the
    failure path (test #9)."""
    return f"{type(exc).__name__} raised during post-commit mastery/review recompute"


def _mark_pending_recompute(
    conn: sqlite3.Connection, learner_id: str, knowledge_node_id: str, attempt_id: str
) -> None:
    existing = MasterySnapshotRepository(conn).get(learner_id, knowledge_node_id)
    snapshot = MasterySnapshot(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        score=existing.score if existing is not None else 0.0,
        status="pending_recompute",
        confidence=existing.confidence if existing is not None else None,
        policy_version=POLICY_VERSION,
        last_attempt_id=attempt_id,
        evidence_watermark=existing.evidence_watermark if existing is not None else None,
        updated_at=to_iso_timestamp(time.time()),
    )
    MasterySnapshotRepository(conn).upsert(snapshot)


def _update_review_state(
    conn: sqlite3.Connection,
    learner_id: str,
    knowledge_node_id: str,
    *,
    is_correct: bool | None,
    reviewed_at: str,
) -> None:
    """Advance the FSRS card for this node.

    Skips entirely when correctness is not yet settled (``is_correct is
    None``): an unresolved attempt is not evidence of recall, so it must not
    move the review schedule.

    ``reviewed_at`` is the attempt's ``submitted_at``, not ``time.time()`` —
    that is what makes ``replay_review_state`` able to reproduce the stored
    schedule instead of merely approximating it.
    """
    if is_correct is None:
        return
    repo = ReviewStateRepository(conn)
    after = step_review(
        math_from_state(repo.get(learner_id, knowledge_node_id)),
        is_correct=is_correct,
        reviewed_at=reviewed_at,
    )
    repo.upsert(
        ReviewState(
            learner_id=learner_id,
            knowledge_node_id=knowledge_node_id,
            stability=after.stability,
            difficulty=after.difficulty,
            due_at=after.due_at,
            last_review_at=after.last_review_at,
            reps=after.reps,
            lapses=after.lapses,
            fsrs_state=after.state,
            fsrs_step=after.step,
            fsrs_params_ver=FSRS_PARAMS_VER,
        )
    )


@dataclass(frozen=True, slots=True)
class ReviewStateReplayReport:
    """Test matrix item #14: 'review_states replay differences are
    recorded, not asserted equal' (P0-DESIGN.md §2.8 — this table is
    explicitly excluded from the rebuild-exactness contract that applies to
    mastery_snapshots). Callers should log/inspect this, never fail a build
    because ``matches`` is False.
    """

    online: ReviewState | None
    replayed: ReviewMath | None
    matches: bool
    note: str


def replay_review_state(
    conn: sqlite3.Connection, learner_id: str, knowledge_node_id: str
) -> ReviewStateReplayReport:
    """Reconstruct stability/difficulty/reps/lapses purely by replaying the
    ordered correctness sequence from ``student_attempts``, and compare
    against whatever is currently stored online. Never writes anything.
    """
    attempts = AttemptRepository(conn).list_for_node(learner_id, knowledge_node_id)
    state: ReviewMath | None = None
    touched = False
    for attempt in attempts:
        if attempt.is_correct is None:
            continue
        # Replay uses each attempt's own submitted_at, exactly as the online
        # path did, so an unchanged attempt history reproduces the schedule
        # rather than merely resembling it.
        state = step_review(state, is_correct=attempt.is_correct, reviewed_at=attempt.submitted_at)
        touched = True

    online = ReviewStateRepository(conn).get(learner_id, knowledge_node_id)
    replayed = state if touched else None
    matches = (
        online is not None
        and replayed is not None
        and online.stability == replayed.stability
        and online.difficulty == replayed.difficulty
        and online.reps == replayed.reps
        and online.lapses == replayed.lapses
        and online.due_at == replayed.due_at
        and online.fsrs_state == replayed.state
    )
    return ReviewStateReplayReport(
        online=online,
        replayed=replayed,
        matches=matches,
        note=(
            "review_states is time-relative state, explicitly excluded from "
            "the rebuild-exactness contract (P0-DESIGN.md §2.8). Since the "
            "2026-08-14 py-fsrs swap the online path and this replay both key "
            "off each attempt's submitted_at with fuzzing disabled, so they "
            "normally do match — but a mismatch is still only recorded here, "
            "never asserted, because a params/version change legitimately "
            "moves the schedule without any attempt changing."
        ),
    )


def record_attempt(conn: sqlite3.Connection, params: NewAttemptInput) -> RecordAttemptResult:
    # --- Step 1: validate everything referenced exists and is legal ---
    if LearnerRepository(conn).get(params.learner_id) is None:
        raise ValidationError(f"unknown learner_id {params.learner_id!r}")

    item = AssessmentItemRepository(conn).get(params.assessment_item_id)
    if item is None:
        raise ValidationError(f"unknown assessment_item_id {params.assessment_item_id!r}")

    if item.status is ItemStatus.RETIRED:
        raise ValidationError(f"assessment_item {item.id!r} is retired and cannot be attempted")

    node = KnowledgeGraphRepository(conn).get_node(item.knowledge_node_id)
    if node is None:
        raise ValidationError(f"assessment_item {item.id!r} points at a missing knowledge_node")
    version = CourseRepository(conn).get_course_version(item.course_version_id)
    if version is None:
        raise ValidationError(f"assessment_item {item.id!r} points at a missing course_version")

    # --- Step 2: deterministic grading where possible ---
    is_correct, score = _grade(item, params.response)
    if is_correct is None and params.manual_is_correct is not None:
        is_correct, score = params.manual_is_correct, params.manual_score

    # paper_ref items have no expected_answer to grade against by design
    # (P0-DESIGN.md §2.4.1) — correctness always comes from a human report,
    # never the system grader. This is a domain invariant, not merely a
    # caller default: force it here so a caller cannot accidentally record
    # a paper_ref attempt as SYSTEM_GRADED and let it silently outweigh
    # real auto-graded evidence in rebuild_mastery (§2.5's evidence_strength
    # split only works if this holds).
    evidence_strength = params.evidence_strength
    if item.item_type is ItemType.PAPER_REF:
        evidence_strength = EvidenceStrength.HUMAN_REPORTED

    now = time.time()
    attempt = StudentAttempt(
        id=params.client_attempt_id or str(uuid.uuid4()),
        learner_id=params.learner_id,
        assessment_item_id=item.id,
        knowledge_node_id=item.knowledge_node_id,
        course_version_id=item.course_version_id,
        response=params.response,
        is_correct=is_correct,
        score=score,
        started_at=params.started_at,
        submitted_at=params.submitted_at,
        duration_ms=params.duration_ms,
        hint_count=params.hint_count,
        retry_index=params.retry_index,
        grader_version=params.grader_version,
        source=params.source,
        provenance=params.provenance,
        evidence_strength=evidence_strength,
        created_at=to_iso_timestamp(now),
    )

    # --- Step 3: the attempt is the fact. Committed on its own; if this
    # fails, nothing else in this function has run yet. ---
    with transaction(conn):
        newly_inserted = AttemptRepository(conn).insert(attempt)

    if not newly_inserted:
        # A row with this id already existed — this is a retried call with
        # the same client_attempt_id (test #11's idempotent-submit path, now
        # reachable from this entry point and not just from
        # AttemptRepository.insert() called directly). Steps 4-6 already ran
        # for the original call; re-running them would (a) be redundant and
        # (b) insert a second judgment_records row for the same logical
        # judgment on every retry, since judgment_records has no natural
        # dedup key of its own. Short-circuit and hand back the settled
        # state instead.
        existing_attempt = AttemptRepository(conn).get(attempt.id)
        assert existing_attempt is not None  # insert() returning False guarantees this
        existing_snapshot = MasterySnapshotRepository(conn).get(
            params.learner_id, item.knowledge_node_id
        )
        return RecordAttemptResult(
            attempt=existing_attempt,
            mastery_snapshot=existing_snapshot,
            pending_recompute=(
                existing_snapshot is not None and existing_snapshot.status == "pending_recompute"
            ),
            error=None,
        )

    # --- Steps 4-6: judgment + mastery + review schedule, as one unit.
    # The attempt above is already durable — a failure here must not undo
    # it (P0-DESIGN.md §3). ---
    pending_recompute = False
    error_message: str | None = None
    snapshot: MasterySnapshot | None = None
    try:
        with transaction(conn):
            if params.judgment is not None:
                JudgmentRepository(conn).insert(
                    JudgmentRecord(
                        id=str(uuid.uuid4()),
                        attempt_id=attempt.id,
                        judge_kind=params.judgment.judge_kind,
                        judge_ref=params.judgment.judge_ref,
                        prompt_version=params.judgment.prompt_version,
                        rubric_version=params.judgment.rubric_version,
                        verdict=params.judgment.verdict,
                        confidence=params.judgment.confidence,
                        rationale=params.judgment.rationale,
                        created_at=to_iso_timestamp(time.time()),
                    )
                )
            snapshot = rebuild_learner_node(conn, params.learner_id, item.knowledge_node_id)
            _update_review_state(
                conn,
                params.learner_id,
                item.knowledge_node_id,
                is_correct=attempt.is_correct,
                reviewed_at=attempt.submitted_at,
            )
    except Exception as exc:  # noqa: BLE001 - any failure here must not undo step 3's commit
        error_message = _safe_error_text(exc)
        logger.error(
            "record_attempt: post-commit steps failed; attempt stays committed, "
            "marking node pending_recompute",
            extra={
                "learner_id": params.learner_id,
                "knowledge_node_id": item.knowledge_node_id,
                "attempt_id": attempt.id,
                "error": error_message,
            },
        )
        _mark_pending_recompute(conn, params.learner_id, item.knowledge_node_id, attempt.id)
        pending_recompute = True

    return RecordAttemptResult(
        attempt=attempt,
        mastery_snapshot=snapshot,
        pending_recompute=pending_recompute,
        error=error_message,
    )


__all__ = [
    "JudgmentInput",
    "NewAttemptInput",
    "RecordAttemptResult",
    "ReviewStateReplayReport",
    "ValidationError",
    "record_attempt",
    "replay_review_state",
]
