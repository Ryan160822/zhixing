# 桌面 APP 化 + 验证码自动识别 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `zxgk_tool` 加本地验证码自动识别（ddddocr，识错自动重试 5 次后回退人工），把结果改为手动保存，并打包成自包含的 macOS `.app`。

**Architecture:** OCR 与重试决策抽成可单测的纯逻辑（`ocr.py`）；可写路径抽到 `paths.py`；`app.py` 只做 GUI 接线，复用现有 events/worker 机制。OCR 依赖用独立 Python 3.12 venv 装并由 PyInstaller 打包，开发机的 3.14 不受影响——dev 环境装不上 ddddocr 时自动降级为人工模式。

**Tech Stack:** Python, tkinter, Pillow, requests, ddddocr(+onnxruntime), PyInstaller。测试用 unittest。

设计文档：`docs/superpowers/specs/2026-06-30-desktop-app-ocr-packaging-design.md`

---

## 文件结构

- 新建 `zxgk_tool/ocr.py` — 验证码识别 + 自动重试决策（纯逻辑，可单测）
- 新建 `zxgk_tool/paths.py` — 打包态/开发态的可写目录
- 修改 `zxgk_tool/app.py` — 自动识别接线、自动开关、保存按钮、临时结果目录
- 修改 `tests/test_app.py` — 更新 make_app 助手 + 新增自动重试测试
- 新建 `tests/test_ocr.py`、`tests/test_paths.py`
- 新建 `requirements-build.txt`、`zxgk_tool.spec`、`build_app.sh`
- 修改 `README.md`

---

## Task 1: OCR 识别模块 `ocr.py`

**Files:**
- Create: `zxgk_tool/ocr.py`
- Test: `tests/test_ocr.py`

- [ ] **Step 1: 写失败测试（清洗 + 懒加载 + 注入分类器）**

`tests/test_ocr.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from zxgk_tool.ocr import CaptchaSolver, clean_captcha_text


class FakeClassifier:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def classification(self, _data: bytes) -> str:
        self.calls += 1
        return self.value


class CleanCaptchaTextTest(unittest.TestCase):
    def test_strips_symbols_and_spaces(self) -> None:
        self.assertEqual(clean_captcha_text("  a b#3d! "), "ab3d")

    def test_keeps_letters_and_digits(self) -> None:
        self.assertEqual(clean_captcha_text("X9y2"), "X9y2")


class CaptchaSolverTest(unittest.TestCase):
    def test_predict_uses_classifier_and_cleans(self) -> None:
        fake = FakeClassifier(" a1 b2 ")
        solver = CaptchaSolver(classifier_factory=lambda: fake)
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "c.png"
            img.write_bytes(b"bytes")
            self.assertEqual(solver.predict(img), "a1b2")
        self.assertEqual(fake.calls, 1)

    def test_classifier_is_lazy(self) -> None:
        created = []

        def factory():
            created.append(1)
            return FakeClassifier("ab12")

        solver = CaptchaSolver(classifier_factory=factory)
        self.assertEqual(created, [])  # 构造时不加载模型
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "c.png"
            img.write_bytes(b"bytes")
            solver.predict(img)
        self.assertEqual(created, [1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_ocr.py -v`
Expected: FAIL（`ModuleNotFoundError: zxgk_tool.ocr`）

- [ ] **Step 3: 写最小实现**

`zxgk_tool/ocr.py`:

```python
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

MAX_AUTO_ATTEMPTS = 5

AUTO_SUBMIT = "auto_submit"
MANUAL = "manual"

_ALNUM = re.compile(r"[^A-Za-z0-9]")


def clean_captcha_text(raw: str) -> str:
    return _ALNUM.sub("", raw or "")


def _default_classifier():
    import ddddocr  # 仅在打包态/装了 ddddocr 时可用

    return ddddocr.DdddOcr(show_ad=False)


class CaptchaSolver:
    def __init__(self, classifier_factory: Callable[[], object] | None = None) -> None:
        self._factory = classifier_factory or _default_classifier
        self._classifier = None

    def _get(self):
        if self._classifier is None:
            self._classifier = self._factory()
        return self._classifier

    def predict(self, image_path: Path) -> str:
        raw = self._get().classification(image_path.read_bytes())
        return clean_captcha_text(raw)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_ocr.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add zxgk_tool/ocr.py tests/test_ocr.py
git commit -m "Add CaptchaSolver with lazy ddddocr and text cleaning"
```

