from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

from .models import QueryItem
from .renderer import safe_filename_part


BASE_URL = "https://zxgk.court.gov.cn/zhzxgk/"
CAPTCHA_RE = re.compile(r'id="captchaId"\s+name="captchaId"\s+type="hidden"\s+value="([^"]+)"')


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
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            }
        )

    def fetch_captcha(self, captcha_dir: Path, label: str) -> CaptchaChallenge:
        response = self.session.get(BASE_URL, timeout=30)
        response.raise_for_status()
        captcha_id = extract_captcha_id(response.text)
        if not captcha_id:
            raise RuntimeError("没有找到验证码，请稍后重试")

        captcha_dir.mkdir(parents=True, exist_ok=True)
        image_path = captcha_dir / f"验证码_{safe_filename_part(label)}_{captcha_id}.png"
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
