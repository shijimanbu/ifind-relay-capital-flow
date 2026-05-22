# -*- coding: utf-8 -*-
"""Local realtime monitor for iFinD relay capital-flow snapshots."""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import parse

from generate_ifind_relay_capital_flow import (
    BOARDS,
    DEFAULT_BASE_URL,
    RelayClient,
    discover_key,
    repo_root,
)


WEB_ROOT = repo_root() / "web"
STATE_DIR = repo_root() / ".ifind_probe"
DEFAULT_MAX_SNAPSHOTS = 10_000


def now_local() -> datetime:
    return datetime.now().astimezone()


def market_progress(ts: datetime) -> float:
    minutes = ts.hour * 60 + ts.minute + ts.second / 60
    sessions = [(9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60)]
    total = sum(end - start for start, end in sessions)
    done = 0.0
    for start, end in sessions:
        if minutes <= start:
            break
        done += min(minutes, end) - start
        if minutes < end:
            break
    return max(0.0, min(1.0, done / total))


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    try:
        return float(str(value).strip().replace(",", ""))
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

    def visit(value: Any, inherited: dict[str, Any] | None = None) -> None:
        base = dict(inherited or {})
        if isinstance(value, dict):
            for key in ("thscode", "code", "securityCode"):
                if isinstance(value.get(key), str):
                    base["thscode"] = value[key]
            if any(key in value for key in ("largeNetInflow", "mainNetInflow", "amount", "latest", "thscode", "code")):
                row = dict(base)
                for key, val in value.items():
                    if not isinstance(val, (dict, list)):
                        row[key] = val
                records.append(row)
            table = value.get("table")
            if isinstance(table, dict):
                lengths = [len(v) for v in table.values() if isinstance(v, list)]
                if lengths:
                    for idx in range(max(lengths)):
                        row = dict(base)
                        for key, column in table.items():
                            row[key] = column[idx] if isinstance(column, list) and idx < len(column) else column
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


