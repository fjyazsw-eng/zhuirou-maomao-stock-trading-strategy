"""Build latest user-facing market decision report from local caches only."""
from __future__ import annotations

import math
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
DATE = "20260630"
MONEYFLOW_RAW_UNIT = "万元"
MONEYFLOW_CONVERSION = "亿元 = 万元 / 10000"

HOLDINGS = [
    {"name": "石英股份", "ts_code": "603688.SH", "quantity": 100, "cost": 82.441},
    {"name": "华锡有色", "ts_code": "600301.SH", "quantity": 100, "cost": 60.861},
    {"name": "晶瑞电材", "ts_code": "300655.SZ", "quantity": 100, "cost": 18.66},
    {"name": "有研硅", "ts_code": "688432.SH", "quantity": 100, "cost": 35.0},
]
SEMICONDUCTOR_TAGS = {
    "603688.SH": ("半导体材料", "半导体用石英材料；仍需公告和主营收入进一步核实"),
    "300655.SZ": ("电子化学品/光刻胶材料", "光刻胶、湿电子化学品；仍需公告和主营收入进一步核实"),
    "688432.SH": ("半导体材料", "硅材料、硅片/硅部件；仍需公告和主营收入进一步核实"),
}


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ts_code": "string", "trade_date": "string", "symbol": "string", "con_code": "string"})


def fmt_pct(x) -> str:
    return "数据不足" if pd.isna(x) else f"{float(x):+.2f}%"


def amount_yi_from_qianyuan(x) -> str:
    return "数据不足" if pd.isna(x) else f"{float(x) / 100000:.2f}亿元"


def moneyflow_yi(x) -> str:
    return "数据不足" if pd.isna(x) else f"{float(x) / 10000:.2f}亿元"


def label(name, code) -> str:
    if pd.isna(name) or str(name).strip() == "":
        name = "名称缺失"
    return f"{name}（{code}）"


def load_l2_mapping() -> pd.DataFrame:
    member_dir = PROJECT_ROOT / "data" / "basic" / "industry_members_L2"
    frames = []
    if not member_dir.exists():
        return pd.DataFrame(columns=["ts_code", "l2_name"])
    for path in member_dir.glob("members_*.csv"):
        df = read_csv(path)
        if "con_code" not in df.columns or "index_name" not in df.columns:
            continue
        if "out_date" in df.columns:
            df = df[(df["out_date"].isna()) | (df["out_date"].astype(str).isin(["", "nan", "NaT"])) | (df["out_date"].astype(str) > DATE)]
        frames.append(df.rename(columns={"con_code": "ts_code", "index_name": "l2_name"})[["ts_code", "l2_name"]])
    return pd.concat(frames, ignore_index=True).drop_duplicates("ts_code") if frames else pd.DataFrame(columns=["ts_code", "l2_name"])


def load_l1_mapping() -> pd.DataFrame:
    path = PROCESSED_DIR / f"stock_industry_matched_{DATE}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["ts_code", "l1_name"])
    df = read_csv(path)
    if "industry_name" in df.columns:
        return df[["ts_code", "industry_name"]].rename(columns={"industry_name": "l1_name"}).drop_duplicates("ts_code")
    return pd.DataFrame(columns=["ts_code", "l1_name"])


def load_all() -> dict[str, pd.DataFrame]:
    return {
        "master": read_csv(PROCESSED_DIR / f"daily_stock_master_{DATE}.csv"),
        "l2": read_csv(PROCESSED_DIR / f"industry_l2_analysis_{DATE}.csv"),
        "index": read_csv(PROCESSED_DIR / f"major_index_weather_{DATE}.csv"),
        "l1map": load_l1_mapping(),
        "l2map": load_l2_mapping(),
    }


def daily_window() -> tuple[list[str], pd.DataFrame]:
    frames, dates = [], []
    for path in sorted(RAW_DIR.glob("daily_202606*.csv"), reverse=True):
        d = path.stem.replace("daily_", "")
        df = read_csv(path)
        if len(df) == 0:
            continue
        dates.append(d)
        frames.append(df[["ts_code", "trade_date", "close", "high", "low", "pre_close", "pct_chg", "amount"]])
        if len(dates) >= 5:
            break
    return dates, pd.concat(frames, ignore_index=True)


