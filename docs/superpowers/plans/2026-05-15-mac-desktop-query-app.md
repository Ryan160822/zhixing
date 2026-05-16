# Mac Desktop Query App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Mac desktop app that batch-parses personal/company query lines, pauses for manual captcha input, submits China execution information queries, and saves result PNG files.

**Architecture:** Use a small Python package with clear modules: parsing, court website client, PNG rendering, and Tkinter UI. The UI owns queue state and calls the client on background threads so the window stays responsive. Tests cover deterministic parsing, filename generation, and PNG rendering before UI/network integration.

**Tech Stack:** Python 3, Tkinter, requests, Pillow, unittest.

---

## File Structure

- Create `zxgk_tool/__init__.py`: package marker and version.
- Create `zxgk_tool/models.py`: dataclasses and status constants shared by parser, renderer, and UI.
- Create `zxgk_tool/parser.py`: batch input parsing and personal/company detection.
- Create `zxgk_tool/renderer.py`: safe filename creation and PNG rendering.
- Create `zxgk_tool/client.py`: China execution information website session, captcha download, and search submission.
- Create `zxgk_tool/app.py`: Tkinter desktop app and queue workflow.
- Create `run_app.py`: tiny entry point for launching the app.
- Create `tests/test_parser.py`: parser tests.
- Create `tests/test_renderer.py`: renderer tests.
- Modify `README.md`: add Mac app launch instructions.
- Modify `.gitignore`: ignore temporary captcha files and local app runtime files.

## Task 1: Input Parser

**Files:**
- Create: `zxgk_tool/__init__.py`
- Create: `zxgk_tool/models.py`
- Create: `zxgk_tool/parser.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_parser.py`:

```python
import unittest

from zxgk_tool.parser import parse_batch_lines


class ParseBatchLinesTest(unittest.TestCase):
    def test_detects_person_when_id_card_is_first(self):
        items = parse_batch_lines("330000199001011234 张三")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "person")
        self.assertEqual(items[0].name, "张三")
        self.assertEqual(items[0].card_num, "330000199001011234")
        self.assertIsNone(items[0].error)

    def test_detects_person_when_id_card_is_last(self):
        items = parse_batch_lines("李四 33000019880505222X")
        self.assertEqual(items[0].kind, "person")
        self.assertEqual(items[0].name, "李四")
        self.assertEqual(items[0].card_num, "33000019880505222X")

    def test_detects_company_when_no_id_card_exists(self):
        items = parse_batch_lines("某某建设有限公司")
        self.assertEqual(items[0].kind, "company")
        self.assertEqual(items[0].name, "某某建设有限公司")
        self.assertEqual(items[0].card_num, "")

    def test_marks_id_only_line_as_error(self):
        items = parse_batch_lines("330000199001011234")
        self.assertEqual(items[0].kind, "person")
        self.assertEqual(items[0].status, "输入错误")
        self.assertEqual(items[0].error, "缺少姓名")

    def test_ignores_blank_lines_and_preserves_order(self):
        text = "\\n330000199001011234 张三\\n\\n某某建设有限公司\\n"
        items = parse_batch_lines(text)
        self.assertEqual([item.name for item in items], ["张三", "某某建设有限公司"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_parser -v
```

Expected: FAIL or ERROR because `zxgk_tool.parser` does not exist.

- [ ] **Step 3: Implement parser models**

Create `zxgk_tool/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `zxgk_tool/models.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path


STATUS_PENDING = "等待中"
STATUS_WAITING_CAPTCHA = "等待验证码"
STATUS_QUERYING = "查询中"
STATUS_DONE = "已完成"
STATUS_CAPTCHA_ERROR = "验证码错误"
STATUS_FAILED = "查询失败"
STATUS_INPUT_ERROR = "输入错误"


@dataclass
class QueryItem:
    index: int
    raw: str
    kind: str
    name: str
    card_num: str = ""
    status: str = STATUS_PENDING
    output_path: Path | None = None
    error: str | None = None
```

Create `zxgk_tool/parser.py`:

```python
import re

from .models import QueryItem, STATUS_INPUT_ERROR


ID_CARD_RE = re.compile(r"(?<!\\d)(\\d{17}[0-9Xx])(?!\\d)")


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
            status = STATUS_INPUT_ERROR if not name else "等待中"
            error = "缺少姓名" if not name else None
            items.append(QueryItem(len(items) + 1, line, "person", name, card_num, status, None, error))
        else:
            items.append(QueryItem(len(items) + 1, line, "company", line, ""))
    return items
