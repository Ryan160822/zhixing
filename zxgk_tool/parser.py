import re

from .models import QueryItem, STATUS_INPUT_ERROR, STATUS_PENDING


ID_CARD_RE = re.compile(r"(?<!\d)(\d{17}[0-9Xx])(?!\d)")


def parse_batch_lines(text: str) -> list[QueryItem]:
    items: list[QueryItem] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue

        match = ID_CARD_RE.search(line)
        if match:
            card_num = match.group(1).upper()
            name = (line[: match.start()] + " " + line[match.end() :]).strip()
            name = " ".join(name.split())
            status = STATUS_INPUT_ERROR if not name else STATUS_PENDING
            error = "缺少姓名" if not name else None
            items.append(QueryItem(len(items) + 1, line, "person", name, card_num, status, None, error))
        else:
            items.append(QueryItem(len(items) + 1, line, "company", line, ""))
    return items
