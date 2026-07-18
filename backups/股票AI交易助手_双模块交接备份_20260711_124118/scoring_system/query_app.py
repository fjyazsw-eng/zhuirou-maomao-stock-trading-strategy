from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.decision_engine import decision_for_row
from scoring_system.stock_score import (
    load_upstream as load_stock_upstream,
    load_yaml as load_stock_yaml,
    read_table as read_stock_table,
    score_stock,
    sector_equal_returns,
    stock_sector_map,
)


SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"
REPORTS = ROOT / "reports"
SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
STOCK_BASIC_CSV = ROOT / "data" / "raw" / "tushare" / "stock_basic" / "stock_basic.csv"
ASSETS = ROOT / "assets"
ICON_PATH = ASSETS / "stock_assistant.ico"


def latest_file_date(folder: Path, pattern: str) -> str:
    dates: list[str] = []
    for path in folder.glob(pattern):
        match = re.search(r"(\d{8})", path.name)
        if match:
            dates.append(match.group(1))
    return max(dates) if dates else ""


def is_missing_scalar(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return False
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool):
            return missing
        return False
    except Exception:
        return False


def pct(value: Any) -> str:
    try:
        if is_missing_scalar(value):
            return "-"
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def num(value: Any) -> str:
    try:
        if is_missing_scalar(value):
            return "-"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def split_items(value: Any) -> list[str]:
    if is_missing_scalar(value):
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items: list[str] = []
        for item in value:
            raw_items.extend(split_items(item))
        return raw_items
    text = str(value).replace(",", "；")
    return [x.strip() for x in text.split("；") if x.strip() and x.strip() != "-"]


def clean_query_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


