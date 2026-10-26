import unittest
from scoring import calculate_score


class ScoreTests(unittest.TestCase):
    def test_score_uses_stored_answer_key_and_ignores_blanks(self):
        rows = [
            {"marks": 2, "correct_option": "A", "selected_option": "A"},
            {"marks": 1, "correct_option": "C", "selected_option": "B"},
            {"marks": 3, "correct_option": "D", "selected_option": None},
        ]
        self.assertEqual(calculate_score(rows), (2, 6, 33.33))

    def test_empty_exam_has_zero_percentage(self):
        self.assertEqual(calculate_score([]), (0, 0, 0.0))

    def test_all_correct(self):
        rows = [
            {"marks": 2, "correct_option": "A", "selected_option": "A"},
            {"marks": 3, "correct_option": "D", "selected_option": "D"},
        ]
        self.assertEqual(calculate_score(rows), (5, 5, 100.0))


if __name__ == "__main__":
    unittest.main()
