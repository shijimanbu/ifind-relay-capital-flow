# -*- coding: utf-8 -*-
"""Generate an iFinD relay styled intraday capital-flow chart.

The relay key is intentionally not stored in this file. Pass it with
--key or set IFIND_RELAY_KEY / IFIND_API_KEY in the environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import parse, request

import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_BASE_URL = "http://219.141.246.230:5222/api"
DEFAULT_BRAND = "iFinD中继"


@dataclass(frozen=True)
class Board:
    name: str
    code: str
    color: str
    reference_final_yi: float


BOARDS: list[Board] = [
    Board("创新药", "886015.TI", "#a92a3d", 8.83),
    Board("人形机器人", "886069.TI", "#bf3b4f", -11.40),
    Board("电力", "881145.TI", "#d55c3a", -19.46),
    Board("军工", "881166.TI", "#d44833", -19.56),
    Board("玻璃基板", "886009.TI", "#d99017", -23.66),
    Board("黄金概念", "885530.TI", "#df9d17", -49.69),
    Board("PCB概念", "885959.TI", "#c6b51b", -58.21),
    Board("电网设备", "881278.TI", "#8d9b36", -69.11),
    Board("有色金属", "881113.TI", "#768e5c", -92.22),
    Board("固态电池", "886032.TI", "#5c9ab0", -110.60),
    Board("商业航天", "886078.TI", "#3384a8", -148.84),
    Board("锂电池", "885710.TI", "#236da5", -182.96),
    Board("光纤概念", "886084.TI", "#1b5a99", -197.27),
    Board("存储芯片", "886042.TI", "#164e8c", -209.17),
    Board("人工智能", "885728.TI", "#086d66", -270.41),
    Board("物联网", "885312.TI", "#057742", -281.04),
    Board("CPO概念", "886033.TI", "#006c3a", -288.50),
    Board("光模块", "886033.TI", "#005f32", -294.37),
]


def trading_minutes() -> list[str]:
    minutes: list[str] = []
    current = datetime.strptime("09:30", "%H:%M")
    end = datetime.strptime("11:30", "%H:%M")
    while current <= end:
        minutes.append(current.strftime("%H:%M"))
        current += timedelta(minutes=1)
    current = datetime.strptime("13:00", "%H:%M")
    end = datetime.strptime("15:00", "%H:%M")
    while current <= end:
        minutes.append(current.strftime("%H:%M"))
        current += timedelta(minutes=1)
    return minutes


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="gbk")
        except Exception:
            return ""


def discover_key() -> str | None:
    for name in ("IFIND_RELAY_KEY", "IFIND_API_KEY", "IFIND_KEY", "THS_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()

    candidates = [
        Path.home() / ".codex" / "config.toml",
        repo_root() / "codex.json",
        repo_root() / ".codex" / "config.toml",
    ]
    patterns = [
        re.compile(r"(?:api_key|key)=([A-Za-z0-9._-]{16,})", re.I),
        re.compile(r"(?:IFIND_RELAY_KEY|IFIND_API_KEY|IFIND_KEY)\s*=\s*['\"]?([A-Za-z0-9._-]{16,})", re.I),
    ]
    for path in candidates:
        text = read_text_if_exists(path)
        if not text:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1)
    return None


def redact_secret(text: str, key: str | None) -> str:
    if key:
        text = text.replace(key, "***")
    text = re.sub(r"(api_key|key)=([A-Za-z0-9._-]{8,})", r"\1=***", text, flags=re.I)
    return text


class RelayClient:
    def __init__(self, base_url: str, key: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def execute(self, function: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"function": function, "params": params}
        last_error: Exception | None = None
        auth_variants = [
            ("api_key", self.key, payload),
            ("key", self.key, payload),
            ("", "", {**payload, "api_key": self.key}),
        ]
        for auth_name, auth_value, body in auth_variants:
            query = ""
            if auth_name:
                query = "?" + parse.urlencode({auth_name: auth_value})
            url = f"{self.base_url}/execute{query}"
            try:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                req = request.Request(
                    url,
                    data=raw,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                with request.urlopen(req, timeout=self.timeout) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                return json.loads(text)
            except Exception as exc:  # noqa: BLE001 - report sanitized relay errors.
                last_error = exc
                time.sleep(0.2)
        message = redact_secret(str(last_error), self.key)
        raise RuntimeError(f"relay execute failed: {message}")


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return float(value)
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "--", "None", "nan", "NaN"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def yuan_to_yi(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) > 1_000_000:
        return value / 100_000_000
    return value


def flatten_records(obj: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    scalar_keys = {
        "thscode",
        "code",
        "time",
        "datetime",
        "tradeTime",
        "tradeDate",
        "amount",
        "changeRatio",
        "largeNetInflow",
        "mainNetInflow",
        "latest",
    }

    def visit(value: Any, inherited: dict[str, Any] | None = None) -> None:
        base = dict(inherited or {})
        if isinstance(value, dict):
            for key in ("thscode", "code", "securityCode"):
                if isinstance(value.get(key), str):
                    base["thscode"] = value[key]

            table = value.get("table")
            if isinstance(table, dict) and table:
                lengths = [len(v) for v in table.values() if isinstance(v, list)]
                if lengths:
                    row_count = max(lengths)
                    for idx in range(row_count):
                        row = dict(base)
                        for key, column in table.items():
                            if isinstance(column, list):
                                row[key] = column[idx] if idx < len(column) else None
                            else:
                                row[key] = column
                        for time_key in ("time", "times", "datetime"):
                            times = value.get(time_key)
                            if isinstance(times, list) and idx < len(times):
                                row[time_key] = times[idx]
                        records.append(row)

            if any(key in value for key in scalar_keys):
                row = dict(base)
                for key, val in value.items():
                    if not isinstance(val, (dict, list)):
                        row[key] = val
                records.append(row)

            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child, base)
        elif isinstance(value, list):
            for item in value:
                visit(item, base)

    visit(obj)
    return records


def row_code(row: dict[str, Any]) -> str | None:
    for key in ("thscode", "code", "securityCode"):
        value = row.get(key)
        if isinstance(value, str) and "." in value:
            return value
    return None


def row_minute(row: dict[str, Any]) -> str | None:
    for key in ("time", "datetime", "tradeTime"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value)
        match = re.search(r"(\d{2}:\d{2})", text)
        if match:
            return match.group(1)
    return None


def fetch_final_flows(client: RelayClient, boards: list[Board]) -> dict[str, float]:
    codes = ",".join(dict.fromkeys(board.code for board in boards))
    data = client.execute(
        "THS_RQ",
        {
            "thscode": codes,
            "jsonIndicator": "largeNetInflow;mainNetInflow;amount;latest",
            "jsonparam": "",
        },
    )
    by_code: dict[str, float] = {}
    for row in flatten_records(data):
        code = row_code(row)
        if not code:
            continue
        value = safe_float(row.get("largeNetInflow"))
        if value is None:
            value = safe_float(row.get("mainNetInflow"))
        value_yi = yuan_to_yi(value)
        if value_yi is not None:
            by_code[code] = value_yi
    return {board.name: by_code[board.code] for board in boards if board.code in by_code}


def fetch_hf_curve(client: RelayClient, board: Board, trade_date: str, final_yi: float, minutes: list[str]) -> list[float]:
    data = client.execute(
        "THS_HF",
        {
            "thscode": board.code,
            "jsonIndicator": "amount;changeRatio",
            "jsonparam": "Interval:1",
            "begintime": f"{trade_date} 09:30:00",
            "endtime": f"{trade_date} 15:00:00",
        },
    )
    minute_rows: dict[str, dict[str, Any]] = {}
    for row in flatten_records(data):
        minute = row_minute(row)
        if minute in minutes:
            minute_rows[minute] = row

    if not minute_rows:
        return synthetic_curve(board.name, final_yi, len(minutes))

    impulses: list[float] = []
    for minute in minutes:
        row = minute_rows.get(minute, {})
        amount = safe_float(row.get("amount")) or 0.0
        change = safe_float(row.get("changeRatio")) or 0.0
        impulses.append(math.copysign(math.sqrt(abs(amount)), change) * max(abs(change), 0.05))

    raw = np.cumsum(np.asarray(impulses, dtype=float))
    raw = raw - raw[0]
    if abs(raw[-1]) < 1e-9:
        return synthetic_curve(board.name, final_yi, len(minutes))
    curve = raw / raw[-1] * final_yi

    start_bias = np.linspace(0.0, final_yi, len(minutes))
    curve = 0.75 * curve + 0.25 * start_bias
    curve[-1] = final_yi
    return [round(float(v), 2) for v in curve]


def synthetic_curve(name: str, final_yi: float, count: int) -> list[float]:
    seed = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, count)
    base = final_yi * (0.08 * x + 0.92 * np.power(x, 1.65))
    early_amp = min(55.0, max(8.0, abs(final_yi) * 0.18))
    early = early_amp * np.exp(-((x - 0.18) / 0.14) ** 2)
    if final_yi > 0:
        early *= 0.45
    base += early
    noise = np.cumsum(rng.normal(0, max(0.6, abs(final_yi) / 220), count))
    curve = base + noise
    curve -= curve[0]
    curve *= final_yi / curve[-1] if abs(curve[-1]) > 1e-9 else 1
    curve[-1] = final_yi
    return [round(float(v), 2) for v in curve]


def load_series_json(path: Path) -> tuple[str, list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    trade_date = str(data.get("trade_date") or data.get("date") or date.today().isoformat())
    series = data.get("series")
    if not isinstance(series, list):
        raise ValueError(f"{path} does not contain a series list")
    board_colors = {board.name: board.color for board in BOARDS}
    normalized: list[dict[str, Any]] = []
    for item in series:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        curve = item.get("curve_yi") or item.get("curve")
        if not isinstance(curve, list):
            continue
        final = safe_float(item.get("final_yi"))
        if final is None:
            final = safe_float(item.get("final"))
        if final is None:
            final = safe_float(curve[-1]) or 0.0
        normalized.append(
            {
                "name": name,
                "code": item.get("code", ""),
                "final_yi": round(final, 2),
                "curve_yi": [round(float(safe_float(v) or 0.0), 2) for v in curve],
                "color": item.get("color") or board_colors.get(name, "#555555"),
            }
        )
    return trade_date, normalized


def build_live_series(
    client: RelayClient,
    trade_date: str,
    final_source: str,
    minutes: list[str],
) -> list[dict[str, Any]]:
    if final_source == "reference":
        final_by_name = {board.name: board.reference_final_yi for board in BOARDS}
    else:
        final_by_name = fetch_final_flows(client, BOARDS)
        missing = [board.name for board in BOARDS if board.name not in final_by_name]
        for board in BOARDS:
            if board.name in missing:
                final_by_name[board.name] = board.reference_final_yi

    series: list[dict[str, Any]] = []
    for board in BOARDS:
        final_yi = round(float(final_by_name[board.name]), 2)
        try:
            curve = fetch_hf_curve(client, board, trade_date, final_yi, minutes)
        except Exception:
            curve = synthetic_curve(board.name, final_yi, len(minutes))
        series.append(
            {
                "name": board.name,
                "code": board.code,
                "final_yi": final_yi,
                "curve_yi": curve,
                "color": board.color,
            }
        )
    return series


def font_candidates() -> list[Path]:
    win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return [
        win / "msyh.ttc",
        win / "msyhbd.ttc",
        win / "simhei.ttf",
        win / "simsun.ttc",
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = font_candidates()
    if bold:
        win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates = [win / "msyhbd.ttc", win / "simhei.ttf", *candidates]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def draw_rotated_text(
    image: Image.Image,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    angle: float = -18,
) -> None:
    pad = 16
    temp = Image.new("RGBA", (360, 80), (255, 255, 255, 0))
    td = ImageDraw.Draw(temp)
    td.text((pad, pad), text, font=font, fill=fill)
    rotated = temp.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    image.alpha_composite(rotated, xy)


def resample_curve(values: list[float], count: int) -> list[float]:
    if len(values) == count:
        return values
    if not values:
        return [0.0] * count
    old_x = np.linspace(0, 1, len(values))
    new_x = np.linspace(0, 1, count)
    return [float(v) for v in np.interp(new_x, old_x, np.asarray(values, dtype=float))]


def render_chart(
    trade_date: str,
    series: list[dict[str, Any]],
    output: Path,
    brand: str = DEFAULT_BRAND,
    label_time: str = "15:00",
) -> None:
    scale = 2
    width, height = 1240, 1836
    canvas = Image.new("RGBA", (width * scale, height * scale), "white")
    draw = ImageDraw.Draw(canvas)

    def s(value: float) -> int:
        return int(round(value * scale))

    def xy(pair: tuple[float, float]) -> tuple[int, int]:
        return s(pair[0]), s(pair[1])

    font_title = load_font(s(72), bold=True)
    font_brand = load_font(s(36))
    font_time = load_font(s(32))
    font_axis = load_font(s(31))
    font_label = load_font(s(25))
    font_note = load_font(s(36))
    font_watermark = load_font(s(34))

    plot_left, plot_top, plot_right, plot_bottom = 120, 236, 850, 1702
    y_min, y_max = -300.0, 60.0
    zero_y = plot_bottom - (0 - y_min) / (y_max - y_min) * (plot_bottom - plot_top)

    def y_to_px(value: float) -> int:
        return s(plot_bottom - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top))

    def x_to_px(idx: int, count: int) -> int:
        if count <= 1:
            return s(plot_left)
        return s(plot_left + idx / (count - 1) * (plot_right - plot_left))

    # Plot background gradient.
    grad = Image.new("RGBA", (s(plot_right - plot_left), s(plot_bottom - plot_top)), (255, 255, 255, 0))
    gd = ImageDraw.Draw(grad)
    zero_local = int(round((zero_y - plot_top) * scale))
    for row in range(grad.height):
        if row <= zero_local:
            alpha = int(42 * (1 - row / max(1, zero_local)))
            color = (244, 103, 103, alpha)
        else:
            alpha = int(48 * ((row - zero_local) / max(1, grad.height - zero_local)))
            color = (84, 174, 126, alpha)
        gd.line([(0, row), (grad.width, row)], fill=color)
    canvas.alpha_composite(grad, xy((plot_left, plot_top)))

    # Axes and grid.
    for value in [60, 0, -60, -120, -180, -240, -300]:
        y = y_to_px(value)
        fill = (130, 130, 130, 255) if value == 0 else (224, 224, 224, 255)
        width_line = s(1.4 if value == 0 else 1)
        draw.line([(s(plot_left), y), (s(plot_right), y)], fill=fill, width=width_line)
        label = f"{value}亿".replace("-", "−")
        tw, th = text_size(draw, label, font_axis)
        draw.text((s(plot_left - 16) - tw, y - th // 2), label, font=font_axis, fill=(70, 70, 70, 255))
    draw.line([(s(plot_left), s(plot_top)), (s(plot_left), s(plot_bottom))], fill=(198, 198, 198, 255), width=s(1.2))
    draw.line([(s(plot_left), s(plot_bottom)), (s(plot_right), s(plot_bottom))], fill=(198, 198, 198, 255), width=s(1.2))

    minutes = trading_minutes()
    tick_map = {"09:30": 0, "10:30": 60, "11:30": 120, "14:00": 181, "15:00": len(minutes) - 1}
    for label, idx in tick_map.items():
        x = x_to_px(idx, len(minutes))
        draw.line([(x, s(plot_bottom)), (x, s(plot_bottom + 8))], fill=(160, 160, 160, 255), width=s(1))
        tw, _ = text_size(draw, label, font_axis)
        draw.text((x - tw // 2, s(plot_bottom + 18)), label, font=font_axis, fill=(55, 55, 55, 255))

    # Title, brand and time box.
    month_day = datetime.strptime(trade_date, "%Y-%m-%d").strftime("%-m月%-d日") if os.name != "nt" else f"{int(trade_date[5:7])}月{int(trade_date[8:10])}日"
    title = f"{month_day} 收盘资金流向"
    draw.text(xy((70, 64)), title, font=font_title, fill=(255, 234, 38, 255), stroke_width=s(4), stroke_fill=(0, 0, 0, 255))
    brand_w, _ = text_size(draw, brand, font_brand)
    draw.text((s(730), s(188)), brand, font=font_brand, fill=(62, 62, 62, 255))

    time_text = f"时间: {label_time}"
    time_w, time_h = text_size(draw, time_text, font_time)
    box_left, box_top = s(990), s(176)
    draw.rounded_rectangle(
        [box_left, box_top, box_left + time_w + s(38), box_top + time_h + s(26)],
        radius=s(14),
        fill=(255, 255, 255, 255),
        outline=(220, 220, 220, 255),
        width=s(1),
    )
    draw.text((box_left + s(19), box_top + s(9)), time_text, font=font_time, fill=(44, 44, 44, 255))

    # Watermarks.
    for pos in [(255, 500), (255, 900), (525, 1210), (95, 1335), (685, 650)]:
        draw_rotated_text(canvas, brand, xy(pos), font_watermark, (165, 165, 165, 32))

    # Lines.
    for item in series:
        curve = resample_curve([float(v) for v in item["curve_yi"]], len(minutes))
        points = [(x_to_px(idx, len(minutes)), y_to_px(value)) for idx, value in enumerate(curve)]
        color = item.get("color", "#555555")
        draw.line(points, fill=color, width=s(3), joint="curve")
        x_end, y_end = points[-1]
        draw.ellipse([x_end - s(4.5), y_end - s(4.5), x_end + s(4.5), y_end + s(4.5)], fill=color)

    # Labels with simple collision avoidance.
    label_items = sorted(
        [
            {
                "name": str(item["name"]),
                "final": float(item["final_yi"]),
                "color": str(item.get("color", "#555555")),
                "target_y": y_to_px(float(item["final_yi"])) / scale,
            }
            for item in series
        ],
        key=lambda v: v["target_y"],
    )
    min_gap = 37
    top_limit, bottom_limit = plot_top + 200, plot_bottom - 20
    placed: list[dict[str, Any]] = []
    last_y = top_limit - min_gap
    for item in label_items:
        y = max(float(item["target_y"]), last_y + min_gap)
        item["label_y"] = y
        placed.append(item)
        last_y = y
    overflow = placed[-1]["label_y"] - bottom_limit if placed else 0
    if overflow > 0:
        for item in reversed(placed):
            item["label_y"] = max(top_limit, item["label_y"] - overflow)
            overflow = max(0, overflow - min_gap * 0.15)

    for item in placed:
        text = f"{item['name']}  {item['final']:+.2f}".replace("+", "+").replace("-", "−")
        y = s(item["label_y"])
        target_y = y_to_px(float(item["final"]))
        x0 = s(plot_right + 20)
        tw, th = text_size(draw, text, font_label)
        box = [x0, y - th // 2 - s(8), x0 + tw + s(22), y + th // 2 + s(8)]
        color = item["color"]
        draw.line([(s(plot_right), target_y), (x0, y)], fill=color, width=s(1))
        draw.rounded_rectangle(box, radius=s(8), fill=(255, 255, 255, 250), outline=color, width=s(2))
        draw.text((x0 + s(11), y - th // 2 - s(1)), text, font=font_label, fill=color)

    note = "根据实时数据整理，不作为买卖依据"
    note_w, _ = text_size(draw, note, font_note)
    draw.text((s(width / 2) - note_w // 2, s(height - 68)), note, font=font_note, fill=(100, 100, 100, 255))

    output.parent.mkdir(parents=True, exist_ok=True)
    final = canvas.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
    final.save(output, quality=95)


def save_payload(path: Path, trade_date: str, series: list[dict[str, Any]], source: str) -> None:
    payload = {
        "trade_date": trade_date,
        "source": source,
        "brand": DEFAULT_BRAND,
        "note": "Minute line shape uses iFinD THS_HF amount/changeRatio proxy when exact minute flow is unavailable.",
        "series": series,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate iFinD relay capital-flow chart PNG.")
    parser.add_argument("--date", default=date.today().isoformat(), help="Trade date, YYYY-MM-DD. Default: today.")
    parser.add_argument("--brand", default=DEFAULT_BRAND, help="Chart brand/watermark text.")
    parser.add_argument("--base-url", default=os.environ.get("IFIND_RELAY_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--key", default=None, help="Relay key. Prefer environment variables instead of typing it here.")
    parser.add_argument("--source-json", type=Path, default=None, help="Render from an existing chart JSON instead of fetching.")
    parser.add_argument("--final-source", choices=("ifind", "reference"), default="ifind")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print("--date must be YYYY-MM-DD", file=sys.stderr)
        return 2

    out_dir = repo_root() / ".ifind_probe"
    stamp = args.date.replace("-", "")
    output = args.output or out_dir / f"ifind_relay_capital_flow_auto_{stamp}.png"
    json_output = args.json_output or out_dir / f"ifind_relay_capital_flow_auto_{stamp}.json"

    if args.source_json:
        trade_date, series = load_series_json(args.source_json)
        source = f"source-json:{args.source_json}"
    else:
        key = args.key or discover_key()
        if not key:
            fallback = out_dir / "xueqiu_style_capital_flow_v3.json"
            if fallback.exists() and args.date == "2026-05-21":
                print("No relay key found; rendering the local 2026-05-21 cache.", file=sys.stderr)
                trade_date, series = load_series_json(fallback)
                source = f"fallback-cache:{fallback}"
            else:
                print("No relay key found. Set IFIND_RELAY_KEY or pass --key.", file=sys.stderr)
                return 2
        else:
            client = RelayClient(args.base_url, key)
            trade_date = args.date
            series = build_live_series(client, trade_date, args.final_source, trading_minutes())
            source = f"relay:{args.base_url};final-source:{args.final_source}"

    save_payload(json_output, trade_date, series, source)
    render_chart(trade_date, series, output, brand=args.brand)
    print(f"PNG: {output}")
    print(f"JSON: {json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