class CapitalFlowMonitor:
    def __init__(
        self,
        trade_date: str,
        interval_seconds: int,
        base_url: str,
        key: str | None,
        mock: bool,
        max_snapshots: int,
    ) -> None:
        self.trade_date = trade_date
        self.interval_seconds = interval_seconds
        self.base_url = base_url
        self.key = key
        self.mock = mock
        self.max_snapshots = max_snapshots
        self.client = RelayClient(base_url, key) if key and not mock else None
        self.lock = threading.Lock()
        self.last_fetch_ts = 0.0
        self.last_error: str | None = None
        self.snapshots: list[dict[str, Any]] = []
        self.state_path = STATE_DIR / f"live_state_{trade_date.replace('-', '')}.json"
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if data.get("trade_date") == self.trade_date and isinstance(data.get("snapshots"), list):
            self.snapshots = data["snapshots"][-self.max_snapshots :]

    def _save_state(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "trade_date": self.trade_date,
            "updated_at": now_local().isoformat(timespec="seconds"),
            "snapshots": self.snapshots[-self.max_snapshots :],
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mock_values(self, ts: datetime) -> dict[str, float]:
        progress = market_progress(ts)
        tick = len(self.snapshots)
        values: dict[str, float] = {}
        for idx, board in enumerate(BOARDS):
            target = board.reference_final_yi
            wobble = math.sin(tick * 0.31 + idx * 0.7) * max(0.8, abs(target) * 0.025)
            early_lift = math.sin(progress * math.pi) * (18 - idx * 0.45)
            value = target * (0.08 + 0.92 * progress**1.45) + wobble + early_lift
            values[board.name] = round(value, 2)
        return values

    def _ifind_values(self) -> dict[str, float]:
        if not self.client:
            raise RuntimeError("IFIND_RELAY_KEY is not configured")
        codes = ",".join(dict.fromkeys(board.code for board in BOARDS))
        data = self.client.execute(
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
                by_code[code] = round(value_yi, 2)
        if not by_code:
            raise RuntimeError("iFinD relay returned no capital-flow rows")
        return {board.name: by_code.get(board.code, board.reference_final_yi) for board in BOARDS}

    def _append_snapshot(self, values: dict[str, float], source: str, ts: datetime) -> None:
        snapshot = {
            "as_of": ts.isoformat(timespec="seconds"),
            "time": ts.strftime("%H:%M:%S"),
            "source": source,
            "values_yi": values,
        }
        if self.snapshots and self.snapshots[-1].get("time") == snapshot["time"]:
            self.snapshots[-1] = snapshot
        else:
            self.snapshots.append(snapshot)
        self.snapshots = self.snapshots[-self.max_snapshots :]
        self._save_state()

    def refresh_if_needed(self, force: bool = False) -> dict[str, Any]:
        with self.lock:
            age = time.time() - self.last_fetch_ts
            should_fetch = force or not self.snapshots or age >= self.interval_seconds
            if should_fetch:
                ts = now_local()
                try:
                    if self.mock:
                        values = self._mock_values(ts)
                        source = "mock"
                    else:
                        values = self._ifind_values()
                        source = "ifind"
                    self._append_snapshot(values, source, ts)
                    self.last_fetch_ts = time.time()
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - keep server alive and surface error in JSON.
                    self.last_error = str(exc)
                    if not self.snapshots:
                        values = {board.name: 0.0 for board in BOARDS}
                        self._append_snapshot(values, "empty", now_local())

            return self.payload()

    def payload(self) -> dict[str, Any]:
        latest = self.snapshots[-1] if self.snapshots else {"values_yi": {}, "as_of": None, "source": "empty"}
        previous = self.snapshots[-2]["values_yi"] if len(self.snapshots) >= 2 else {}
        latest_values = latest.get("values_yi", {})
        boards = []
        for board in BOARDS:
            current = round(float(latest_values.get(board.name, 0.0)), 2)
            prev = previous.get(board.name)
            delta = round(current - float(prev), 2) if prev is not None else 0.0
            boards.append(
                {
                    "name": board.name,
                    "code": board.code,
                    "color": board.color,
                    "current_yi": current,
                    "delta_yi": delta,
                    "history": [
                        {
                            "time": snapshot["time"],
                            "value_yi": round(float(snapshot.get("values_yi", {}).get(board.name, 0.0)), 2),
                        }
                        for snapshot in self.snapshots
                    ],
                }
            )

        next_fetch_in = max(0, int(self.interval_seconds - (time.time() - self.last_fetch_ts)))
        return {
            "ok": self.last_error is None,
            "error": self.last_error,
            "trade_date": self.trade_date,
            "as_of": latest.get("as_of"),
            "source": latest.get("source", "empty"),
            "poll_seconds": self.interval_seconds,
            "next_fetch_in": next_fetch_in,
            "snapshot_count": len(self.snapshots),
            "boards": boards,
        }


def write_json(handler: SimpleHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def make_handler(monitor: CapitalFlowMonitor) -> type[SimpleHTTPRequestHandler]:
    class MonitorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = parse.urlparse(self.path)
            if parsed.path == "/api/capital-flow":
                query = parse.parse_qs(parsed.query)
                payload = monitor.refresh_if_needed(force=query.get("force", ["0"])[0] == "1")
                write_json(self, payload)
                return
            if parsed.path == "/api/status":
                write_json(self, monitor.payload())
                return
            if parsed.path == "/":
                self.path = "/index.html"
            return super().do_GET()

    return MonitorHandler


def start_background_collector(monitor: CapitalFlowMonitor) -> threading.Thread:
    def collect() -> None:
        while True:
            monitor.refresh_if_needed()
            time.sleep(max(1, min(5, monitor.interval_seconds)))

    thread = threading.Thread(target=collect, name="ifind-capital-flow-collector", daemon=True)
    thread.start()
    return thread


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local iFinD relay capital-flow monitor.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--date", default=date.today().isoformat(), help="Trade date, YYYY-MM-DD.")
    parser.add_argument("--interval", type=int, default=5, help="Minimum seconds between relay fetches.")
    parser.add_argument("--base-url", default=os.environ.get("IFIND_RELAY_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--key", default=None, help="Relay key. Prefer IFIND_RELAY_KEY.")
    parser.add_argument("--mock", action="store_true", help="Use deterministic local data for UI smoke tests.")
    parser.add_argument("--max-snapshots", type=int, default=DEFAULT_MAX_SNAPSHOTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    key = args.key or discover_key()
    monitor = CapitalFlowMonitor(
        trade_date=args.date,
        interval_seconds=max(5, args.interval),
        base_url=args.base_url,
        key=key,
        mock=args.mock,
        max_snapshots=max(100, args.max_snapshots),
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(monitor))
    start_background_collector(monitor)
    mode = "mock" if args.mock else "ifind"
    browser_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"iFinD relay monitor running in {mode} mode: http://{browser_host}:{args.port}")
    if args.host == "0.0.0.0":
        print(f"Listening on all interfaces. LAN clients can use this machine's IP with port {args.port}.")
    if not args.mock and not key:
        print("IFIND_RELAY_KEY is not configured; API responses will report the missing key until configured.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nmonitor stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
