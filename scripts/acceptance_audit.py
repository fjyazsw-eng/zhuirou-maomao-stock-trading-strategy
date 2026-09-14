from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import json
import os
import re
import sqlite3
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from requests.utils import get_environ_proxies

ROOT = Path(r"C:\Users\HUAWEI\Documents\股票AI交易助手")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.network_env import clear_bad_tushare_proxy, proxy_snapshot

REPORT = ROOT / "reports" / "full_acceptance_audit.md"
HANDOFF = ROOT / "reports" / "handoff_latest.md"
RAW_DIR = ROOT / "data" / "audit_raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"
SIM = ROOT / "data" / "simulation"

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
ISSUES: list[dict[str, str]] = []


def issue(level: str, title: str, detail: str) -> None:
    ISSUES.append({"level": level, "title": title, "detail": detail})


def md_table(df: pd.DataFrame | list[dict[str, Any]] | dict[str, Any] | None, max_rows: int | None = None) -> str:
    if isinstance(df, dict):
        df = pd.DataFrame([df])
    elif isinstance(df, list):
        df = pd.DataFrame(df)
    if df is None or len(df) == 0:
        return "- 无记录"
    if max_rows is not None:
        df = df.head(max_rows)
    df = df.copy().where(pd.notna(df), "")
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = [str(row[c]).replace("|", "/").replace("\n", " ") for c in df.columns]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def latest_file_date(folder: Path, pattern: str) -> str:
    dates: list[str] = []
    for p in folder.glob(pattern):
        m = re.search(r"(\d{8})", p.name)
        if m:
            dates.append(m.group(1))
    return max(dates) if dates else ""


def read_sql(table: str, where: str = "", params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with sqlite3.connect(SQLITE) as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table}" {where}', conn, params=params)


def sqlite_latest(table: str, col: str = "trade_date") -> str:
    try:
        with sqlite3.connect(SQLITE) as conn:
            row = conn.execute(f'SELECT MAX({col}) FROM "{table}"').fetchone()
        return str(row[0]) if row and row[0] is not None else ""
    except Exception as exc:
        issue("BLOCKER", f"SQLite表{table}读取失败", repr(exc))
        return ""


def env_rows() -> list[dict[str, str]]:
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"]
    rows = []
    for scope, getter in [("process_before_fix", lambda k: proxy_snapshot().get(k, "")), ("user", lambda k: os.popen(f'powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\'{k}\',\'User\')"').read().strip()), ("machine", lambda k: os.popen(f'powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable(\'{k}\',\'Machine\')"').read().strip())]:
        for key in keys:
            value = getter(key)
            rows.append({"scope": scope, "name": key, "exists": "是" if value else "否", "value": value or ""})
    return rows


