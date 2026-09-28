import unittest
from deeptutor.education.application.im_lesson_briefs import extract,sha

class IMLessonBriefTests(unittest.TestCase):
 def source(self):
  text='''## Lesson 1 — Preparation
Lesson 1
Factor Pairs

Lesson Purpose

Find factor pairs.

Lesson Narrative

A classroom narrative.

Learning Goals
Teacher Facing

Find all positive factor pairs of a number.

Student Facing

Let's find factors.

Required Materials

Materials to Gather

Tiles

Required Preparation

CCSS Standards

Building On

3.MD.C

Addressing

4.OA.B.4

Lesson Timeline

Warm-up
10 min

## Lesson 1 — Lesson Content
Student Response

Teachers with a valid work email can sign in.

Activity Synthesis

Do not put this content in the learning goals.
'''
  row={'family':'IM:G4:U1:L1','start':0,'end':len(text),'raw_sha256':sha(text),'id':'record-one','source_path':'unit1.md','source_sha256':sha(text),'source_line':1}
  return row,text
 def test_goals_are_bounded_and_source_spans_reconstruct_exact_values(self):
  row,text=self.source();b=extract(row,text)
  self.assertEqual(b['gated_response_sections'],1)
  self.assertNotIn('Activity Synthesis',b['student_goal'])
  self.assertNotIn('Tiles',b['teacher_goals'])
  self.assertEqual(b['standards'],{'Building On':['3.MD.C'],'Addressing':['4.OA.B.4']})
  for span in b['evidence'].values():self.assertEqual(sha(text[span['start']:span['end']]),span['sha256'])
  self.assertEqual(b['teaching_adaptation'],'pending')
 def test_changed_source_or_mismatched_lesson_fails(self):
  row,text=self.source()
  with self.assertRaises(ValueError):extract(row,text.replace('Find factor pairs.','Changed purpose.'))
  bad=text.replace('## Lesson 1 — Lesson Content','## Lesson 2 — Lesson Content');row.update(end=len(bad),raw_sha256=sha(bad))
  with self.assertRaises(ValueError):extract(row,bad)
 def test_unknown_standard_and_missing_audience_are_not_silently_dropped(self):
  for before,after in [('4.OA.B.4','malformed-standard'),('Student Facing','Student audience missing')]:
   row,text=self.source();text=text.replace(before,after);row.update(end=len(text),raw_sha256=sha(text))
   with self.assertRaises(ValueError):extract(row,text)
if __name__=='__main__':unittest.main()
