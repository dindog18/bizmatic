def markdown_table(rows: list[list[str]]) -> str:
    """Render rows as a Markdown table, using the first row as its header.

    Rows shorter than the widest row are padded with empty cells. Pipe
    characters and embedded newlines are escaped so cell contents remain
    inside their table columns.
    """
    if not rows:
        return ""
    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]

    def escape(value: str) -> str:
        return value.replace("|", r"\|").replace("\n", "<br>")

    header = "| " + " | ".join(escape(value) for value in normalized_rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in normalized_rows[0]) + " |"
    body = ["| " + " | ".join(escape(value) for value in row) + " |" for row in normalized_rows[1:]]
    return "\n".join([header, separator, *body])
