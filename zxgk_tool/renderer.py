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
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
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
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", value.strip())
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
    for i, (label, value) in enumerate(
        [
            ("被执行人姓名/名称:", item.name),
            ("身份证号码/组织机构代码:", card_label),
            ("执行法院范围:", COURT_SCOPE),
        ]
    ):
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