```

- [ ] **Step 4: Run parser tests and verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_parser -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit parser**

```bash
git add zxgk_tool tests/test_parser.py
git commit -m "Add batch input parser"
```

## Task 2: PNG Renderer

**Files:**
- Create: `zxgk_tool/renderer.py`
- Test: `tests/test_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/test_renderer.py`:

```python
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from zxgk_tool.models import QueryItem
from zxgk_tool.renderer import make_result_filename, render_result_png


class RendererTest(unittest.TestCase):
    def test_make_result_filename_removes_path_unsafe_characters(self):
        item = QueryItem(1, "某/某:公司", "company", "某/某:公司")
        filename = make_result_filename(item, "2026-05-15")
        self.assertEqual(filename, "某_某_公司_被执行人查询结果_2026-05-15.png")

    def test_render_empty_result_creates_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = QueryItem(1, "330000199001011234 张三", "person", "张三", "330000199001011234")
            out = render_result_png(item, [], Path(tmp), "2026-05-15")
            self.assertTrue(out.exists())
            with Image.open(out) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1400, 980))

    def test_render_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = QueryItem(1, "某某建设有限公司", "company", "某某建设有限公司")
            first = render_result_png(item, [], Path(tmp), "2026-05-15")
            second = render_result_png(item, [], Path(tmp), "2026-05-15")
            self.assertNotEqual(first, second)
            self.assertTrue(second.name.endswith("_2.png"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run renderer tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_renderer -v
```

Expected: FAIL or ERROR because `zxgk_tool.renderer` does not exist.

- [ ] **Step 3: Implement renderer**

Create `zxgk_tool/renderer.py` with functions:

```python
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import QueryItem


IMAGE_SIZE = (1400, 980)
COURT_SCOPE = "全国法院（包含地方各级法院）"
QUERY_URL = "https://zxgk.court.gov.cn/zhzxgk/"


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r'[\\\\/:*?"<>|\\s]+', "_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "未命名"


def make_result_filename(item: QueryItem, date_text: str) -> str:
    return f"{safe_filename_part(item.name)}_被执行人查询结果_{date_text}.png"


def next_available_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def render_result_png(item: QueryItem, rows: list[dict], output_dir: Path, date_text: str) -> Path:
    out = next_available_path(output_dir, make_result_filename(item, date_text))
    image = Image.new("RGB", IMAGE_SIZE, "#eeeeee")
    draw = ImageDraw.Draw(image)

    f_title = load_font(42, True)
    f_sub = load_font(22)
    f_h2 = load_font(24, True)
    f_label = load_font(21, True)
    f_text = load_font(21)
    f_small = load_font(17)
    f_table = load_font(20, True)
    f_warn = load_font(22)
    f_warn_bold = load_font(22, True)

    width, height = IMAGE_SIZE
    header_h = 145
    draw.rectangle([0, 0, width, header_h], fill="#ffffff")
    draw.rectangle([0, header_h - 6, width, header_h], fill="#c71920")
    left = 115
    draw.ellipse([left, 34, left + 70, 104], outline="#c71920", width=5)
    draw.text((left + 35, 69), "法", anchor="mm", fill="#c71920", font=load_font(34, True))
    draw.text((left + 92, 35), "中国执行信息公开网", fill="#b50000", font=f_title)
    draw.text((left + 95, 91), "全国法院信息综合查询 - 综合查询被执行人", fill="#666666", font=f_sub)

    content_x = 115
    content_w = width - 230

    def block(y: int, title: str, block_h: int) -> int:
        draw.rectangle([content_x, y, content_x + content_w, y + block_h], fill="#ffffff", outline="#dddddd", width=1)
        draw.rectangle([content_x, y, content_x + content_w, y + 54], fill="#f5f5f5", outline="#dddddd", width=1)
        draw.text((content_x + 22, y + 15), title, fill="#333333", font=f_h2)
        return y + 54

    body_y = block(185, "综合查询被执行人", 240)
    card_label = item.card_num if item.card_num else "未填写"
    for i, (label, value) in enumerate([
        ("被执行人姓名/名称:", item.name),
        ("身份证号码/组织机构代码:", card_label),
        ("执行法院范围:", COURT_SCOPE),
    ]):
        y0 = body_y + 22 + i * 56
        if i > 0:
            draw.line([content_x + 28, y0, content_x + content_w - 28, y0], fill="#f0f0f0", width=1)
        draw.text((content_x + 285, y0 + 18), label, anchor="ra", fill="#555555", font=f_label)
        draw.text((content_x + 315, y0 + 18), value, fill="#222222" if i != 2 else "#666666", font=f_text)

    body_y = block(455, "查询结果", 370)
    tx = content_x + 32
    ty = body_y + 28
    col_w = [90, 230, 260, 420, 120]
    for col_width, header in zip(col_w, ["序号", "姓名", "立案时间", "案号", "查看"]):
        draw.rectangle([tx, ty, tx + col_width, ty + 48], fill="#eeeeee", outline="#dddddd")
        draw.text((tx + 14, ty + 13), header, fill="#333333", font=f_table)
        tx += col_width

    tx = content_x + 32
    if rows:
        for row_index, row in enumerate(rows[:8], start=1):
            row_y = ty + 48 * row_index
            values = [
                str(row_index),
                str(row.get("pname", "")),
                str(row.get("caseCreateTimeText", "")),
                str(row.get("caseCode", "")),
                "查看",
            ]
            x = tx
            for col_width, value in zip(col_w, values):
                draw.rectangle([x, row_y, x + col_width, row_y + 48], fill="#ffffff", outline="#e2e2e2")
                draw.text((x + 14, row_y + 13), value, fill="#333333", font=f_text)
                x += col_width
    else:
        x = tx
        for col_width in col_w:
            draw.rectangle([x, ty + 48, x + col_width, ty + 96], fill="#ffffff", outline="#e2e2e2")
            x += col_width
        warn_y = ty + 122
        draw.rectangle([tx, warn_y, content_x + content_w - 32, warn_y + 76], fill="#fcf8e3", outline="#faebcc")
        x = tx + 18
        base_y = warn_y + 24
        target = f"{item.card_num} {item.name}".strip()
        for text, font, color in [
            ("在", f_warn, "#8a6d3b"),
            (COURT_SCOPE, f_warn_bold, "#b50000"),
            ("范围内没有找到 ", f_warn, "#8a6d3b"),
            (target, f_warn_bold, "#b50000"),
            (" 相关的结果.", f_warn, "#8a6d3b"),
        ]:
            draw.text((x, base_y), text, fill=color, font=font)
            x += int(draw.textlength(text, font=font))

    meta_y = ty + 240
    draw.text((content_x + 32, meta_y), f"查询网站：{QUERY_URL}", fill="#666666", font=f_small)
    draw.text((content_x + content_w - 32, meta_y), f"查询日期：{date_text}", anchor="ra", fill="#666666", font=f_small)
    draw.text((content_x, height - 70), "本图根据中国执行信息公开网本次查询返回结果生成。", fill="#777777", font=f_small)

    image.save(out, "PNG")
    return out
```

- [ ] **Step 4: Run renderer tests and verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_renderer -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit renderer**

```bash
git add zxgk_tool/renderer.py tests/test_renderer.py
git commit -m "Add result PNG renderer"
```

## Task 3: Court Website Client

**Files:**
- Create: `zxgk_tool/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: Write failing client parsing tests**

Create `tests/test_client.py`:

```python
import json
import unittest

from zxgk_tool.client import extract_captcha_id, parse_search_response


class ClientHelpersTest(unittest.TestCase):
    def test_extract_captcha_id_from_page(self):
        html = '<input id="captchaId" name="captchaId" type="hidden" value="abc123"/>'
        self.assertEqual(extract_captcha_id(html), "abc123")

    def test_extract_captcha_id_returns_none_when_missing(self):
        self.assertIsNone(extract_captcha_id("<html></html>"))

    def test_parse_search_response_empty_result(self):
        body = json.dumps([{"result": [], "totalSize": 0, "currentPage": 1}], ensure_ascii=False)
        parsed = parse_search_response(body)
        self.assertEqual(parsed.total_size, 0)
        self.assertEqual(parsed.rows, [])

    def test_parse_search_response_error_body_is_captcha_error(self):
        parsed = parse_search_response("error")
        self.assertEqual(parsed.error, "验证码错误或已过期")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run client tests and verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_client -v
```

Expected: FAIL or ERROR because `zxgk_tool.client` does not exist.

- [ ] **Step 3: Implement client helpers and session**

Create `zxgk_tool/client.py` with:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

from .models import QueryItem


BASE_URL = "https://zxgk.court.gov.cn/zhzxgk/"
CAPTCHA_RE = re.compile(r'id="captchaId"\\s+name="captchaId"\\s+type="hidden"\\s+value="([^"]+)"')


@dataclass
class CaptchaChallenge:
    captcha_id: str
    image_path: Path


@dataclass
class SearchResult:
    rows: list[dict]
    total_size: int = 0
    error: str | None = None


def extract_captcha_id(html: str) -> str | None:
    match = CAPTCHA_RE.search(html)
    return match.group(1) if match else None


def parse_search_response(body: str) -> SearchResult:
    if body.strip() == "error":
        return SearchResult([], 0, "验证码错误或已过期")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return SearchResult([], 0, "查询返回内容无法解析")
    if not payload:
        return SearchResult([], 0)
    first = payload[0]
    return SearchResult(first.get("result", []), int(first.get("totalSize", 0) or 0))


class CourtClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })

    def fetch_captcha(self, captcha_dir: Path, label: str) -> CaptchaChallenge:
        response = self.session.get(BASE_URL, timeout=30)
        response.raise_for_status()
        captcha_id = extract_captcha_id(response.text)
        if not captcha_id:
            raise RuntimeError("没有找到验证码，请稍后重试")
        captcha_dir.mkdir(parents=True, exist_ok=True)
        image_path = captcha_dir / f"验证码_{label}_{captcha_id}.png"
        captcha_url = urljoin(BASE_URL, f"captcha.do?captchaId={captcha_id}&random=0.5")
        image_response = self.session.get(captcha_url, timeout=30)
        image_response.raise_for_status()
        image_path.write_bytes(image_response.content)
        return CaptchaChallenge(captcha_id, image_path)

    def search(self, item: QueryItem, captcha: CaptchaChallenge, code: str) -> SearchResult:
        data = {
            "pName": item.name,
            "pCardNum": item.card_num,
            "selectCourtId": "0",
            "pCode": code.strip(),
            "captchaId": captcha.captcha_id,
            "searchCourtName": "全国法院（包含地方各级法院）",
            "selectCourtArrange": "1",
            "currentPage": "1",
        }
        response = self.session.post(urljoin(BASE_URL, "searchZhcx.do"), data=data, timeout=30)
        response.raise_for_status()
        return parse_search_response(response.text)
