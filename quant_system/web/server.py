"""Local-only HTTP entry for inspecting context and running Codex diagnosis."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from quant_system.ai.codex_diagnosis import diagnose_stock, load_diagnosis_context, recommend_stocks
from quant_system.ai.long_term_research import run_ai_long_term_research
from quant_system.config.crawler_config import CrawlerConfig
from quant_system.config.app_config import save_data_source_config, tickflow_config, tushare_config
from quant_system.pipeline.normalizer import normalize_code
from quant_system.tasks.stock_job import run_daily_stock
from quant_system.tasks.today_change_job import run_today_change_job
from quant_system.tasks.trade_plan_job import build_stock_operation_plan
from quant_system.tasks.universe_job import load_tickflow_universe, sync_tickflow_universe

ASSET_DIR = Path(__file__).resolve().parent
SYNC_LOCK = threading.Lock()
MARKET_JOB = {"status": "idle", "count": 0, "completed": 0, "error": ""}


def _read_data(rel: str) -> dict:
    path = CrawlerConfig().data_dir / rel
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _dashboard_payload(limit: int = 20) -> dict:
    strategy = _read_data("strategy/index.json")
    validation = _read_data("strategy_backtest/status.json")
    recommendations = _read_data("recommendations/summary.json")
    ai_long_term = _read_data("ai_long_term/latest.json")
    today_change = _read_data("today_change/summary.json")
    iteration = _read_data("iteration/status.json")
    iteration_worker = _read_data("iteration/worker_status.json")
    iteration_eta = _read_data("iteration/eta.json")
    daily_recap = _read_data("daily_market_recap/latest.json")
    trading = _read_data("trading/index.json")
    sector_rotation = _read_data("sector_data/rotation.json")
    tournament = _read_data("strategy_iterations/latest.json")
    polarized = _read_data("strategy_iterations/polarized_latest.json")
    freshness_reset = _read_data("data_freshness/reset.json")
    us_cpi = _read_data("macro/us_cpi.json")
    market_snapshot = _read_data("latest.json")
    stock_trade_date = today_change.get("trade_date") or recommendations.get("market_context", {}).get("trade_date")
    sector_trade_date = sector_rotation.get("trade_date")
    index_trade_date = market_snapshot.get("trade_date")
    observed_dates = [str(x) for x in (stock_trade_date, sector_trade_date, index_trade_date) if x]
    latest_observed = min(observed_dates) if observed_dates else None
    freshness_invalidated = freshness_reset.get("status") == "invalidated"
    items = list(strategy.get("items") or [])
    stage_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    for item in items:
        stage = str(item.get("trend_stage") or "unknown")
        confidence = str(item.get("confidence") or "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
    top = sorted(items, key=lambda item: float(item.get("trend_score") or 0), reverse=True)[:limit]
    periods = {
        key: {
            "label": period.get("label"), "horizon": period.get("horizon"),
            "recommendations": period.get("recommendations") or [],
            "observation": period.get("observation") or [],
            "shortage_count": period.get("shortage_count"),
        }
        for key, period in (recommendations.get("periods") or {}).items()
    }
    medium_evaluated = ((recommendations.get("periods") or {}).get("medium") or {}).get("evaluated") or []
    medium_validated = sorted([
        item for item in medium_evaluated
        if float((item.get("replay_summary") or {}).get("hit_rate") or 0) >= 0.55
        and float((item.get("replay_summary") or {}).get("avg_return_pct") or 0) >= 1.0
        and int((item.get("replay_summary") or {}).get("evaluated_count") or 0) >= 500
        and float(item.get("score") or 0) >= 60
        and not item.get("blockers")
    ], key=lambda item: float(item.get("score") or 0), reverse=True)[:10]
    return {
        "updated_at": strategy.get("updated_at"),
        "strategy": {"count": strategy.get("count", len(items)), "stage_counts": stage_counts, "confidence_counts": confidence_counts, "top": top},
        "validation": {key: validation.get(key) for key in ("status", "updated_at", "total", "completed", "validated")},
        "market_context": recommendations.get("market_context") or {},
        "today_change": today_change,
        "data_freshness": {
            "latest_observed_trade_date": latest_observed,
            "stock_trade_date": stock_trade_date,
            "sector_trade_date": sector_trade_date,
            "index_trade_date": index_trade_date,
            "updated_at": max(str(x.get("updated_at") or "") for x in (today_change, sector_rotation, market_snapshot, recommendations)),
            "degraded": freshness_invalidated or bool(recommendations.get("market_context", {}).get("degraded")) or len(set(observed_dates)) > 1,
            "status": "invalidated" if freshness_invalidated else ("degraded" if len(set(observed_dates)) > 1 else "valid"),
            "reset_reason": freshness_reset.get("reason"),
            "allow_formal_recommendation": not freshness_invalidated,
        },
        "us_cpi": us_cpi,
        "iteration": {
            key: iteration.get(key)
            for key in (
                "policy_version", "updated_at", "phase", "strategy_status",
                "promotion_allowed", "failed_gates", "next_actions", "gates",
            )
        },
        "iteration_worker": iteration_worker,
        "iteration_eta": iteration_eta,
        "daily_market_recap": daily_recap,
        "trading": trading,
        "sector_rotation": sector_rotation,
        "strategy_tournament": {
            "updated_at": tournament.get("updated_at"),
            "research_version": tournament.get("research_version"),
            "decision": tournament.get("decision"),
            "promotion_passed": tournament.get("promotion_passed", False),
            "horizons": {
                key: {
                    "selected_candidate": value.get("selected_candidate"),
                    "baseline_candidate": value.get("baseline_candidate"),
                    "promotion_passed": value.get("promotion_passed", False),
                    "evaluation_scope": value.get("evaluation_scope"),
                    "selected_oos": {k: value.get("selected_oos", {}).get(k) for k in ("trades", "hit_rate", "avg_net_return_pct", "max_drawdown_pct")},
                }
                for key, value in (tournament.get("horizon_results") or {}).items()
            },
        },
        "polarized_strategy": polarized,
        "periods": periods,
        "ai_long_term": ai_long_term,
        "medium_validated": medium_validated,
    }


def _sync_full_market() -> None:
    try:
        rows = sync_tickflow_universe()
        MARKET_JOB.update(status="running", count=len(rows), completed=0, error="")
        # 分块保存，单块失败不会丢失此前已完成的数据，并可向页面报告进度。
        completed = 0
        for start in range(0, len(rows), 50):
            chunk = rows[start:start + 50]
            completed += len(run_daily_stock(items=chunk))
            MARKET_JOB["completed"] = completed
        run_today_change_job()
        MARKET_JOB["status"] = "completed"
    except Exception as exc:  # noqa: BLE001
        MARKET_JOB.update(status="failed", error=str(exc))
    finally:
        if SYNC_LOCK.locked():
            SYNC_LOCK.release()


class DiagnosisHandler(BaseHTTPRequestHandler):
    server_version = "AStockDiagnosis/1.0"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = (ASSET_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/stocks":
            rows = load_tickflow_universe()
            if not rows:
                path = CrawlerConfig().stock_data_dir / "index.json"
                rows = (json.loads(path.read_text(encoding="utf-8")).get("stocks") or []) if path.exists() else []
            self._json(200, {"count": len(rows), "stocks": rows})
            return
        if parsed.path == "/api/tickflow/status":
            self._json(200, dict(MARKET_JOB))
            return
        if parsed.path == "/api/config/status":
            self._json(200, {
                "tickflow_configured": bool(tickflow_config()["api_key"]),
                "tushare_configured": bool(tushare_config()["token"]),
            })
            return
        if parsed.path == "/api/dashboard":
            limit = max(5, min(int(parse_qs(parsed.query).get("limit", ["20"])[0]), 100))
            self._json(200, _dashboard_payload(limit))
            return
        if parsed.path == "/api/strategy":
            code = normalize_code(parse_qs(parsed.query).get("code", [""])[0])
            payload = _read_data(f"strategy/{code}.json")
            validation = _read_data(f"strategy_backtest/{code}.json")
            if not payload:
                self._json(404, {"error": f"缺少 {code} 趋势策略"})
            else:
                self._json(200, {"strategy": payload, "validation": validation})
            return
        if parsed.path == "/api/operation":
            code = normalize_code(parse_qs(parsed.query).get("code", [""])[0])
            try:
                self._json(200, build_stock_operation_plan(code))
            except (ValueError, FileNotFoundError, OSError) as exc:
                self._json(404, {"error": str(exc)})
            return
        if parsed.path == "/api/context":
            code = normalize_code(parse_qs(parsed.query).get("code", [""])[0])
            try:
                self._json(200, load_diagnosis_context(code))
            except (ValueError, FileNotFoundError) as exc:
                self._json(404, {"error": str(exc)})
            return
        if parsed.path == "/api/realtime-kline":
            code = normalize_code((parse_qs(parsed.query).get("code") or [""])[0])
            from quant_system.data_source.stock_sdk_bridge import fetch_minute
            suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
            rows = fetch_minute(f"{code}.{suffix}")
            self._json(200, {"code": code, "source": "stock-sdk", "realtime": not rows.empty, "rows": rows.tail(240).to_dict(orient="records")})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route not in {"/api/diagnose", "/api/recommend", "/api/ai-long", "/api/tickflow/sync", "/api/config"}:
            self._json(404, {"error": "not found"})
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 16_384)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if route == "/api/config":
                tickflow_key = str(payload.get("tickflow_key") or "").strip()
                tushare_token = str(payload.get("tushare_token") or "").strip()
                if not tickflow_key and not tushare_token:
                    raise ValueError("至少填写一个新的 Key 或 Token")
                save_data_source_config(
                    tickflow_api_key=tickflow_key or None,
                    tushare_token=tushare_token or None,
                )
                self._json(200, {"ok": True, "message": "数据源配置已保存，仅存储在本机配置文件"})
                return
            if route == "/api/tickflow/sync":
                scope = str(payload.get("scope") or "current")
                code = normalize_code(str(payload.get("code") or ""))
                if scope not in {"current", "universe", "market", "phase1"}:
                    raise ValueError("同步范围必须是 current、universe、market 或 phase1")
                if scope == "current" and (not code.isdigit() or len(code) != 6):
                    raise ValueError("请选择有效股票")
                if not SYNC_LOCK.acquire(blocking=False):
                    self._json(409, {"error": "已有 TickFlow 同步任务正在运行"})
                    return
                if scope == "market":
                    MARKET_JOB.update(status="starting", count=0, completed=0, error="")
                    threading.Thread(target=_sync_full_market, daemon=True).start()
                    self._json(202, {"ok": True, "message": "全市场数据同步已在后台启动"})
                    return
                try:
                    if scope == "current":
                        rows = run_daily_stock(codes=[code])
                        run_today_change_job()
                    elif scope == "phase1":
                        from quant_system.tasks.phase1_market_data_job import run_phase1_market_data
                        summary = run_phase1_market_data(codes=[code] if code else None)
                        self._json(200, {"ok": True, "message": "Phase 1 市场制度数据同步完成", "summary": summary})
                        return
                    else:
                        rows = sync_tickflow_universe()
                finally:
                    SYNC_LOCK.release()
                if not rows:
                    raise RuntimeError("TickFlow 未返回可用数据，请检查 Key、网络和后台日志")
                self._json(200, {
                    "ok": True,
                    "scope": scope,
                    "count": len(rows),
                    "stocks": rows,
                    "message": f"TickFlow 同步完成，共更新 {len(rows)} 只股票",
                })
                return
            if route == "/api/recommend":
                limit = max(1, min(int(payload.get("limit") or 5), 10))
                path = recommend_stocks(limit=limit, focus=str(payload.get("focus") or "")[:500])
                self._json(200, {"ok": True, "content": path.read_text(encoding="utf-8")})
                return
            if route == "/api/ai-long":
                result = run_ai_long_term_research(focus=str(payload.get("focus") or "")[:500])
                self._json(200, {"ok": True, "result": result})
                return
            code = normalize_code(str(payload.get("code") or ""))
            path = diagnose_stock(code, focus=str(payload.get("focus") or "")[:500])
            self._json(200, {"ok": True, "content": path.read_text(encoding="utf-8")})
        except (ValueError, FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("端口必须在 1..65535")
    server = ThreadingHTTPServer((host, port), DiagnosisHandler)
    print(f"内部 AI 诊股页面: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
