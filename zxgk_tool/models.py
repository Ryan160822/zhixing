from __future__ import annotations

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
    result_rows: list[dict] = field(default_factory=list)