---

## Task 2: 自动重试决策（纯函数，加到 `ocr.py`）

**Files:**
- Modify: `zxgk_tool/ocr.py`
- Test: `tests/test_ocr.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_ocr.py` 顶部 import 改为：

```python
from zxgk_tool.ocr import (
    AUTO_SUBMIT,
    MANUAL,
    CaptchaSolver,
    clean_captcha_text,
    decide_captcha_action,
    should_auto_attempt,
)
```

并追加：

```python
class DecisionTest(unittest.TestCase):
    def test_auto_on_with_prediction_submits(self) -> None:
        self.assertEqual(decide_captcha_action(True, "ab12", 0), AUTO_SUBMIT)

    def test_auto_on_without_prediction_is_manual(self) -> None:
        self.assertEqual(decide_captcha_action(True, None, 0), MANUAL)

    def test_auto_off_is_manual(self) -> None:
        self.assertEqual(decide_captcha_action(False, "ab12", 0), MANUAL)

    def test_attempts_exhausted_is_manual(self) -> None:
        self.assertEqual(decide_captcha_action(True, "ab12", 5, max_attempts=5), MANUAL)

    def test_should_auto_attempt_boundary(self) -> None:
        self.assertTrue(should_auto_attempt(True, 4, 5))
        self.assertFalse(should_auto_attempt(True, 5, 5))
        self.assertFalse(should_auto_attempt(False, 0, 5))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_ocr.py::DecisionTest -v`
Expected: FAIL（`ImportError: cannot import name 'decide_captcha_action'`）

- [ ] **Step 3: 在 `ocr.py` 追加实现（放在 `CaptchaSolver` 之前）**

```python
def should_auto_attempt(auto_enabled: bool, attempts: int, max_attempts: int = MAX_AUTO_ATTEMPTS) -> bool:
    return auto_enabled and attempts < max_attempts


def decide_captcha_action(
    auto_enabled: bool,
    predicted: str | None,
    attempts: int,
    max_attempts: int = MAX_AUTO_ATTEMPTS,
) -> str:
    if should_auto_attempt(auto_enabled, attempts, max_attempts) and predicted:
        return AUTO_SUBMIT
    return MANUAL
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_ocr.py -v`
Expected: PASS（全部通过）

- [ ] **Step 5: 提交**

```bash
git add zxgk_tool/ocr.py tests/test_ocr.py
git commit -m "Add captcha auto-retry decision helpers"
```

---

## Task 3: 可写路径模块 `paths.py`

**Files:**
- Create: `zxgk_tool/paths.py`
- Test: `tests/test_paths.py`

- [ ] **Step 1: 写失败测试**

`tests/test_paths.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zxgk_tool import paths


class PathsTest(unittest.TestCase):
    def test_captcha_dir_dev_is_project_runtime(self) -> None:
        with patch.object(paths, "is_frozen", return_value=False):
            self.assertEqual(paths.captcha_dir(), paths.PROJECT_ROOT / ".runtime" / "captchas")

    def test_captcha_dir_frozen_is_tempdir(self) -> None:
        with patch.object(paths, "is_frozen", return_value=True):
            expected = Path(tempfile.gettempdir()) / "zxgk_captchas"
            self.assertEqual(paths.captcha_dir(), expected)

    def test_temp_results_dir_exists_after_call(self) -> None:
        d = paths.temp_results_dir()
        self.assertTrue(d.exists())
        self.assertEqual(d.name, "zxgk_results")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: FAIL（`ModuleNotFoundError: zxgk_tool.paths`）

- [ ] **Step 3: 写实现**

`zxgk_tool/paths.py`:

```python
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def captcha_dir() -> Path:
    if is_frozen():
        return Path(tempfile.gettempdir()) / "zxgk_captchas"
    return PROJECT_ROOT / ".runtime" / "captchas"


