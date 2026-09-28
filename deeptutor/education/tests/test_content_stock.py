import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from deeptutor.education.application.content_stock import boxed, parse_file, process


def math_source(prompt='Calculate 6 times 7.',answer='42'):
    return '# MATH\nProblems in this file: 1\n\n## Algebra · Level 4 · Problem 1\n**Type:** Algebra  **Difficulty:** Level 4\n\n### Problem\n\n'+prompt+'\n\n### Solution\n\nSix groups of seven: \\boxed{'+answer+'}.\n\n---\n'


class StockTests(unittest.TestCase):
    def test_boxed_nested_braces_and_escaped_braces(self):
        self.assertEqual(boxed(r'\boxed{\frac{1}{48}} and \boxed{\{2,3\}}'),[r'\frac{1}{48}',r'\{2,3\}'])
        with self.assertRaises(ValueError): boxed(r'\boxed{\frac{1}{48}')

    def test_difficulty_never_becomes_grade(self):
        row=parse_file('math-competition','math-algebra.md',math_source())[0]
        self.assertEqual(row['source_difficulty'],'Level 4')
        self.assertIsNone(row['grade_assignment'])
        self.assertEqual(row['source_grade'],'')
        self.assertEqual(row['answer'],'42')

    def test_count_mismatch_fails_not_partial_success(self):
        with self.assertRaises(ValueError): parse_file('qasc','qasc-biology.md','Problems in this file: 2\n## One\n### Question\nTest?\n')

    def test_context_choices_case_and_missing_figure(self):
        text='Problems in this file: 1\n## verbs · grade3 · Q1\n**Grade:** grade3  **Topic:** verbs\n> original problem includes a figure that is not bundled\n**Context:** Tom will swim.\n\n### Question\nWhich tense?\n\n**Options:**\n- Future\n  tense\n- Present\n\n**Correct answer:** Future\n  tense\n\n### Explanation\nThe word will indicates the future.\n'
        row=parse_file('scienceqa','scienceqa-test.md',text)[0]
        self.assertTrue(row['prompt'].startswith('Tom will swim.'))
        self.assertEqual(row['options'],['Future\n  tense','Present'])
        self.assertIn('missing_figure',row['issues'])
        # Multi-line answer and option text must both survive extraction.
        self.assertEqual(row['answer'],'Future\n  tense')
        self.assertNotIn('answer_not_in_options',row['issues'])

    def test_history_answer_not_independent_fact(self):
        text='Entries: 1\n## A date\n### Question\nWhen?\n### Answer\n76 BCE.\n## Embedded historical context\nMore context.\n### Another paragraph\nStill the answer.\n'
        row=parse_file('world-history-1500','history.md',text)[0]
        self.assertIn('historical_fact_check',row['issues'])
        self.assertEqual(row['explanation'],'')
        self.assertIn('Still the answer.',row['answer'])

    def test_im_groups_preparation_and_content(self):
        text='## Lesson 1 — Preparation\nPlan.\n## Lesson 1 — Lesson Content\nTask.\n## Lesson 2 — Preparation\nPlan 2.\n'
        rows=parse_file('im-g4-full','grade4-unit1-factors.md',text)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['family'],'IM:G4:U1:L1')
        self.assertIn('Task.',rows[0]['prompt'])

    def test_all_source_copies_preserved_and_conflicts_not_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'input'; raw=root/'math-competition/raw';raw.mkdir(parents=True)
            (raw/'math-a.md').write_text(math_source())
            (raw/'math-b.md').write_text(math_source())
            (raw/'math-c.md').write_text(math_source(answer='43'))
            report=process(root,Path(tmp)/'output',batch_size=2)
            self.assertEqual(report['records'],3)
            self.assertEqual(report['committed_batches'],2)
            self.assertEqual(report['answer_conflict_records'],3)
            self.assertEqual(report['duplicate_records'],0)
            self.assertEqual(report['formal_quiz_items_created'],0)
            folder=Path(tmp)/'output'/report['snapshot_id']
            db=sqlite3.connect(folder/'catalog.sqlite3')
            self.assertEqual(db.execute("SELECT count(*) FROM records WHERE state='needs_repair'").fetchone()[0],3)
            db.close()
            self.assertEqual(process(root,Path(tmp)/'output'),report)
            with (folder/'catalog.sqlite3').open('ab') as f: f.write(b'corruption')
            with self.assertRaises(ValueError): process(root,Path(tmp)/'output')

    def test_same_answer_dedupes_but_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'in';raw=root/'math-competition/raw';raw.mkdir(parents=True)
            for suffix in ['a','b']: (raw/('math-'+suffix+'.md')).write_text(math_source())
            report=process(root,Path(tmp)/'out')
            self.assertEqual(report['records'],2)
            self.assertEqual(report['duplicate_records'],1)

    def test_missing_images_never_make_identical_text_safe_to_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'in';raw=root/'scienceqa/raw';raw.mkdir(parents=True)
            source='Problems in this file: 1\n## Q1\n> original problem includes a figure that is not bundled\n### Question\nWhich figure?\n**Options:**\n- A\n- B\n**Correct answer:** A\n### Explanation\nThe picture shows A.\n'
            for name in ['a.md','b.md']: (raw/name).write_text(source)
            report=process(root,Path(tmp)/'out')
            self.assertEqual(report['records'],2)
            self.assertEqual(report['duplicate_records'],0)
            self.assertEqual(report['issues']['missing_figure'],2)

    def test_symlink_cannot_read_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'in';raw=root/'qasc/raw';raw.mkdir(parents=True)
            other=Path(tmp)/'unrelated.md';other.write_text('private')
            (raw/'qasc-a.md').symlink_to(other)
            with self.assertRaises(ValueError): process(root,Path(tmp)/'out')


if __name__=='__main__': unittest.main()
