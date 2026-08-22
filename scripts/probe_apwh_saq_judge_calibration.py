"""Does the local judge actually mark the six AP World History SAQs sensibly?

Unlocking an item only helps if the verdict it produces is trustworthy. This
sends each of the six SAQs three answers written by hand against the stored
rubric — one that should score, one that is on-topic but thin, one that is
plainly wrong — and prints what the judge said.

There is no pass/fail assertion and this is not a test: model behaviour is
not a property a suite can pin (see ``test_llm_judge``'s docstring). It is a
calibration reading, to be looked at by a person before deciding these six
go in front of a child. Read-only: no database is opened for writing.

Usage: ``.venv/bin/python scripts/probe_apwh_saq_judge_calibration.py``
"""

from __future__ import annotations

import sqlite3
import sys

from deeptutor.education.application.llm_judge import LocalOpenAIJudge, judge_open_response
from deeptutor.education.storage.repositories import AssessmentItemRepository

DB = "/Users/gwp_group/Projects/deeptutor-education/data/education.db"
COURSE = "cv-hist-apworld-1.0.0"
MODEL = "Qwen3-VL-8B-Instruct-4bit"

# Written against each item's stored rubric, not copied from it — a verdict
# earned by echoing the reference answer back would prove nothing.
ANSWERS: dict[str, dict[str, str]] = {
    "apwh-u1-t11-saq2a": {
        "should_score":
            "Tang and Song rulers responded by patronising Confucian revival: they "
            "restored the civil service examinations on Confucian classics, which "
            "rebuilt an officialdom loyal to Confucian rather than Buddhist authority, "
            "and under Emperor Wuzong the state seized monastery land outright.",
        "thin": "They didn't like Buddhism so they pushed Confucianism instead.",
        "wrong": "Chinese leaders converted to Buddhism and banned Confucianism forever.",
    },
    "apwh-u1-t11-saq2c": {
        "should_score":
            "Neo-Confucianism absorbed Buddhist metaphysics: thinkers such as Zhu Xi "
            "took up questions about the nature of reality and self-cultivation that "
            "Confucianism had not addressed, producing a syncretic system that kept "
            "Confucian social ethics but answered Buddhist spiritual concerns.",
        "thin": "Confucianism borrowed some ideas from Buddhism.",
        "wrong": "Buddhism destroyed Confucianism, which disappeared after 1200.",
    },
    "apwh-u1-t12-saq1b": {
        "should_score":
            "The Sufis in the passage practise through collective devotion and ascetic "
            "discipline — a hundred prayer mats, bodies in humble devotion — seeking "
            "direct experience of God rather than centring practice on law and ritual "
            "as the ulama did, and that experiential, portable form is what carried "
            "Islam into new regions.",
        "thin": "The Sufis prayed a lot, which was different from other Muslims.",
        "wrong": "The Sufis were Christian priests who rejected Islam.",
    },
    # 2026-08-22：原 apwh-u1-t12-saq2b 因设问时段与史实冲突已 retired，改期版
    # apwh-u1-t12-saq2b-r2（711–1031）接替。校准要打在真正会发给孩子的那条上。
    "apwh-u1-t12-saq2b-r2": {
        "should_score":
            "The Umayyads of Cordoba turned the city into a centre of learning and "
            "wealth: they built the Great Mosque, funded libraries and translation of "
            "Greek texts, and presided over a relatively tolerant order in which "
            "Muslims, Christians and Jews all served the court.",
        "thin": "Cordoba was rich and had a big mosque.",
        "wrong": "The Umayyads of Cordoba conquered China and ruled it until 1450.",
    },
    "apwh-u1-t13-saq2a": {
        "should_score":
            "Both regions saw decentralised states legitimised through religion: "
            "Southern Indian kingdoms such as the Cholas and Southeast Asian polities "
            "such as the Khmer both used temple building and Hindu-Buddhist ritual "
            "kingship to bind local rulers to a paramount king rather than governing "
            "through a centralised bureaucracy.",
        "thin": "They both had kings and temples.",
        "wrong": "Both were centralised bureaucratic empires with no religion.",
    },
    "apwh-u1-t13-saq2c": {
        "should_score":
            "Muslim merchants and Sufi missionaries on Indian Ocean routes brought "
            "Islam to the region, and rulers who converted used it to legitimise their "
            "states — the sultanate of Malacca became a Muslim trading power whose "
            "conversion pulled surrounding ports into an Islamic commercial network.",
        "thin": "Traders brought Islam to Southeast Asia.",
        "wrong": "The Mongols conquered Japan in 1850 and forced everyone to convert.",
    },
}


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    items = {i.id: i for i in AssessmentItemRepository(conn).list_for_version(COURSE)}
    conn.close()

    judge = LocalOpenAIJudge()
    tally: dict[str, list[str]] = {"should_score": [], "thin": [], "wrong": []}

    for item_id, answers in ANSWERS.items():
        item = items.get(item_id)
        if item is None:
            print(f"!! {item_id} not in the database any more")
            continue
        print(f"\n=== {item_id} ===")
        print(f"    {(item.prompt or '')[-150:].strip()}")
        for kind, answer in answers.items():
            judgment = judge_open_response(judge, item, answer, model_ref=MODEL)
            tally[kind].append(judgment.verdict.value)
            print(f"  [{kind:12}] {judgment.verdict.value:12} "
                  f"conf={judgment.confidence} :: {(judgment.rationale or '')[:110]}")

    print("\n--- summary (what a person has to look at) ---")
    for kind, verdicts in tally.items():
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v] = counts.get(v, 0) + 1
        print(f"  {kind:12}: {counts}")
    print(
        "\nA scoring answer landing on 'incorrect' is the failure that matters: "
        "it is the child being told they are wrong when they are not."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