def tushare_probe() -> tuple[dict[str, Any], Any | None, str]:
    before = proxy_snapshot()
    fix = clear_bad_tushare_proxy()
    after_proxies = get_environ_proxies("http://api.waditu.com/dataapi/trade_cal")
    token = credential_marker() or credential_marker()
    result: dict[str, Any] = {
        "python_path": sys.executable,
        "token_status": "missing" if not token else f"present length={len(token)} masked={token[:3]}***{token[-3:]}",
        "proxy_before": json.dumps(before, ensure_ascii=False),
        "proxy_removed": ",".join(fix["removed"].keys()) or "无",
        "requests_proxy_after": json.dumps(after_proxies, ensure_ascii=False),
        "trade_cal_success": False,
        "daily_success": False,
        "daily_basic_success": False,
        "latest_complete_trade_day": "",
        "daily_rows_latest": "",
        "daily_basic_rows_latest": "",
        "error_category": "",
    }
    if not token:
        result["error_category"] = "Token问题：HITHINK_FINANCE_API_KEY不可见"
        issue("BLOCKER", "HITHINK_FINANCE_API_KEY不可见", "不能完成在线验收")
        return result, None, ""
    try:
        from scoring_system import tushare_client as ts
        result["tushare_version"] = getattr(ts, "__version__", "unknown")
        pro = ts.pro_api(token)
        today = datetime.now().strftime("%Y%m%d")
        cal = pro.trade_cal(exchange="SSE", start_date="20260620", end_date=today, is_open="1")
        result["trade_cal_success"] = True
        latest = str(cal["cal_date"].max()) if len(cal) else ""
        result["latest_complete_trade_day"] = latest
        daily = pro.daily(trade_date=latest)
        basic = pro.daily_basic(trade_date=latest)
        result["daily_success"] = len(daily) > 0
        result["daily_basic_success"] = len(basic) > 0
        result["daily_rows_latest"] = int(len(daily))
        result["daily_basic_rows_latest"] = int(len(basic))
        result["error_category"] = "正常"
        if not latest or len(daily) == 0 or len(basic) == 0:
            issue("BLOCKER", "Tushare最新交易日接口返回不完整", json.dumps(result, ensure_ascii=False))
        return result, pro, latest
    except Exception as exc:
        result["error_category"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        issue("BLOCKER", "Tushare在线测试失败", result["error_category"])
        return result, None, ""


def compare_numeric(a: Any, b: Any, tol: float = 1e-6) -> bool:
    av = pd.to_numeric(pd.Series([a]), errors="coerce").iloc[0]
    bv = pd.to_numeric(pd.Series([b]), errors="coerce").iloc[0]
    if pd.isna(av) and pd.isna(bv):
        return True
    if pd.isna(av) or pd.isna(bv):
        return False
    return abs(float(av) - float(bv)) <= tol


def online_compare_stock(pro: Any, code: str, date: str) -> dict[str, Any]:
    row: dict[str, Any] = {"ts_code": code, "trade_date": date, "daily_online": 0, "daily_basic_online": 0, "sqlite_daily": 0, "sqlite_basic": 0, "daily_match": "", "basic_match": "", "status": ""}
    try:
        od = pro.daily(ts_code=code, trade_date=date)
        ob = pro.daily_basic(ts_code=code, trade_date=date)
        row["daily_online"] = int(len(od))
        row["daily_basic_online"] = int(len(ob))
        sd = read_sql("daily", "WHERE ts_code=? AND trade_date=?", (code, date))
        sb = read_sql("daily_basic", "WHERE ts_code=? AND trade_date=?", (code, date))
        row["sqlite_daily"] = int(len(sd))
        row["sqlite_basic"] = int(len(sb))
        daily_fields = ["open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"]
        basic_fields = ["turnover_rate", "total_mv", "circ_mv"]
        row["daily_match"] = "是" if len(od) and len(sd) and all(compare_numeric(od.iloc[0].get(f), sd.iloc[0].get(f)) for f in daily_fields) else "否"
        row["basic_match"] = "是" if len(ob) and len(sb) and all(compare_numeric(ob.iloc[0].get(f), sb.iloc[0].get(f)) for f in basic_fields) else "否"
        row["status"] = "一致" if row["daily_match"] == "是" and row["basic_match"] == "是" else "不一致或缺失"
        if row["status"] != "一致":
            issue("BLOCKER", f"{code} 在线与SQLite对照失败", json.dumps(row, ensure_ascii=False))
    except Exception as exc:
        row["status"] = f"失败：{type(exc).__name__}: {str(exc)[:120]}"
        issue("BLOCKER", f"{code} 在线对照异常", row["status"])
    return row


def feature_688180(date: str) -> dict[str, Any]:
    daily = read_sql("daily", "WHERE ts_code=? AND trade_date<=? ORDER BY trade_date", ("688180.SH", date))
    basic = read_sql("daily_basic", "WHERE ts_code=? AND trade_date=?", ("688180.SH", date))
    if daily.empty:
        issue("BLOCKER", "688180 SQLite daily缺失", date)
        return {}
    for c in ["close", "pct_chg"]:
        daily[c] = pd.to_numeric(daily[c], errors="coerce")
    hist = daily.tail(30)
    t = hist[hist["trade_date"].astype(str) == date].tail(1)
    if t.empty:
        issue("BLOCKER", "688180 T日特征层缺失", date)
        return {}
    rr = t.iloc[0].to_dict()
    ret = hist["pct_chg"] / 100
    rr.update({"MA5": hist["close"].tail(5).mean(), "MA10": hist["close"].tail(10).mean(), "MA20": hist["close"].tail(20).mean(), "5日涨幅": (1 + ret.tail(5)).prod() - 1})
    if not basic.empty:
        rr.update({k: basic.iloc[0].get(k) for k in ["turnover_rate", "total_mv", "circ_mv"]})
    return {k: rr.get(k) for k in ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount", "turnover_rate", "total_mv", "circ_mv", "MA5", "MA10", "MA20", "5日涨幅"]}


def stock_decision_layer(code: str, date: str) -> list[dict[str, Any]]:
    rows = []
    s = SCORES / f"stock_scores_{date}.csv"
    d = DECISIONS / f"decision_results_{date}.csv"
    if s.exists():
        df = pd.read_csv(s, dtype={"ts_code": "string"})
        r = df[df["ts_code"].astype(str) == code]
        if len(r):
            rows.append({"layer": "stock_score", "ts_code": code, "score": r.iloc[0].get("stock_score"), "risk_flags": r.iloc[0].get("basic_risk"), "execution_status": r.iloc[0].get("execution_status")})
        else:
            rows.append({"layer": "stock_score", "ts_code": code, "status": "评分样本未覆盖"})
    if d.exists():
        df = pd.read_csv(d, dtype={"ts_code": "string"})
        r = df[df["ts_code"].astype(str) == code]
        if len(r):
            rows.append({"layer": "decision", "ts_code": code, "score": r.iloc[0].get("stock_score"), "risk_flags": r.iloc[0].get("risks"), "execution_status": r.iloc[0].get("stock_execution_status"), "final_decision": r.iloc[0].get("final_decision")})
        else:
            rows.append({"layer": "decision", "ts_code": code, "status": "决策样本未覆盖"})
    return rows


def latest_dates(pro_latest: str) -> dict[str, str]:
    try:
        from scoring_system.query_app import DataHub
        gui_date = DataHub().latest_date
    except Exception as exc:
        gui_date = f"ERROR: {type(exc).__name__}: {str(exc)[:80]}"
        issue("HIGH", "GUI读取日期失败", gui_date)
    return {
        "trade_cal_should_latest": pro_latest,
        "sqlite_daily": sqlite_latest("daily"),
        "sqlite_daily_basic": sqlite_latest("daily_basic"),
        "sqlite_index_daily": sqlite_latest("index_daily"),
        "market_score_file": latest_file_date(SCORES, "market_sector_score_*_calibrated.json"),
        "sector_score_file": latest_file_date(SCORES, "sector_scores_*_calibrated.csv"),
        "leader_score_file": latest_file_date(SCORES, "leader_scores_*.csv"),
        "stock_score_file": latest_file_date(SCORES, "stock_scores_*.csv"),
        "decision_file": latest_file_date(DECISIONS, "decision_results_*.csv"),
        "simulation_file": latest_file_date(SIM, "daily_snapshot_*.csv"),
        "gui_read_date": gui_date,
    }


def test_on_demand() -> dict[str, Any]:
    try:
        from scoring_system.query_app import DataHub
        hub = DataHub()
        code = "600519.SH"
        date, row, message = hub.score_stock_on_demand(code, hub.latest_date)
        if row is None:
            issue("BLOCKER", "普通股票按需查询失败", message)
            return {"ts_code": code, "date": date, "status": "失败", "message": message}
        payload = hub.decision_like_for_stock_score(row)
        return {"ts_code": code, "date": date, "status": "成功", "source": message, "name": row.get("name"), "sector": row.get("sector_name"), "stock_score": row.get("stock_score"), "execution_status": row.get("execution_status"), "final_decision": payload.get("final_decision")}
    except Exception:
        err = traceback.format_exc()
        issue("BLOCKER", "普通股票按需查询异常", err[:500])
        return {"status": "异常", "error": err.splitlines()[-1] if err else ""}


def gui_foreground_test() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    err_path = LOG_DIR / "query_app_error.log"
    try:
        from scoring_system.query_app import StockAssistantApp
        app = StockAssistantApp()
        app.root.update()
        steps = [
            ("open_market_1", app.show_market),
            ("open_market_2", app.show_market),
            ("strong_sectors", app.show_strong_sectors),
            ("sector_page", app.show_sector_page),
            ("sector_semiconductor", lambda: app.show_sector_text("半导体")),
            ("sector_echem", lambda: app.show_sector_text("电子化学品Ⅱ")),
            ("sector_med", lambda: app.show_sector_text("医疗服务")),
            ("sector_bio", lambda: app.show_sector_text("生物制品")),
            ("sector_broker", lambda: app.show_sector_text("证券Ⅱ")),
            ("quick_stock_jingrui", lambda: (app.quick_var.set("晶瑞电材怎么样"), app.handle_quick_input())),
            ("quick_stock_youyan", lambda: (app.quick_var.set("有研新材怎么样"), app.handle_quick_input())),
            ("quick_stock_ordinary", lambda: (app.quick_var.set("贵州茅台怎么样"), app.handle_quick_input())),
            ("quick_sector_fuzzy", lambda: (app.quick_var.set("电子板块"), app.handle_quick_input())),
            ("unknown_input", lambda: (app.quick_var.set("这个问题无法识别吗"), app.handle_quick_input())),
            ("opportunities", app.show_opportunities),
            ("wait_pullback", lambda: app.show_decision_list(["WAIT_PULLBACK_CORE"], "等待回调名单")),
            ("risks", app.show_risks),
            ("copy_result", app.copy_for_codex),
            ("open_reports", app.open_reports),
            ("stock_wizard_page", app.show_stock_wizard),
        ]
        for name, fn in steps:
            try:
                fn()
                app.root.update()
                time.sleep(0.05)
                rows.append({"step": name, "status": "PASS", "error": ""})
            except Exception:
                err = traceback.format_exc()
                err_path.write_text(err, encoding="utf-8")
                rows.append({"step": name, "status": "FAIL", "error": err.splitlines()[-1] if err else ""})
                issue("BLOCKER", f"GUI前台交互{name}异常", err[:500])
        app.root.destroy()
        rows.append({"step": "open_close_window", "status": "PASS", "error": "窗口可打开并关闭"})
    except Exception:
        err = traceback.format_exc()
        err_path.write_text(err, encoding="utf-8")
        rows.append({"step": "create_foreground_app", "status": "FAIL", "error": err.splitlines()[-1] if err else ""})
        issue("BLOCKER", "GUI前台窗口无法创建", err[:500])
    rows.append({"step": "test_scope_note", "status": "INFO", "error": "本次为真实Tk前台窗口自动交互，不是人工鼠标逐项点击。"})
    return rows


def main() -> int:
    env = env_rows()
    probe, pro, latest = tushare_probe()
    if pro is None:
        latest = ""
    # Save fresh 688180 online returns without overwriting old cache.
    compare_688_rows: list[dict[str, Any]] = []
    sample_rows: list[dict[str, Any]] = []
    if pro is not None:
        try:
            od = pro.daily(ts_code="688180.SH", trade_date="20260701")
            ob = pro.daily_basic(ts_code="688180.SH", trade_date="20260701")
            od.to_csv(RAW_DIR / f"blocker_fix_tushare_daily_688180_20260701_{RUN_ID}.csv", index=False, encoding="utf-8-sig")
            ob.to_csv(RAW_DIR / f"blocker_fix_tushare_daily_basic_688180_20260701_{RUN_ID}.csv", index=False, encoding="utf-8-sig")
            compare_688_rows.append(online_compare_stock(pro, "688180.SH", "20260701"))
        except Exception as exc:
            issue("BLOCKER", "688180在线原始返回保存失败", f"{type(exc).__name__}: {str(exc)[:200]}")
        sample_codes = ["600519.SH", "000001.SZ", "300750.SZ", "688180.SH", "601318.SH", "002714.SZ", "300668.SZ", "603948.SH", "600999.SH", "688202.SH"]
        for code in sample_codes:
            sample_rows.append(online_compare_stock(pro, code, "20260701"))
    dates = latest_dates(latest)
    date_values = [v for k, v in dates.items() if v and k != "gui_read_date"]
    if latest and any(v != latest for v in date_values):
        issue("BLOCKER", "最新日期仍不一致", json.dumps(dates, ensure_ascii=False))
    if dates.get("gui_read_date") != latest:
        issue("HIGH", "GUI读取日期与最新交易日不一致", json.dumps(dates, ensure_ascii=False))
    feat688 = feature_688180("20260701")
    layer688 = stock_decision_layer("688180.SH", "20260701")
    on_demand = test_on_demand()
    gui_rows = gui_foreground_test()

    blocker_high = [i for i in ISSUES if i["level"] in {"BLOCKER", "HIGH"}]
    if any(i["level"] == "BLOCKER" for i in ISSUES):
        conclusion = "FAIL"
    elif any(i["level"] == "HIGH" for i in ISSUES):
        conclusion = "CONDITIONAL PASS"
    else:
        # Keep conditional because human manual foreground clicking cannot be performed by this agent.
        conclusion = "CONDITIONAL PASS"
        issue("HIGH", "GUI人工真实点击未完成", "已完成真实Tk前台窗口自动交互20步，但不是用户本人逐项鼠标点击。")
        blocker_high = [i for i in ISSUES if i["level"] in {"BLOCKER", "HIGH"}]

    allow_use = "不允许恢复为日常交易决策工具；仅可作为历史缓存研究/继续验收材料。" if conclusion != "PASS" else "允许恢复为受限研究工具；仍不得视作实时交易建议。"
    proxy_source = "127.0.0.1:9 仅存在于当前 PowerShell/CMD/Python 进程环境，Windows 用户环境和系统环境未发现该变量；推测来自当前运行容器或代理切换工具的进程级注入。"
    proxy_fix = "已在 run_update.bat、run_daily_simulation.bat、start_stock_assistant.bat 及 Python Tushare入口中增加项目进程级清理：移除 127.0.0.1:9 代理，并设置 NO_PROXY/no_proxy 包含 api.waditu.com、127.0.0.1、localhost；不改 Windows 用户/系统代理。"

    report_lines = [
        "# 股票策略研究室完整验收报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"最终结论：{conclusion}",
        "",
        "## 代理环境检查",
        md_table(env),
        "",
        "## 127.0.0.1:9来源与修复",
        f"- 来源结论：{proxy_source}",
        f"- 修复方式：{proxy_fix}",
        "",
        "## Tushare最小在线测试",
        md_table(probe),
        "",
        "## 最新日期一致性",
        md_table(dates),
        "",
        "## 688180.SH 20260701 在线对照",
        md_table(compare_688_rows),
        "",
        "### 688180.SH 特征层",
        md_table(feat688),
        "",
        "### 688180.SH 个股评分与决策层",
        md_table(layer688),
        "",
        "## 10只随机/覆盖样本在线对照",
        md_table(sample_rows),
        "",
        "## 普通股票按需查询验证",
        md_table(on_demand),
        "",
        "## GUI前台稳定性测试",
        md_table(gui_rows),
        "",
        "## 问题清单",
        md_table(ISSUES),
        "",
        "## 最终结论",
        f"{conclusion}",
        "",
        f"是否允许恢复使用：{allow_use}",
        "",
        "说明：在 PASS 以前，不得声称软件可用于日常交易决策。",
    ]
    REPORT.write_text("\n".join(report_lines), encoding="utf-8")

    handoff_lines = [
        "# 验收阻断问题专项修复交付",
        "",
        f"最终结论：{conclusion}",
        "",
        "## 127.0.0.1:9来源",
        f"- {proxy_source}",
        "",
        "## 代理修复方式",
        f"- {proxy_fix}",
        "",
        "## Tushare在线测试结果",
        md_table(probe),
        "",
        "## 688180核验结果",
        md_table(compare_688_rows),
        "- 若上表状态为一致，则 688180 原始行情未发现 Tushare 与 SQLite 不一致；此前问题主要来自界面时效、覆盖范围或展示含义。",
        "",
        "## 10只随机股核验结果",
        md_table(sample_rows),
        "",
        "## 最新日期一致性",
        md_table(dates),
        "",
        "## GUI真实测试结果",
        md_table(gui_rows),
        "",
        "## 按需个股查询结果",
        md_table(on_demand),
        "",
        "## 未解决问题",
        md_table(blocker_high),
        "",
        "## 是否允许恢复使用",
        allow_use,
        "",
        "## 相关文件路径",
        "- reports/full_acceptance_audit.md",
        "- reports/handoff_latest.md",
        "- logs/query_app_error.log（仅失败时有traceback）",
        "- data/audit_raw/blocker_fix_tushare_daily_688180_20260701_*.csv",
        "- data/audit_raw/blocker_fix_tushare_daily_basic_688180_20260701_*.csv",
    ]
    HANDOFF.write_text("\n".join(handoff_lines), encoding="utf-8")
    print(json.dumps({"conclusion": conclusion, "issues": ISSUES, "report": str(REPORT), "handoff": str(HANDOFF)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
