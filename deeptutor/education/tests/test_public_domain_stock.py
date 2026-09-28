import unittest,tempfile
from pathlib import Path
from deeptutor.education.application.public_domain_stock import numbered,tangled,parse_book

class HistoricalStockTests(unittest.TestCase):
    def book(self):
        def title(n):return 'THE CROSS TARGET.' if n==284 else f'PUZZLE {n}.'
        questions='\n\n'.join(f'{384 if n==284 else n}.--{title(n)}\n\nQuestion {n}.' for n in range(1,431))
        answers='\n\n'.join(f'{n}.--{title(n)}\n\nSolution {n}.' for n in range(1,431) if n!=163)
        return questions+'\n\nSOLUTIONS.\n\n'+answers+'\n\nINDEX.\nNot an answer.'

    def test_number_and_title_pairing_preserves_known_source_typo(self):
        q,a=numbered(self.book(),'amusements-in-mathematics.txt')
        self.assertEqual(len(q),430);self.assertEqual(len(a),429)
        self.assertEqual(q[284]['printed_number'],'384')
        self.assertEqual(q[284]['title'],a[284]['title'])
        self.assertNotIn(163,a)
        self.assertNotIn('Not an answer',a[430]['body'])
        self.assertEqual(q[384]['title'],'PUZZLE 384.')

    def test_unknown_title_or_missing_number_stops_pairing(self):
        for broken in [self.book().replace('Solution 12.','Solution 12.\n13.--UNEXPECTED HEADER.'),
                       self.book().replace('12.--PUZZLE 12.\n\nSolution 12.','12.--UNRELATED TITLE.\n\nSolution 12.'),
                       self.book().replace('42.--PUZZLE 42.','42x--PUZZLE 42.',1)]:
            with self.assertRaises(ValueError):numbered(broken,'amusements-in-mathematics.txt')

    def test_tangled_sections_keep_answer_commentary_out_of_next_problem(self):
        roman=['I','II','III','IV','V','VI','VII','VIII','IX','X']
        text='\n'.join(f'KNOT {n}.\nStory {n}.\n' for n in roman)+'APPENDIX.\n'
        text+='\n'.join(f'ANSWERS TO KNOT {n}.\nAnswer {n}.\n' for n in roman)+'THE END\nLicense.'
        q,a=tangled(text)
        self.assertEqual(len(q),10);self.assertEqual(len(a),10)
        self.assertEqual(a[10]['body'],'Answer X.')
        self.assertNotIn('Answer',q[10]['body'])
        with self.assertRaises(ValueError):tangled(text.replace('ANSWERS TO KNOT IV.','ANSWERS TO KNOT III.'))

    def test_activity_stays_reference_and_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'amusements-in-mathematics.txt';p.write_text(self.book())
            records=parse_book(p);activity=records[162]
            self.assertEqual(activity['kind'],'lesson');self.assertEqual(activity['state'],'reference_only')
            self.assertEqual(activity['approval'],'unreviewed')
            self.assertEqual(activity['explanation'],'')
            target=Path(tmp)/'book.txt';p.rename(target);p.symlink_to(target)
            with self.assertRaises(ValueError):parse_book(p)

if __name__=='__main__':unittest.main()