def temp_results_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "zxgk_results"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add zxgk_tool/paths.py tests/test_paths.py
git commit -m "Add paths module for frozen/dev writable dirs"
```

---

## Task 4: 接线到 `app.py`（自动识别 + 保存 + 临时目录）

**Files:**
- Modify: `zxgk_tool/app.py`
- Modify: `tests/test_app.py`

### 4a. 先改测试助手并加自动重试测试（TDD）

- [ ] **Step 1: 更新 `tests/test_app.py` 的 make_app 与 Dummy，并加新测试**

在 `tests/test_app.py` 顶部 import 后追加：

```python
class DummyBoolVar:
    def __init__(self, value: bool = False) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value
```

把 `make_app` 改为（在原有基础上补字段）：

```python
    def make_app(self, items: list[QueryItem], auto: bool = False) -> ZxgkApp:
        app = ZxgkApp.__new__(ZxgkApp)
        app.items = items
        app.current_item = items[0]
        app.current_captcha = None
        app.current_predicted = None
        app.batch_output_path = None
        app.busy = True
        app.auto_var = DummyBoolVar(auto)
        app.auto_attempts = 0
        app.output_paths = []
        app.status_var = DummyVar()
        app.current_label_var = DummyVar()
        app.captcha_entry = DummyEntry()
        app.captcha_label = DummyLabel()
        app.save_button = DummyLabel()
        app._render_queue = lambda: None
        app._update_save_button = lambda: None
        return app
```

在文件末尾（`if __name__` 之前）追加自动重试测试：

```python
class AutoSolveTest(unittest.TestCase):
    def make_app(self, auto: bool, attempts: int):
        app = ZxgkApp.__new__(ZxgkApp)
        items = [QueryItem(1, "x", "company", "某公司")]
        app.items = items
        app.current_item = items[0]
        app.current_captcha = None
        app.current_predicted = "ab12"
        app.batch_output_path = None
        app.busy = True
        app.auto_var = DummyBoolVar(auto)
        app.auto_attempts = attempts
        app.output_paths = []
        app.status_var = DummyVar()
        app.current_label_var = DummyVar()
        app.captcha_entry = DummyEntry()
        app.captcha_label = DummyLabel()
        app.save_button = DummyLabel()
        app._render_queue = lambda: None
        app._update_save_button = lambda: None
        return app, items

    def test_auto_error_refetches_new_captcha(self) -> None:
        app, items = self.make_app(auto=True, attempts=2)
        fetched = []
        app._fetch_captcha_for = lambda item: fetched.append(item)
        with tempfile.TemporaryDirectory() as d:
            cap_path = Path(d) / "c.png"
            cap_path.write_bytes(b"x")
            captcha = CaptchaChallenge("c1", cap_path)
            app.current_captcha = captcha
            app._handle_search_done(items[0], captcha, SearchResult([], 0, "验证码错误或已过期"), "ab12")
            self.assertEqual(fetched, [items[0]])
            self.assertIsNone(app.current_captcha)
            self.assertFalse(cap_path.exists())

    def test_auto_error_falls_back_to_manual_after_max(self) -> None:
        app, items = self.make_app(auto=True, attempts=5)
        app._fetch_captcha_for = lambda item: self.fail("should not refetch after max")
        with tempfile.TemporaryDirectory() as d:
            cap_path = Path(d) / "c.png"
            cap_path.write_bytes(b"x")
            captcha = CaptchaChallenge("c1", cap_path)
            app.current_captcha = captcha
            app._handle_search_done(items[0], captcha, SearchResult([], 0, "验证码错误或已过期"), "ab12")
            self.assertTrue(app.captcha_entry.focused)
            self.assertTrue(cap_path.exists())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_app.py -v`
Expected: FAIL（`_handle_search_done` 旧逻辑无自动分支；新断言失败 / AttributeError）

### 4b. 改 `app.py`

- [ ] **Step 3: 改导入与常量（文件顶部）**

把 `zxgk_tool/app.py` 顶部的导入区改为加入：

```python
import shutil
from tkinter import filedialog, messagebox, ttk
```

并在 `from .parser import parse_batch_lines` 附近加：

```python
from . import paths
from .ocr import (
    AUTO_SUBMIT,
    MAX_AUTO_ATTEMPTS,
    CaptchaSolver,
    decide_captcha_action,
    should_auto_attempt,
)
```

删除写死的常量（`PROJECT_ROOT`、`RESULTS_DIR`、`CAPTCHA_DIR` 三行），改用 `paths` 模块。

- [ ] **Step 4: 在 `__init__` 增加状态字段**

在 `self.busy = False` 之后插入：

```python
        self.solver = CaptchaSolver()
        self.auto_var = tk.BooleanVar(value=True)
        self.auto_attempts = 0
        self.output_paths: list[Path] = []
        self.current_predicted: str | None = None