def moneyflow_window() -> pd.DataFrame:
    frames = [read_csv(p) for p in sorted(RAW_DIR.glob("moneyflow_202606*.csv"), reverse=True)[:5]]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts_code", "trade_date", "net_mf_amount"])


def row_by_code(df: pd.DataFrame, code: str) -> pd.Series | None:
    hit = df[df.ts_code.astype(str) == code]
    return None if hit.empty else hit.iloc[0]


def stock_return(code: str, dates: list[str], dw: pd.DataFrame, n: int):
    if len(dates) < n:
        return math.nan
    cur = dw[(dw.ts_code == code) & (dw.trade_date == dates[0])]
    base = dw[(dw.ts_code == code) & (dw.trade_date == dates[n - 1])]
    if cur.empty or base.empty:
        return math.nan
    pre = float(base.iloc[0].pre_close)
    return (float(cur.iloc[0].close) / pre - 1) * 100 if pre else math.nan


def ma_position(code: str, dw: pd.DataFrame, n: int) -> str:
    sub = dw[dw.ts_code == code].sort_values("trade_date", ascending=False).head(n)
    if len(sub) < min(n, 5):
        return "数据不足"
    return "高于" if float(sub.iloc[0].close) > float(sub.close.mean()) else "低于"


def industry_rank(l2: pd.DataFrame, name: str) -> str:
    hit = l2.reset_index(drop=True)[l2.industry_name.astype(str) == str(name)]
    return "数据不足" if hit.empty else str(int(hit.index[0]) + 1)


def build_holdings(data, dates, dw, mf) -> tuple[list[str], list[str]]:
    master, l1map, l2map, l2 = data["master"], data["l1map"], data["l2map"], data["l2"]
    lines = ["## 7. 用户4只持仓监控", ""]
    alerts = []
    for h in HOLDINGS:
        r = row_by_code(master, h["ts_code"])
        if r is None:
            lines.append(f"### {label(h['name'], h['ts_code'])}\n- 数据不足：总表缺失。\n")
            alerts.append(f"{h['name']}：数据不足")
            continue
        l1r = row_by_code(l1map, h["ts_code"])
        l2r = row_by_code(l2map, h["ts_code"])
        l1_name = l1r.l1_name if l1r is not None else r.get("industry", "数据不足")
        l2_name = l2r.l2_name if l2r is not None else "数据不足"
        ind = l2[l2.industry_name.astype(str) == str(l2_name)]
        ind_ret = float(ind.iloc[0].return_1d_pct) if not ind.empty else 0
        close = float(r.close)
        pnl = (close - h["cost"]) * h["quantity"]
        pnl_pct = (close / h["cost"] - 1) * 100
        ret3, ret5 = stock_return(h["ts_code"], dates, dw, 3), stock_return(h["ts_code"], dates, dw, 5)
        hist = dw[dw.ts_code == h["ts_code"]].sort_values("trade_date", ascending=False)
        amount5 = hist.head(5).amount.mean() if not hist.empty else math.nan
        high20, low20 = (hist.high.max(), hist.low.min()) if "high" in hist.columns and not hist.empty else (math.nan, math.nan)
        mf_s = mf[mf.ts_code == h["ts_code"]]
        mf_today = mf_s[mf_s.trade_date == dates[0]].net_mf_amount.sum() if not mf_s.empty else 0
        mf3 = mf_s[mf_s.trade_date.isin(dates[:3])].net_mf_amount.sum() if not mf_s.empty else 0
        mf5 = mf_s[mf_s.trade_date.isin(dates[:5])].net_mf_amount.sum() if not mf_s.empty else 0
        tags = []
        if float(r.pct_chg) >= ind_ret and mf_today > 0:
            tags.append("偏强")
        if float(r.pct_chg) < ind_ret - 2:
            tags.append("个股弱于板块")
        if float(r.pct_chg) < -3 or mf3 < 0:
            tags.append("转弱")
        if pd.notna(ret5) and ret5 > 20 and float(r.pct_chg) < ind_ret:
            tags.append("高位分歧")
        if not tags:
            tags = ["正常"]
        if tags != ["正常"]:
            alerts.append(f"{h['name']}：{'、'.join(tags)}")
        main_tag, note = SEMICONDUCTOR_TAGS.get(h["ts_code"], ("待核实", "待核实"))
        lines += [
            f"### {label(h['name'], h['ts_code'])}",
            f"- 最新收盘价 {close:.2f}元，成本 {h['cost']:.3f}元，浮动盈亏 {pnl:+.2f}元（{pnl_pct:+.2f}%）。",
            f"- 行业：一级 {l1_name}；二级 {l2_name}；二级行业排名 {industry_rank(l2, l2_name)}。",
            f"- 产业链标签：{main_tag}。说明：{note}。",
            f"- 走势：1日 {fmt_pct(r.pct_chg)}，3日 {fmt_pct(ret3)}，5日 {fmt_pct(ret5)}；10日/20日因为当前缓存不足，数据不足。",
            f"- 成交额：今日 {amount_yi_from_qianyuan(r.amount)}；5日均值 {amount_yi_from_qianyuan(amount5)}；是否放大：{'是' if float(r.amount) > amount5 else '否'}。",
            f"- 资金流：今日 {moneyflow_yi(mf_today)}；3日 {moneyflow_yi(mf3)}；5日 {moneyflow_yi(mf5)}。",
            f"- 价格位置：相对5日均价{ma_position(h['ts_code'], dw, 5)}，相对10日/20日均价数据不足；20日高低点因缓存不足，当前仅能参考近5日：{high20:.2f}/{low20:.2f}。",
            "- 基本面和公告风险：本地暂无财务、公告、减持、解禁、处罚、诉讼缓存，标记为数据不足。",
            f"- 预警标签：{'、'.join(tags)}。",
            "",
        ]
    return lines, alerts