```

- [ ] **Step 4: Run client tests and verify they pass**

Run:

```bash
.venv/bin/python -m unittest tests.test_client -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit client**

```bash
git add zxgk_tool/client.py tests/test_client.py
git commit -m "Add court website client"
```

## Task 4: Tkinter Mac App

**Files:**
- Create: `zxgk_tool/app.py`
- Create: `run_app.py`
- Modify: `README.md`

- [ ] **Step 1: Add app shell**

Create `zxgk_tool/app.py` with a `ZxgkApp` class that builds a single Tkinter window containing input, captcha, and queue sections.

- [ ] **Step 2: Wire parser into UI**

The Start button calls `parse_batch_lines`, stores the queue, and renders rows in a `ttk.Treeview`.

- [ ] **Step 3: Wire sequential captcha workflow**

The app picks the next non-error pending item, fetches a captcha on a background thread, displays the image, focuses the captcha entry, and sets status to `等待验证码`.

- [ ] **Step 4: Wire submit workflow**

The Submit button and Return key submit the current captcha on a background thread. On success, call `render_result_png`, delete the captcha image, set output path, and move to the next item.

- [ ] **Step 5: Wire retry captcha shortcut**

Bind `Command-r` to refresh captcha for the current item. On captcha error, keep the same item selected and show a user-readable error.