```

- [ ] **Step 5: 在 `_build_ui` 加「自动识别」开关与「保存结果」按钮**

在 captcha_box 的 `captcha_actions` 之后追加：

```python
        self.auto_check = ttk.Checkbutton(captcha_box, text="自动识别验证码", variable=self.auto_var)
        self.auto_check.grid(row=4, column=0, sticky="w", pady=(8, 0))
```

在 right 面板 status 标签那一行（`row=2`）之后追加：

```python
        self.save_button = ttk.Button(right, text="保存结果", command=self.save_results, state="disabled")
        self.save_button.grid(row=3, column=0, sticky="w", pady=(8, 0))
```

- [ ] **Step 6: `start_queue` 重置状态**

把 `start_queue` 中 `self.batch_output_path = None` 之后补：

```python
        self.auto_attempts = 0
        self.output_paths = []
        self._update_save_button()
```

- [ ] **Step 7: `_fetch_captcha_worker` 顺带跑 OCR**

整段替换为：

```python
    def _fetch_captcha_worker(self, item: QueryItem) -> None:
        try:
            challenge = self.client.fetch_captcha(paths.captcha_dir(), item.name)
            predicted = None
            if self.auto_var.get():
                try:
                    predicted = self.solver.predict(challenge.image_path)
                except Exception:
                    predicted = None
            self.events.put(("captcha_ready", (item, challenge, predicted)))
        except Exception as exc:
            self.events.put(("error", (item, str(exc))))
```

- [ ] **Step 8: `_process_events` 解包 3 元组**

把 `captcha_ready` 分支改为：

```python
                if event == "captcha_ready":
                    item, challenge, predicted = payload
                    self._handle_captcha_ready(item, challenge, predicted)
```

- [ ] **Step 9: 替换 `_handle_captcha_ready`（带自动提交）**

```python
    def _handle_captcha_ready(self, item: QueryItem, challenge: CaptchaChallenge, predicted: str | None) -> None:
        self.busy = False
        item.status = STATUS_WAITING_CAPTCHA
        self.current_item = item
        self.current_captcha = challenge
        self.current_predicted = predicted
        self.current_label_var.set(f"当前：{item.name}")
        self._show_captcha(challenge.image_path)
        self.captcha_entry.delete(0, tk.END)
        self._render_queue()

        if decide_captcha_action(self.auto_var.get(), predicted, self.auto_attempts) == AUTO_SUBMIT:
            self.auto_attempts += 1
            self.status_var.set(f"自动识别验证码（第 {self.auto_attempts} 次）：{predicted}")
            self._submit_with_captcha(item, challenge, predicted)
            return

        self.captcha_entry.focus_set()
        self.status_var.set("请输入验证码，按 Enter 提交")
```

- [ ] **Step 10: 改 `_handle_search_done` 的错误分支与成功分支**

错误分支（`if result.error:` 块）替换为：

```python
        if result.error:
            item.status = STATUS_CAPTCHA_ERROR
            item.error = result.error
            self.current_item = item
            self.current_captcha = captcha
            self._render_queue()
            self.captcha_entry.delete(0, tk.END)
            if should_auto_attempt(self.auto_var.get(), self.auto_attempts):
                self.status_var.set(f"验证码识别错误，自动换一张重试（已 {self.auto_attempts} 次）")
                self._delete_captcha(captcha)
                self.current_captcha = None
                self._fetch_captcha_for(item)
                return
            self.status_var.set(result.error)
            self.captcha_entry.focus_set()
            return