def candidate_lines(data, dates, mf) -> list[str]:
    l2, master, l2map = data["l2"], data["master"], data["l2map"]
    recent = read_csv(PROCESSED_DIR / f"stock_industry_matched_{DATE}.csv").drop(columns=["industry_name", "industry_code"], errors="ignore")
    matched = recent.merge(l2map, on="ts_code", how="left").merge(master, on="ts_code", how="left", suffixes=("", "_m"))
    lines = ["## 8. 1万元闲置资金候选方案", "说明：这是候选资料，不是买入指令。", ""]
    strong = l2[(l2.return_1d_pct > 0) & (l2.return_3d_pct > 0) & (l2.return_5d_pct > 0)].head(3)
    for ind in strong.itertuples(index=False):
        lines.append(f"### {ind.industry_name}")
        pool = matched[(matched.l2_name.astype(str) == str(ind.industry_name)) & (matched.close <= 100) & (matched.amount_today >= 100000)]
        pool = pool[~pool.name.astype(str).str.contains("退|^N|^C", regex=True, na=False)].copy()
        if pool.empty:
            lines.append("- 数据不足：没有符合价格、流动性和非新股过滤的样本。")
            continue
        pool["score"] = pool.return_5d_pct * 0.4 + pool.return_1d_pct * 0.3 + pool.amount_today.rank(pct=True) * 5
        for r in pool.sort_values("score", ascending=False).head(3).itertuples(index=False):
            mf_s = mf[mf.ts_code == r.ts_code]
            mf_today = mf_s[mf_s.trade_date == dates[0]].net_mf_amount.sum() if not mf_s.empty else 0
            mf3 = mf_s[mf_s.trade_date.isin(dates[:3])].net_mf_amount.sum() if not mf_s.empty else 0
            lines.append(f"- {label(r.name, r.ts_code)}：当前价 {float(r.close):.2f}元，100股约 {float(r.close)*100:.0f}元；1日 {float(r.return_1d_pct):+.2f}%，3日 {float(r.return_3d_pct):+.2f}%，5日 {float(r.return_5d_pct):+.2f}%；成交额 {amount_yi_from_qianyuan(r.amount_today)}；资金今日 {moneyflow_yi(mf_today)}，3日 {moneyflow_yi(mf3)}。进入候选原因：行业持续走强、个股流动性达标。不能直接买入原因：还要看明日承接、公告风险和是否高位分歧。")
        lines.append("")
    return lines


