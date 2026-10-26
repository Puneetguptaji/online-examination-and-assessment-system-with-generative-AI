"""Deterministic marking logic: no model call is involved in awarding marks."""


def calculate_score(question_rows):
    """Return (score, total_marks, percentage) for rows with marks/key/selected_option.

    Each row must contain ``marks`` and ``correct_option``; ``selected_option``
    may be None when the student left a question blank.
    """
    total = sum(int(row["marks"]) for row in question_rows)
    score = sum(
        int(row["marks"])
        for row in question_rows
        if row.get("selected_option") and row["selected_option"] == row["correct_option"]
    )
    percentage = round(score * 100.0 / total, 2) if total else 0.0
    return score, total, percentage