```

成功分支里，把渲染目录改为临时目录并记录输出。将这几行：

```python
        out = None
        if not self._uses_batch_output():
            out = render_result_png(item, result.rows, RESULTS_DIR, date.today().isoformat())
```

替换为：

```python
        out = None
        if not self._uses_batch_output():
            out = render_result_png(item, result.rows, paths.temp_results_dir(), date.today().isoformat())
            self.output_paths.append(out)
            self._update_save_button()
        self.auto_attempts = 0
```

- [ ] **Step 11: `_finish_batch_output_if_ready` 改临时目录并记录输出**

把 `out = render_batch_result_png(self.items, RESULTS_DIR, date.today().isoformat())` 改为：

```python
        out = render_batch_result_png(self.items, paths.temp_results_dir(), date.today().isoformat())
```

并在 `self.batch_output_path = out` 之后追加：

```python
        self.output_paths = [out]
        self._update_save_button()
```

- [ ] **Step 12: 新增 `_update_save_button` 与 `save_results` 方法**

在类中（`main()` 之前）追加：

```python
    def _update_save_button(self) -> None:
        self.save_button.configure(state="normal" if self.output_paths else "disabled")

    def save_results(self) -> None:
        if not self.output_paths:
            messagebox.showinfo("没有结果", "还没有可保存的结果。")
            return
        if len(self.output_paths) == 1:
            src = self.output_paths[0]
            dest = filedialog.asksaveasfilename(
                title="保存结果",
                defaultextension=".png",
                initialfile=src.name,
                filetypes=[("PNG 图片", "*.png")],
            )
            if not dest:
                return
            shutil.copyfile(src, dest)
            self.status_var.set(f"已保存：{dest}")
            return
        folder = filedialog.askdirectory(title="选择保存文件夹")
        if not folder:
            return
        for src in self.output_paths:
            shutil.copyfile(src, Path(folder) / src.name)
        self.status_var.set(f"已保存 {len(self.output_paths)} 个文件到：{folder}")
```

- [ ] **Step 13: 跑全部测试确认通过**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS（含旧测试、新 AutoSolveTest、ocr、paths 全绿）

- [ ] **Step 14: 提交**

```bash
git add zxgk_tool/app.py tests/test_app.py
git commit -m "Wire OCR auto-solve, manual save, and temp dirs into app"
```

---

## Task 5: 构建依赖清单 `requirements-build.txt`

**Files:**
- Create: `requirements-build.txt`

> ddddocr 在 Python 3.14 装不上，所以不放进主 `requirements.txt`，单独用一个构建清单（仅 `.venv-build` 用）。

- [ ] **Step 1: 创建文件**

`requirements-build.txt`:

```text
pillow
requests
ddddocr
pyinstaller
```

- [ ] **Step 2: 提交**

```bash
git add requirements-build.txt
git commit -m "Add build requirements for packaging with ddddocr"
```

---

## Task 6: PyInstaller 规格与构建脚本

**Files:**
- Create: `zxgk_tool.spec`
- Create: `build_app.sh`

- [ ] **Step 1: 写 `zxgk_tool.spec`**

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for _pkg in ("ddddocr", "onnxruntime"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="被执行人查询助手",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="被执行人查询助手",
)
app = BUNDLE(
    coll,
    name="被执行人查询助手.app",
    icon=None,
    bundle_identifier="com.zxgk.tool",
)
```

- [ ] **Step 2: 写 `build_app.sh`**