- [ ] **Step 6: Add launcher**

Create `run_app.py`:

```python
from zxgk_tool.app import main


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Smoke test launch**

Run:

```bash
.venv/bin/python run_app.py
```

Expected: the Mac desktop window opens. Close it after verifying the layout.

- [ ] **Step 8: Commit app UI**

```bash
git add zxgk_tool/app.py run_app.py README.md
git commit -m "Add Mac desktop app"
```

## Task 5: Final Verification

**Files:**
- Modify if needed: `README.md`
- Modify if needed: `docs/项目使用说明.md`

- [ ] **Step 1: Run all unit tests**

Run:

```bash
.venv/bin/python -m unittest discover -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run UI smoke test**

Run:

```bash
.venv/bin/python run_app.py
```

Expected: the app launches, parses sample rows, and can fetch a captcha when network access is available.

- [ ] **Step 3: Check Git ignore safety**

Run:

```bash
git status --short --ignored
```

Expected: `results/` and `.superpowers/` are ignored; source files and docs are tracked or ready to commit.

- [ ] **Step 4: Commit final docs if changed**

```bash
git add README.md docs/项目使用说明.md
git commit -m "Update app usage docs"
```

Skip this commit only if no docs changed.

## Self-Review

- Spec coverage: The plan covers batch parsing, automatic personal/company detection, sequential queue, manual captcha pause, PNG output, captcha deletion, error statuses, and local Mac-only scope.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: `QueryItem`, `CaptchaChallenge`, and `SearchResult` names are consistent across tasks.