class DataHub:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.latest_market_date = latest_file_date(SCORES, "market_sector_score_*_calibrated.json")
        self.latest_sector_date = latest_file_date(SCORES, "sector_scores_*_calibrated.csv")
        self.latest_leader_date = latest_file_date(SCORES, "leader_scores_*.csv")
        self.latest_decision_date = latest_file_date(DECISIONS, "decision_results_*.csv")
        self.latest_date = max([d for d in [self.latest_market_date, self.latest_sector_date, self.latest_decision_date] if d], default="")
        self._stock_basic: pd.DataFrame | None = None

    def market_payload(self) -> dict[str, Any]:
        path = SCORES / f"market_sector_score_{self.latest_market_date}_calibrated.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def sectors(self, date: str | None = None) -> pd.DataFrame:
        as_of = date or self.latest_sector_date
        path = SCORES / f"sector_scores_{as_of}_calibrated.csv"
        return pd.read_csv(path, dtype={"index_code": "string"}) if path.exists() else pd.DataFrame()

    def leaders(self, date: str | None = None) -> pd.DataFrame:
        as_of = date or self.latest_leader_date
        path = SCORES / f"leader_scores_{as_of}.csv"
        return pd.read_csv(path, dtype={"sector_code": "string", "ts_code": "string"}) if path.exists() else pd.DataFrame()

    def decisions(self, date: str | None = None) -> pd.DataFrame:
        as_of = date or self.latest_decision_date
        path = DECISIONS / f"decision_results_{as_of}.csv"
        return pd.read_csv(path, dtype={"ts_code": "string"}) if path.exists() else pd.DataFrame()

    def decision_dates_desc(self) -> list[str]:
        dates = []
        for path in DECISIONS.glob("decision_results_*.csv"):
            match = re.search(r"(\d{8})", path.name)
            if match:
                dates.append(match.group(1))
        return sorted(set(dates), reverse=True)

    def stock_basic(self) -> pd.DataFrame:
        if self._stock_basic is not None and not self._stock_basic.empty:
            return self._stock_basic
        frames: list[pd.DataFrame] = []
        if SQLITE.exists():
            with sqlite3.connect(SQLITE) as conn:
                try:
                    frames.append(pd.read_sql_query("SELECT ts_code, name FROM stock_basic", conn))
                except Exception:
                    pass
        if STOCK_BASIC_CSV.exists():
            try:
                frames.append(pd.read_csv(STOCK_BASIC_CSV, dtype={"ts_code": "string", "name": "string"})[["ts_code", "name"]])
            except Exception:
                pass
        df = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=["ts_code", "name"])
        df = df.dropna(subset=["ts_code", "name"]).drop_duplicates("ts_code")
        df["ts_code"] = df["ts_code"].astype(str).str.strip()
        df["name"] = df["name"].astype(str).str.strip()
        df["name_key"] = df["name"].map(clean_query_text)
        df["code_key"] = df["ts_code"].map(clean_query_text)
        self._stock_basic = df
        return df

    def resolve_stocks(self, query: str) -> pd.DataFrame:
        q = clean_query_text(query)
        if not q:
            return pd.DataFrame(columns=["ts_code", "name"])
        basic = self.stock_basic()
        code_like = bool(re.match(r"^\d{6}(\.(SZ|SH|BJ))?$", q))
        if code_like and "." not in q:
            candidates = basic[basic["code_key"].str.startswith(q)]
        elif code_like:
            candidates = basic[basic["code_key"] == q]
        else:
            candidates = basic[basic["name_key"].str.contains(q, na=False, regex=False)]
        if candidates.empty:
            all_decisions = []
            for date in self.decision_dates_desc():
                all_decisions.append(self.decisions(date)[["ts_code", "name"]])
            if all_decisions:
                merged = pd.concat(all_decisions).drop_duplicates()
                merged["name_key"] = merged["name"].map(clean_query_text)
                merged["code_key"] = merged["ts_code"].map(clean_query_text)
                candidates = merged[
                    merged["code_key"].str.contains(q, na=False, regex=False)
                    | merged["name_key"].str.contains(q, na=False, regex=False)
                ]
        return candidates.drop_duplicates("ts_code").sort_values("ts_code")[["ts_code", "name"]]

    def stock_score_dates_desc(self) -> list[str]:
        dates = []
        for path in SCORES.glob("stock_scores_*.csv"):
            match = re.search(r"(\d{8})", path.name)
            if match:
                dates.append(match.group(1))
        return sorted(set(dates), reverse=True)

    def stock_scores(self, date: str) -> pd.DataFrame:
        path = SCORES / f"stock_scores_{date}.csv"
        return pd.read_csv(path, dtype={"ts_code": "string"}) if path.exists() else pd.DataFrame()

    def latest_stock_score_row(self, stock_code: str) -> tuple[str, pd.Series | None]:
        for date in self.stock_score_dates_desc():
            df = self.stock_scores(date)
            row = df[df["ts_code"].astype(str).str.upper() == stock_code.upper()]
            if len(row):
                return date, row.iloc[0]
        return "", None

    def score_stock_on_demand(self, stock_code: str, as_of: str | None = None) -> tuple[str, pd.Series | None, str]:
        date = as_of or self.latest_market_date or self.latest_sector_date
        if not date:
            return "", None, "缺少可用评分日期"
        try:
            cfg = load_stock_yaml(ROOT / "config" / "stock_score.yaml")
            market, sectors, leader = load_stock_upstream(date)
            with sqlite3.connect(SQLITE) as conn:
                daily = read_stock_table(conn, "daily")
                daily_basic = read_stock_table(conn, "daily_basic")
                stock_basic = read_stock_table(conn, "stock_basic")
                members = read_stock_table(conn, "index_member")
                classify = read_stock_table(conn, "index_classify")
            dates = sorted(daily["trade_date"].dropna().astype(str).unique().tolist())
            dates = [d for d in dates if d <= date][-30:]
            sector_map = stock_sector_map(members, classify, date)
            sector_returns = sector_equal_returns(daily, members, classify, date, dates)
            row = score_stock(stock_code, date, daily, daily_basic, stock_basic, sector_map, sector_returns, market, sectors, leader, cfg)
            return date, pd.Series(row), "按需离线评分"
        except Exception as exc:
            return date, None, f"按需评分失败：{type(exc).__name__}: {str(exc)[:120]}"

    def decision_like_for_stock_score(self, row: pd.Series) -> dict[str, Any]:
        try:
            import yaml
            cfg = yaml.safe_load((ROOT / "config" / "decision_rules.yaml").read_text(encoding="utf-8"))
            leader = self.leaders(str(row.get("trade_date", self.latest_leader_date)))
            return decision_for_row(row, leader, cfg)
        except Exception:
            return {
                "trade_date": str(row.get("trade_date", "")),
                "ts_code": str(row.get("ts_code", "")),
                "name": str(row.get("name", row.get("ts_code", ""))),
                "market_score": row.get("market_score"),
                "market_grade": str(row.get("market_grade", "-")),
                "sector_name": str(row.get("sector_name", "-")),
                "sector_score": row.get("sector_score"),
                "sector_grade": str(row.get("sector_grade", "-")),
                "leader_score": row.get("leader_score"),
                "core_identity": "非核心候选",
                "stock_score": row.get("stock_score"),
                "stock_execution_status": str(row.get("execution_status", "-")),
                "final_decision": str(row.get("execution_status", "-")),
                "current_stage": "按个股执行评分观察",
                "advantages": split_items(row.get("advantages"))[:3],
                "risks": split_items(str(row.get("basic_risk", "")).replace("基础行情风险：", ""))[:3],
                "wait_conditions": split_items(row.get("wait_or_stop_conditions"))[:3],
                "invalid_conditions": [],
                "event_risk": str(row.get("event_risk", "事件风险：未检查或数据缺失")),
                "data_quality": row.get("data_quality"),
            }

    def market_history_lines(self, days: int = 5) -> list[str]:
        lines = []
        for date in sorted([d for d in {self.latest_market_date, *[re.search(r"(\d{8})", p.name).group(1) for p in SCORES.glob("market_sector_score_*_calibrated.json") if re.search(r"(\d{8})", p.name)]} if d])[-days:]:
            path = SCORES / f"market_sector_score_{date}_calibrated.json"
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            m = payload.get("market_score", {})
            f = m.get("features", {})
            lines.append(f"- {date}：市场{num(m.get('score'))} / {m.get('grade','-')}，上涨宽度{pct(f.get('up_ratio'))}，成交变化{num(f.get('amount_vs_5d_avg'))}倍")
        return lines

    def stock_history_lines(self, stock_code: str, days: int = 5) -> list[str]:
        lines = []
        for date in self.stock_score_dates_desc()[:days]:
            df = self.stock_scores(date)
            row = df[df["ts_code"].astype(str).str.upper() == stock_code.upper()]
            if len(row):
                r = row.iloc[0]
                lines.append(f"- {date}：{num(r.get('stock_score'))} / {r.get('grade','-')}，{r.get('execution_status','-')}，{r.get('sector_name','-')}")
        return lines

    def stock_price_history_lines(self, stock_code: str, as_of: str | None = None, days: int = 5) -> list[str]:
        if not SQLITE.exists():
            return []
        with sqlite3.connect(SQLITE) as conn:
            daily = read_stock_table(conn, "daily")
            basic = read_stock_table(conn, "daily_basic")
        daily = daily[daily["ts_code"].astype(str).str.upper() == stock_code.upper()].copy()
        if daily.empty:
            return []
        if as_of:
            daily = daily[daily["trade_date"].astype(str) <= as_of]
        daily = daily.sort_values("trade_date").tail(days)
        lines = []
        for row in daily.itertuples(index=False):
            close_value = pd.to_numeric(pd.Series([getattr(row, "close", None)]), errors="coerce").iloc[0]
            pct_value = pd.to_numeric(pd.Series([getattr(row, "pct_chg", None)]), errors="coerce").iloc[0]
            amount_value = pd.to_numeric(pd.Series([getattr(row, "amount", None)]), errors="coerce").iloc[0]
            pct_display_value = None if pd.isna(pct_value) else float(pct_value) / 100
            lines.append(f"- {row.trade_date}：收盘{num(close_value)}，涨跌{pct(pct_display_value)}，成交额{num(amount_value)}元")
        return lines

    def sector_history_lines(self, sector_name: str, days: int = 5) -> list[str]:
        lines = []
        for date in sorted([re.search(r"(\d{8})", p.name).group(1) for p in SCORES.glob("sector_scores_*_calibrated.csv") if re.search(r"(\d{8})", p.name)])[-days:]:
            df = self.sectors(date)
            row = df[df["industry_name"].astype(str) == sector_name]
            if len(row):
                r = row.iloc[0]
                lines.append(f"- {date}：{num(r.get('score'))} / {r.get('grade','-')}，相对强度{num(r.get('relative_strength_composite'))}，扩散{pct(r.get('up_ratio'))}")
        return lines

    def decision_for_stock(self, stock_code: str) -> tuple[str, pd.Series | None]:
        for date in self.decision_dates_desc():
            df = self.decisions(date)
            row = df[df["ts_code"].astype(str).str.upper() == stock_code.upper()]
            if len(row):
                return date, row.iloc[0]
        return "", None

    def search_sectors(self, keyword: str) -> pd.DataFrame:
        df = self.sectors()
        if not keyword.strip():
            return df.sort_values("score", ascending=False)
        key = keyword.strip()
        return df[df["industry_name"].astype(str).str.contains(key, na=False, regex=False)].sort_values("score", ascending=False)


class StockAssistantApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Side.TFrame", background="#eef2f7")
        style.configure("Main.TFrame", background="#f8fafc")
        style.configure("Header.TLabel", background="#f8fafc", foreground="#0f172a", font=("Microsoft YaHei", 16, "bold"))
        style.configure("SideHeader.TLabel", background="#eef2f7", foreground="#111827", font=("Microsoft YaHei", 18, "bold"))
        style.configure("Hint.TLabel", background="#f8fafc", foreground="#475569", font=("Microsoft YaHei", 9))
        style.configure("Action.TButton", font=("Microsoft YaHei", 10, "bold"), padding=(10, 8))
        style.configure("Nav.TButton", font=("Microsoft YaHei", 10), padding=(8, 8))
        self.hub = DataHub()
        self.root = tk.Tk()
        self.root.title("股票策略研究室")
        self.root.geometry("1180x760")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.root.configure(bg="#eef2f7")
        if ICON_PATH.exists():
            try:
                self.root.iconbitmap(default=str(ICON_PATH))
            except Exception:
                pass
        self.current_result = ""
        self.current_params: dict[str, Any] = {}

        self.left = ttk.Frame(self.root, padding=14, style="Side.TFrame")
        self.left.pack(side=tk.LEFT, fill=tk.Y)
        self.main = ttk.Frame(self.root, padding=18, style="Main.TFrame")
        self.main.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self._build_home()

    def _build_home(self) -> None:
        for child in self.left.winfo_children():
            child.destroy()
        self.ttk.Label(self.left, text="股票策略研究室", style="SideHeader.TLabel").pack(anchor="w", pady=(0, 4))
        self.ttk.Label(self.left, text="选项式引导为主，自然语言补充为辅", style="Hint.TLabel").pack(anchor="w", pady=(0, 12))
        buttons = [
            ("最新市场状态", self.show_market),
            ("找强势板块", self.show_strong_sectors),
            ("查看板块核心股票", self.show_sector_page),
            ("查询某只股票", self.show_stock_wizard),
            ("查看模拟机会", self.show_opportunities),
            ("查看等待回调名单", lambda: self.show_decision_list(["WAIT_PULLBACK_CORE"], "等待回调名单")),
            ("查看风险和回避名单", self.show_risks),
            ("更新今日数据", self.run_update_data),
            ("运行每日模拟", self.run_daily_simulation),
            ("打开详细报告", self.open_reports),
        ]
        for text, command in buttons:
            self.ttk.Button(self.left, text=text, command=command, width=22, style="Nav.TButton").pack(fill="x", pady=4)
        self.ttk.Separator(self.left).pack(fill="x", pady=12)
        self.ttk.Label(self.left, text="小助手快捷输入").pack(anchor="w")
        self.quick_var = self.tk.StringVar()
        self.ttk.Entry(self.left, textvariable=self.quick_var, width=24).pack(fill="x", pady=4)
        self.ttk.Button(self.left, text="识别", command=self.handle_quick_input, style="Action.TButton").pack(fill="x")
        self.ttk.Button(self.left, text="复制结果给Codex", command=self.copy_for_codex, style="Action.TButton").pack(fill="x", pady=(12, 0))

        self.show_market()

    def clear_main(self) -> None:
        for child in self.main.winfo_children():
            child.destroy()

    def set_text(self, title: str, lines: list[str], params: dict[str, Any] | None = None) -> None:
        self.clear_main()
        self.ttk.Label(self.main, text=title, style="Header.TLabel").pack(anchor="w", pady=(0, 8))
        text = self.tk.Text(self.main, wrap="word", font=("Microsoft YaHei", 10), height=30, bg="#ffffff", fg="#111827", relief="solid", bd=1, padx=10, pady=10)
        text.pack(fill="both", expand=True)
        content = "\n".join(lines)
        text.insert("1.0", content)
        text.configure(state="disabled")
        self.current_result = f"{title}\n\n{content}"
        self.current_params = params or {}

    def show_market(self) -> None:
        payload = self.hub.market_payload()
        market = payload.get("market_score", {})
        features = market.get("features", {})
        top = payload.get("top10_sectors", [])[:5]
        lines = [
            f"最新缓存交易日：{payload.get('as_of_date', self.hub.latest_market_date)}",
            f"市场评分：{num(market.get('score'))}",
            f"市场等级：{market.get('grade', '-')}",
            f"环境判断：{market.get('grade', '-')}",
            f"上涨宽度：{pct(features.get('up_ratio'))}，上涨/下跌/平盘：{features.get('up_count', '-')}/{features.get('down_count', '-')}/{features.get('flat_count', '-')}",
            f"成交变化：成交额为5日均值的 {num(features.get('amount_vs_5d_avg'))} 倍",
            "前5板块：",
        ]
        if top:
            for item in top:
                lines.append(f"- {item.get('industry_name')}：{num(item.get('score'))} / {item.get('grade')}")
        else:
            df = self.hub.sectors().sort_values("score", ascending=False).head(5)
            for _, row in df.iterrows():
                lines.append(f"- {row['industry_name']}：{num(row['score'])} / {row['grade']}")
        score = market.get("score")
        tone = "以观察和结构性机会为主"
        try:
            if float(score) >= 70:
                tone = "环境较好，可主动寻找机会，但仍按板块和个股执行状态过滤"
            elif float(score) < 40:
                tone = "风险环境，优先控制风险"
        except Exception:
            pass
        lines.append(f"今日操作基调：{tone}")
        history = self.hub.market_history_lines(5)
        if history:
            lines.append("")
            lines.append("近5个交易日市场轨迹：")
            lines.extend(history)
        self.set_text("最新市场状态", lines, {"intent": "market", "date": payload.get("as_of_date")})

    def show_strong_sectors(self) -> None:
        df = self.hub.sectors().sort_values("score", ascending=False).head(20)
        lines = [f"最新缓存交易日：{self.hub.latest_sector_date}", "说明：以下为本地缓存评分结果，不是实时行情。", "强势板块前20："]
        for i, row in enumerate(df.itertuples(index=False), 1):
            lines.append(f"{i}. {row.industry_name}：{num(row.score)} / {row.grade}，扩散度 {pct(row.up_ratio)}，成交占比变化 {num(row.amount_share_change_ratio)}")
        self.set_text("找强势板块", lines, {"intent": "strong_sectors", "date": self.hub.latest_sector_date})

    def show_sector_page(self) -> None:
        self.clear_main()
        self.ttk.Label(self.main, text="查看板块核心股票", font=("Microsoft YaHei", 15, "bold")).pack(anchor="w", pady=(0, 8))
        top = self.ttk.Frame(self.main)
        top.pack(fill="x", pady=(0, 8))
        self.ttk.Label(top, text="板块关键词").pack(side="left")
        keyword_var = self.tk.StringVar()
        self.ttk.Entry(top, textvariable=keyword_var, width=24).pack(side="left", padx=6)
        sector_var = self.tk.StringVar()
        sectors = self.hub.sectors().sort_values("industry_name")
        names = sectors["industry_name"].astype(str).tolist()
        combo = self.ttk.Combobox(top, textvariable=sector_var, values=names, width=28)
        combo.pack(side="left", padx=6)
        if names:
            combo.set(names[0])
        result = self.tk.Text(self.main, wrap="word", font=("Microsoft YaHei", 10))
        result.pack(fill="both", expand=True)

        def render(name: str) -> None:
            row = sectors[sectors["industry_name"].astype(str) == name]
            result.configure(state="normal")
            result.delete("1.0", "end")
            if row.empty:
                matches = self.hub.search_sectors(name)
                if len(matches) > 1:
                    result.insert("1.0", "关键词匹配多个板块，请在下拉框中明确选择：\n" + "\n".join(matches["industry_name"].astype(str).head(20).tolist()))
                else:
                    result.insert("1.0", "未找到板块。")
                result.configure(state="disabled")
                return
            r = row.iloc[0]
            leaders = self.hub.leaders()
            block = leaders[leaders["sector_code"].astype(str) == str(r["index_code"])].sort_values("score", ascending=False).head(5)
            rank_df = self.hub.sectors().sort_values("score", ascending=False).reset_index(drop=True)
            rank = int(rank_df.index[rank_df["index_code"].astype(str) == str(r["index_code"])][0]) + 1 if str(r["index_code"]) in set(rank_df["index_code"].astype(str)) else "-"
            lines = [
                f"最新缓存交易日：{self.hub.latest_sector_date}",
                f"板块：{r['industry_name']}（{r['index_code']}）",
                f"评分和等级：{num(r['score'])} / {r['grade']}",
                f"全市场排名：{rank}",
                f"相对强度：{num(r.get('relative_strength_composite'))}",
                f"资金集中：成交占比变化 {num(r.get('amount_share_change_ratio'))}，绝对成交占比 {pct(r.get('amount_share'))}",
                f"扩散度：{pct(r.get('up_ratio'))}",
                f"持续性：跑赢市场 {r.get('outperform_market_days_5d', '-')}/5，扩散达标 {r.get('breadth_ge_50_days_5d', '-')}/5，成交占比上升 {r.get('amount_share_up_days_5d', '-')}/5",
                "龙头候选前5（若为空，表示当前缓存未产出该板块候选）：",
            ]
            for item in block.itertuples(index=False):
                lines.append(f"- {item.name} {item.ts_code}：{num(item.score)} / {item.grade} / {item.candidate_labels}")
            lines.append(f"基础行情风险：{r.get('risk_tips', '基础行情风险：未触发；事件风险：未检查或数据缺失')}")
            history = self.hub.sector_history_lines(str(r["industry_name"]), 5)
            if history:
                lines.append("")
                lines.append("近5个交易日板块轨迹：")
                lines.extend(history)
            lines.append("事件风险：未检查或数据缺失")
            text = "\n".join(lines)
            result.insert("1.0", text)
            result.configure(state="disabled")
            self.current_result = "查看板块核心股票\n\n" + text
            self.current_params = {"intent": "sector_core", "sector_name": str(r["industry_name"]), "sector_code": str(r["index_code"])}

        def search() -> None:
            matches = self.hub.search_sectors(keyword_var.get())
            if len(matches) == 1:
                combo.set(str(matches.iloc[0]["industry_name"]))
                render(combo.get())
            elif len(matches) > 1:
                combo["values"] = matches["industry_name"].astype(str).tolist()
                result.configure(state="normal")
                result.delete("1.0", "end")
                result.insert("1.0", "关键词匹配多个板块，请从下拉框中选择：\n" + "\n".join(matches["industry_name"].astype(str).head(30).tolist()))
                result.configure(state="disabled")
            else:
                render(keyword_var.get())

        self.ttk.Button(top, text="搜索", command=search).pack(side="left", padx=4)
        self.ttk.Button(top, text="查看", command=lambda: render(combo.get())).pack(side="left", padx=4)
        render(combo.get())

    def show_stock_wizard(self) -> None:
        self.clear_main()
        self.ttk.Label(self.main, text="查询某只股票", font=("Microsoft YaHei", 15, "bold")).pack(anchor="w", pady=(0, 8))
        form = self.ttk.Frame(self.main)
        form.pack(fill="x")
        stock_var = self.tk.StringVar()
        status_var = self.tk.StringVar(value="空仓")
        horizon_var = self.tk.StringVar(value="周度：未来5个交易日")
        goal_var = self.tk.StringVar(value="现在是否适合参与")
        cost_var = self.tk.StringVar()
        qty_var = self.tk.StringVar()
        pos_var = self.tk.StringVar()
        hold_var = self.tk.StringVar()
        note_var = self.tk.StringVar()
        candidate_var = self.tk.StringVar()
        candidates: list[tuple[str, str]] = []

        row = 0
        self.ttk.Label(form, text="股票名称或代码").grid(row=row, column=0, sticky="w", pady=4)
        stock_entry = self.ttk.Entry(form, textvariable=stock_var, width=28)
        stock_entry.grid(row=row, column=1, sticky="w", pady=4)
        candidate_combo = self.ttk.Combobox(form, textvariable=candidate_var, values=[], width=36)
        candidate_combo.grid(row=row, column=2, sticky="w", padx=8, pady=4)
        row += 1

        self.ttk.Label(form, text="当前状态").grid(row=row, column=0, sticky="w", pady=4)
        status_frame = self.ttk.Frame(form)
        status_frame.grid(row=row, column=1, columnspan=3, sticky="w")
        goals_by_status = {
            "空仓": ["现在是否适合参与", "是否等待回调", "是否加入观察"],
            "已持仓": ["是否继续持有", "是否减仓", "是否退出"],
            "准备卖出": ["现在处理", "等待反弹", "分批处理"],
            "仅观察": ["判断强弱和阶段", "查看风险"],
        }

        def update_goals() -> None:
            goal_combo["values"] = goals_by_status[status_var.get()]
            goal_var.set(goals_by_status[status_var.get()][0])

        for item in goals_by_status:
            self.ttk.Radiobutton(status_frame, text=item, value=item, variable=status_var, command=update_goals).pack(side="left", padx=4)
        row += 1

        self.ttk.Label(form, text="关注周期").grid(row=row, column=0, sticky="w", pady=4)
        horizon_frame = self.ttk.Frame(form)
        horizon_frame.grid(row=row, column=1, columnspan=3, sticky="w")
        for item in ["短线：未来1至3个交易日", "周度：未来5个交易日", "中期：未来2至4周"]:
            self.ttk.Radiobutton(horizon_frame, text=item, value=item, variable=horizon_var).pack(side="left", padx=4)
        row += 1

        self.ttk.Label(form, text="交易目标").grid(row=row, column=0, sticky="w", pady=4)
        goal_combo = self.ttk.Combobox(form, textvariable=goal_var, values=goals_by_status["空仓"], width=28)
        goal_combo.grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        hold_frame = self.ttk.LabelFrame(form, text="持仓信息（可留空）", padding=8)
        hold_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=8)
        for i, (label, var) in enumerate([("持仓成本", cost_var), ("持股数量", qty_var), ("仓位比例", pos_var), ("预计持有时间", hold_var)]):
            self.ttk.Label(hold_frame, text=label).grid(row=0, column=i * 2, sticky="w", padx=4)
            self.ttk.Entry(hold_frame, textvariable=var, width=14).grid(row=0, column=i * 2 + 1, sticky="w", padx=4)
        row += 1

        self.ttk.Label(form, text="补充说明").grid(row=row, column=0, sticky="w", pady=4)
        self.ttk.Entry(form, textvariable=note_var, width=80).grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        row += 1
        result = self.tk.Text(self.main, wrap="word", font=("Microsoft YaHei", 10))
        result.pack(fill="both", expand=True, pady=(10, 0))

        def resolve() -> None:
            nonlocal candidates
            query_text = stock_entry.get().strip() or stock_var.get().strip()
            matches = self.hub.resolve_stocks(query_text)
            candidates = [(str(r.ts_code), str(r.name)) for r in matches.itertuples(index=False)]
            candidate_combo["values"] = [f"{code} {name}" for code, name in candidates]
            if len(candidates) == 1:
                candidate_combo.set(f"{candidates[0][0]} {candidates[0][1]}")
            elif len(candidates) > 1:
                result.configure(state="normal")
                result.delete("1.0", "end")
                result.insert("1.0", "名称匹配多个股票，请从候选列表中选择：\n" + "\n".join(f"{c} {n}" for c, n in candidates[:30]))
                result.configure(state="disabled")
            else:
                result.configure(state="normal")
                result.delete("1.0", "end")
                result.insert("1.0", "未找到股票，请检查名称或代码。")
                result.configure(state="disabled")

        def run_query() -> None:
            selected = candidate_combo.get().strip() or candidate_var.get().strip()
            if not selected:
                resolve()
                selected = candidate_combo.get().strip() or candidate_var.get().strip()
            code = selected.split()[0] if selected else (stock_entry.get().strip() or stock_var.get().strip()).upper()
            result.configure(state="normal")
            result.delete("1.0", "end")

            holding = {
                "cost": cost_var.get().strip(),
                "quantity": qty_var.get().strip(),
                "position_ratio": pos_var.get().strip(),
                "expected_holding": hold_var.get().strip(),
                "note": note_var.get().strip(),
            }

            source = "决策样本"
            date, d = self.hub.decision_for_stock(code)
            if d is not None:
                payload = d
            else:
                score_date, score_row = self.hub.latest_stock_score_row(code)
                if score_row is not None:
                    source = "已有个股评分"
                    date = score_date
                    payload = pd.Series(self.hub.decision_like_for_stock_score(score_row))
                else:
                    score_date, score_row, message = self.hub.score_stock_on_demand(code)
                    if score_row is not None:
                        source = "按需离线评分"
                        date = score_date
                        payload = pd.Series(self.hub.decision_like_for_stock_score(score_row))
                    else:
                        base = self.hub.resolve_stocks(code)
                        base_name = str(base.iloc[0]["name"]) if len(base) else code
                        lines = [
                            f"股票：{base_name}（{code}）",
                            f"当前本地评分库暂未覆盖该股票。",
                            message,
                            "",
                            "近5个交易日原始行情：",
                        ]
                        price_history = self.hub.stock_price_history_lines(code, self.hub.latest_date, 5)
                        lines.extend(price_history or ["- 暂无可用原始行情。"])
                        lines.append("")
                        lines.append("说明：当前不会猜测正式评分结论；如需正式结论，请先补齐该股票所需上游评分数据。")
                        text = "\n".join(lines)
                        result.insert("1.0", text)
                        result.configure(state="disabled")
                        self.current_result = text
                        self.current_params = {
                            "intent": "stock_query",
                            "stock_code": code,
                            "position_status": status_var.get(),
                            "time_horizon": horizon_var.get(),
                            "trade_goal": goal_var.get(),
                            "holding": holding,
                            "supplement": note_var.get().strip(),
                            "covered": False,
                        }
                        return

            lines = self.stock_result_lines(payload, date, status_var.get(), horizon_var.get(), goal_var.get(), holding)
            lines.insert(2, f"结果来源：{source}")
            text = "\n".join(lines)
            result.insert("1.0", text)
            result.configure(state="disabled")
            self.current_result = text
            self.current_params = {
                "intent": "stock_query",
                "stock_code": code,
                "position_status": status_var.get(),
                "time_horizon": horizon_var.get(),
                "trade_goal": goal_var.get(),
                "holding": holding,
                "supplement": note_var.get().strip(),
                "covered": True,
                "source": source,
            }
        actions = self.ttk.Frame(form)
        actions.grid(row=row, column=0, columnspan=4, sticky="w", pady=8)
        self.ttk.Button(actions, text="查找股票", command=resolve).pack(side="left", padx=4)
        self.ttk.Button(actions, text="生成结果", command=run_query).pack(side="left", padx=4)

    def stock_result_lines(self, d: pd.Series, date: str, status: str, horizon: str, goal: str, holding: dict[str, str]) -> list[str]:
        lines = [
            f"股票：{d['name']}（{d['ts_code']}）",
            f"评分/缓存日期：{date}",
            f"用户状态：{status}；周期：{horizon}；目标：{goal}",
            f"当前市场环境：{num(d.get('market_score'))} / {d.get('market_grade', '-')}",
            f"所属板块及等级：{d.get('sector_name', '-')}，{num(d.get('sector_score'))} / {d.get('sector_grade', '-')}",
            f"股票核心身份：{num(d.get('leader_score'))} / {d.get('core_identity', '-')}",
            f"当前执行状态：{num(d.get('stock_score'))} / {d.get('stock_execution_status', '-')}",
            f"最终统一结论：{d.get('final_decision', '-')}",
            f"当前阶段：{d.get('current_stage', '-')}",
            "三项主要优势：" + ("；".join(split_items(d.get("advantages"))[:3]) or "暂无突出优势"),
            "三项主要风险：" + ("；".join(split_items(d.get("risks"))[:3]) or "基础行情风险：未触发"),
            "等待条件：" + ("；".join(split_items(d.get("wait_conditions"))[:3]) or "按既定风控观察"),
            "失效条件：" + ("；".join(split_items(d.get("invalid_conditions"))[:3]) or "-"),
            f"数据质量：{num(d.get('data_quality'))}",
            str(d.get("event_risk", "事件风险：未检查或数据缺失")),
        ]
        score_history = self.hub.stock_history_lines(str(d.get("ts_code", "")), 5)
        if score_history:
            lines.append("")
            lines.append("近5个交易日评分轨迹：")
            lines.extend(score_history)
        price_history = self.hub.stock_price_history_lines(str(d.get("ts_code", "")), date, 5)
        if price_history:
            lines.append("")
            lines.append("近5个交易日行情轨迹：")
            lines.extend(price_history)
        if status in {"已持仓", "准备卖出"}:
            cost = holding.get("cost")
            lines.append("")
            if cost:
                close = self.latest_close(str(d["ts_code"]), date)
                relation = "无法读取最新收盘价"
                try:
                    relation = f"最新收盘价 {close:.2f}，相对成本 {float(cost):.2f} 的浮动约 {((close / float(cost)) - 1) * 100:.2f}%"
                except Exception:
                    pass
                lines.append(f"成本与收盘价关系：{relation}")
            else:
                lines.append("持仓信息未完整填写：当前只输出行情与结构判断，不提供个性化持仓处理建议。")
            lines.append("持仓信息已记录，但当前版本尚未完成个性化持仓管理。")
        if holding.get("note"):
            lines.append(f"补充说明：{holding['note']}")
        return lines
    def latest_close(self, code: str, date: str) -> float:
        with sqlite3.connect(SQLITE) as conn:
            row = conn.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date=?", (code, date)).fetchone()
        if not row:
            raise ValueError("missing close")
        return float(row[0])

    def show_opportunities(self) -> None:
        self.show_decision_list(["READY_CORE", "READY_SECONDARY", "WAIT_PULLBACK_CORE"], "模拟机会")

    def show_risks(self) -> None:
        self.show_decision_list(["WEAK_STRUCTURE", "AVOID", "DATA_INSUFFICIENT"], "风险和回避名单")

    def show_decision_list(self, decisions: list[str], title: str) -> None:
        df = self.hub.decisions()
        subset = df[df["final_decision"].isin(decisions)].copy()
        lines = [
            f"模拟样本日期：{self.hub.latest_decision_date}",
            "说明：以下来自每日模拟样本，不是全市场实时扫描；READY_CORE优先级最高，READY_SECONDARY是非核心候选，WAIT_PULLBACK_CORE不等于立即买入。",
            "",
        ]
        for decision in decisions:
            block = subset[subset["final_decision"] == decision]
            lines.append(f"{decision}：{len(block)}只")
            for row in block.sort_values("stock_score", ascending=False).head(20).itertuples(index=False):
                reason = getattr(row, "risks", "") or getattr(row, "current_stage", "")
                lines.append(f"- {row.name} {row.ts_code}：{num(row.stock_score)}，{row.sector_name}，{reason}")
            lines.append("")
        self.set_text(title, lines, {"intent": "decision_list", "decisions": decisions, "date": self.hub.latest_decision_date})

    def handle_quick_input(self) -> None:
        text = self.quick_var.get().strip()
        if not text:
            self.set_text("小助手快捷输入", ["我没有完全理解，请使用上方选项选择查询类型。"])
            return
        if "机会" in text:
            self.show_opportunities()
        elif any(k in text for k in ["回避", "风险"]):
            self.show_risks()
        elif "板块" in text:
            key = text.replace("板块", "").strip()
            matches = self.hub.search_sectors(key)
            if len(matches) == 1:
                self.show_sector_text(str(matches.iloc[0]["industry_name"]))
            elif len(matches) > 1:
                self.set_text("板块候选", ["关键词匹配多个板块，请使用“查看板块核心股票”页面选择："] + matches["industry_name"].astype(str).head(20).tolist(), {"intent": "sector_ambiguous", "keyword": key})
            else:
                self.set_text("小助手快捷输入", ["我没有完全理解，请使用上方选项选择查询类型。"])
        else:
            matches = self.hub.resolve_stocks(text.replace("怎么样", "").strip())
            if len(matches) == 1:
                code = str(matches.iloc[0]["ts_code"])
                date, d = self.hub.decision_for_stock(code)
                if d is not None:
                    self.set_text("股票快捷查询", self.stock_result_lines(d, date, "仅观察", "周度：未来5个交易日", "判断强弱和阶段", {}), {"intent": "quick_stock", "stock_code": code})
                else:
                    score_date, score_row = self.hub.latest_stock_score_row(code)
                    if score_row is None:
                        score_date, score_row, _ = self.hub.score_stock_on_demand(code)
                    if score_row is not None:
                        payload = pd.Series(self.hub.decision_like_for_stock_score(score_row))
                        self.set_text("股票快捷查询", self.stock_result_lines(payload, score_date, "仅观察", "周度：未来5个交易日", "判断强弱和阶段", {}), {"intent": "quick_stock", "stock_code": code})
                    else:
                        self.set_text("股票快捷查询", [f"当前本地评分库暂未覆盖 {code}，请使用“查询某只股票”向导继续查看基础行情。"])
            elif len(matches) > 1:
                self.set_text("股票候选", ["名称匹配多个股票，请使用“查询某只股票”页面选择："] + [f"{r.ts_code} {r.name}" for r in matches.head(20).itertuples(index=False)])
            else:
                self.set_text("小助手快捷输入", ["我没有完全理解，请使用上方选项选择查询类型。"])

    def show_sector_text(self, name: str) -> None:
        df = self.hub.sectors()
        row = df[df["industry_name"].astype(str) == name]
        if row.empty:
            self.set_text("板块查询", ["未找到板块。"])
            return
        r = row.iloc[0]
        lines = [
            f"板块：{r['industry_name']}",
            f"评分：{num(r['score'])} / {r['grade']}",
            f"扩散度：{pct(r['up_ratio'])}",
            f"成交占比变化：{num(r['amount_share_change_ratio'])}",
            "如需查看龙头候选，请使用“查看板块核心股票”。",
        ]
        history = self.hub.sector_history_lines(name, 5)
        if history:
            lines.append("")
            lines.append("近5个交易日板块轨迹：")
            lines.extend(history)
        self.set_text("板块快捷查询", lines, {"intent": "quick_sector", "sector_name": name})
    def copy_for_codex(self) -> None:
        payload = {
            "structured_params": self.current_params,
            "result": self.current_result,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.set_text("复制结果给Codex", ["已复制当前查询结果和结构化参数到剪贴板。", "", text], {"intent": "copy_for_codex"})

    def run_update_data(self) -> None:
        self.run_command("run_update.bat", "更新今日数据")

    def run_daily_simulation(self) -> None:
        self.run_command("run_daily_simulation.bat", "运行每日模拟")

    def run_command(self, command: str, title: str) -> None:
        try:
            subprocess.Popen(str(ROOT / command), cwd=ROOT, shell=True)
            self.set_text(title, [f"已启动：{command}", "运行完成后请查看对应报告。"])
        except Exception as exc:
            self.set_text(title, [f"启动失败：{type(exc).__name__}: {exc}"])

    def open_reports(self) -> None:
        path = REPORTS / "simulation" / "latest_run_status.html"
        if not path.exists():
            path = REPORTS / "simulation" / "latest_run_status.md"
        try:
            os.startfile(path)
            self.set_text("打开详细报告", [f"已打开：{path}"])
        except Exception as exc:
            self.set_text("打开详细报告", [f"打开失败：{type(exc).__name__}: {exc}", f"路径：{path}"])

    def run(self) -> None:
        self.root.mainloop()


def self_test() -> dict[str, Any]:
    hub = DataHub()
    market = hub.market_payload()
    sectors = hub.search_sectors("半导体")
    stocks = {
        "晶瑞电材": len(hub.resolve_stocks("晶瑞电材")),
        "有研新材": len(hub.resolve_stocks("有研新材")),
    }
    fuzzy = hub.search_sectors("电子")
    decisions = hub.decisions()
    return {
        "latest_date": hub.latest_date,
        "market_loaded": bool(market),
        "sector_semiconductor_matches": len(sectors),
        "stock_lookup": stocks,
        "fuzzy_sector_matches": len(fuzzy),
        "decision_rows": len(decisions),
        "ready_core": int((decisions["final_decision"] == "READY_CORE").sum()) if len(decisions) else 0,
        "wait_pullback_core": int((decisions["final_decision"] == "WAIT_PULLBACK_CORE").sum()) if len(decisions) else 0,
        "risk_rows": int(decisions["final_decision"].isin(["WEAK_STRUCTURE", "AVOID", "DATA_INSUFFICIENT"]).sum()) if len(decisions) else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    StockAssistantApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())