```bash
#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYBIN="${PYBIN:-/opt/homebrew/bin/python3.12}"
if [ ! -x "$PYBIN" ]; then
  echo "找不到 Python 3.12：$PYBIN"
  echo "请先安装：brew install python@3.12"
  exit 1
fi

if [ ! -x ".venv-build/bin/python" ]; then
  "$PYBIN" -m venv .venv-build
fi

.venv-build/bin/python -m pip install --upgrade pip
.venv-build/bin/python -m pip install -r requirements-build.txt
.venv-build/bin/python -m PyInstaller --noconfirm zxgk_tool.spec

echo ""
echo "完成：dist/被执行人查询助手.app"
echo "首次打开若被拦截，右键 → 打开，或运行："
echo "  xattr -dr com.apple.quarantine 'dist/被执行人查询助手.app'"
```

- [ ] **Step 3: 赋可执行权限并加入忽略**

```bash
chmod +x build_app.sh
printf '\n.venv-build/\nbuild/\ndist/\n' >> .gitignore
```

- [ ] **Step 4: 提交**

```bash
git add zxgk_tool.spec build_app.sh .gitignore
git commit -m "Add PyInstaller spec and macOS build script"
```

---

## Task 7: 打包冒烟测试 + README + 收尾

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 准备 Python 3.12（若未装）**

Run: `/opt/homebrew/bin/python3.12 --version || brew install python@3.12`
Expected: 输出 `Python 3.12.x`

- [ ] **Step 2: 构建 .app**

Run: `./build_app.sh`
Expected: 末尾打印 `完成：dist/被执行人查询助手.app`，`dist/被执行人查询助手.app` 存在

- [ ] **Step 3: 手动冒烟测试**

```bash
xattr -dr com.apple.quarantine "dist/被执行人查询助手.app"
open "dist/被执行人查询助手.app"
```

人工验证（勾上「自动识别验证码」默认开）：
1. 粘贴 1 条企业名单 → 点「开始查询」；
2. 观察验证码是否被自动识别并提交（错了会自动换图重试，状态栏显示「第 N 次」）；
3. 查询完成后点「保存结果」→ 选个位置 → 确认 PNG 落到该位置。

若 OCR 连续 5 次失败，应自动显示验证码图并让你手动输入——也算通过。

- [ ] **Step 4: 更新 README**

在 `README.md` 的「使用方式」后补一节：

```markdown
## 打包成 macOS APP

需要 Python 3.12（`brew install python@3.12`），然后：

\`\`\`bash
./build_app.sh
\`\`\`

产物在 `dist/被执行人查询助手.app`，双击即可，使用者无需安装 Python。

首次打开若提示「来自身份不明的开发者」：右键 →「打开」，或运行：

\`\`\`bash
xattr -dr com.apple.quarantine "dist/被执行人查询助手.app"
\`\`\`

验证码默认本地自动识别（ddddocr），识别错误会自动换图重试，连续 5 次失败回退人工输入。
可在界面取消勾选「自动识别验证码」改为纯人工。

查询结果不再自动保存到目录，查完点「保存结果」自行选择保存位置。
```

> 注：上面代码块里的 `\`\`\`` 写进 README 时是正常的三反引号。

同时把「输出目录」一节中“结果 PNG 保存在 results/”的描述改为“查完点『保存结果』自行选择保存位置”。

- [ ] **Step 5: 跑一遍测试确保没回归**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS（全绿）

- [ ] **Step 6: 提交**

```bash
git add README.md
git commit -m "Document macOS app build and captcha auto-solve"
```

---

## 自查记录

- **spec 覆盖**：自动识别(Task1-2,4)、人工兜底(Task2,4)、打包.app(Task6-7)、可写路径(Task3)、结果手动保存(Task4)、3.14 降级(Task1 懒加载 + Task4 try/except + Task5 独立构建清单)、Gatekeeper(Task6-7) 均有对应任务。
- **占位符**：无 TODO/TBD，每个改动都给了完整代码。
- **类型/命名一致**：`AUTO_SUBMIT`/`MANUAL`/`MAX_AUTO_ATTEMPTS`/`decide_captcha_action`/`should_auto_attempt`/`CaptchaSolver.predict`/`paths.captcha_dir`/`paths.temp_results_dir`/`output_paths`/`auto_attempts`/`auto_var`/`_update_save_button`/`save_results` 在 Task 1-4 中前后一致。
```