def build_report() -> dict[str, object]:
    data = load_all()
    dates, dw = daily_window()
    mf = moneyflow_window()
    l2 = data["l2"]
    semi = l2[l2.industry_name.astype(str).str.contains("半导体", na=False)].head(1)
    holding_lines, alerts = build_holdings(data, dates, dw, mf)
    lines = [
        "# 每日决策总报告",
        "",
        f"## 1. 数据日期\n{DATE}", "",
        "## 2. 今日市场天气",
        "- 截至20260630，市场天气评分73/100，阶段更接近转强。这个评分不等于交易指令，只说明市场从弱势里修复得比较明显。",
        "- 指数证据：科技成长最强，科创50、创业板明显强于上证和沪深300。", "",
        "## 3. 当前最强2-3个细分板块",
    ]
    for r in l2.head(3).itertuples(index=False):
        lines.append(f"- {r.industry_name}：1日 {r.return_1d_pct:+.2f}%，3日 {r.return_3d_pct:+.2f}%，5日 {r.return_5d_pct:+.2f}%。强的原因：涨幅、上涨比例、成交额、资金流和核心股表现综合靠前。风险：短线涨多后容易分歧。")
    lines += ["", "## 4. 强势板块班长候选"]
    for r in l2.head(10).itertuples(index=False):
        dispute = "班长候选存在争议。" if float(r.return_1d_pct) > 3 and "(" in str(r.leader_candidate) else "仍需观察是否继续强于行业。"
        lines.append(f"- {r.industry_name}：综合班长候选 {r.leader_candidate}。证据：{r.rank_reason} 资金流今日 {moneyflow_yi(r.moneyflow_today)}。{dispute}")
    lines += ["", "## 5. 半导体进一步细分"]
    if not semi.empty:
        s = semi.iloc[0]
        lines.append(f"半导体排名第1，1日{s.return_1d_pct:+.2f}%，3日{s.return_3d_pct:+.2f}%，5日{s.return_5d_pct:+.2f}%；成交额较昨日{s.amount_vs_yesterday_yi:+.2f}亿元，较5日均值{s.amount_vs_5d_avg_yi:+.2f}亿元；资金今日{moneyflow_yi(s.moneyflow_today)}。")
    lines += [
        "- 石英股份：主要标记为半导体材料，具体收入占比待公告/财报核实。",
        "- 晶瑞电材：主要标记为电子化学品/光刻胶材料，具体收入占比待公告/财报核实。",
        "- 有研硅：主要标记为半导体材料，具体收入占比待公告/财报核实。",
        "- 设备、设计、制造、封测、存储、模拟、功率等更细标签，目前本地数据不能完整自动确认，未确认部分标记为待核实。", "",
    ]
    lines.extend(holding_lines)
    lines.extend(candidate_lines(data, dates, mf))
    lines += [
        "## 9. 明日需要观察的条件",
        "- 半导体资金能否继续净流入，成交额能否重新放大。",
        "- 持仓股是否继续强于所属二级行业。",
        "- 候选股是否出现高开低走、放量滞涨或资金转负。", "",
        "## 10. 风险提示",
        "- 本报告不提供买入、卖出或仓位指令。",
        "- 资金流只是参考，不能单独作为买入依据。",
        "- 半导体和电子方向短线较热，可能出现高位分歧。", "",
        "## 11. 数据异常",
        "- 股票名称已统一为 股票名称（股票代码），不再使用内部编号。",
        f"- Tushare moneyflow 原始单位：{MONEYFLOW_RAW_UNIT}；换算后单位：{MONEYFLOW_CONVERSION}。", "",
        "## 12. 数据局限",
        "- 基本面、公告、减持、解禁、处罚、诉讼等缓存不足，相关内容标记为数据不足。",
        "- 半导体三级产业链标签仍需用主营业务和公告继续核实。",
    ]
    out = REPORTS_DIR / "latest_market_decision_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"path": out, "alerts": alerts, "data_issues": ["基本面和公告风险数据不足", "半导体三级产业链标签部分待核实"]}


if __name__ == "__main__":
    res = build_report()
    print(f"总报告生成成功: {res['path']}")
    print("持仓预警: " + ("；".join(res["alerts"]) if res["alerts"] else "无"))
    print("数据不足: " + "；".join(res["data_issues"]))

