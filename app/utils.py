import re


def mentioned_columns(text: str, columns: list[str]) -> list[str]:
    """Which of the known column names appear as whole words in text."""
    text_l = (text or "").lower()
    found = []
    for col in columns:
        if re.search(rf"\b{re.escape(col.lower())}\b", text_l):
            found.append(col)
    return found
