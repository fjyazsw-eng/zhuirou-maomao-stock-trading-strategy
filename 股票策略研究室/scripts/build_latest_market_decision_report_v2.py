"""Build latest concise market decision report v2.

Data-only report. No trading instruction. No token printing.
"""
from __future__ import annotations

import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
BASIC_DIR = PROJECT_ROOT / "data" / "basic"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
DATE = "20260630"
SLEEP_SECONDS = 1.5

HOLDINGS = [
    {"name": "石英股份", "ts_code": "603688.SH", "quantity": 100, "cost": 82.441},
    {"name": "华锡有色", "ts_code": "600301.SH", "quantity": 100, "cost": 60.861},
    {"name": "晶瑞电材", "ts_code": "300655.SZ", "quantity": 100, "cost": 18.66},
    {"name": "有研硅", "ts_code": "688432.SH", "quantity": 100, "cost": 35.0},
]

SEMICONDUCTOR_TAGS = {
    "603688.SH": ("半导体材料", "石英材料/半导体用石英制品，主营占比仍需公告核实"),
    "300655.SZ": ("电子化学品/光刻胶材料", "光刻胶、湿电子化学品，主营占比仍需公告核实"),
    "688432.SH": ("半导体材料", "硅材料/硅片相关，主营占比仍需公告核实"),
}


def pro_api():
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 不存在")
    return ts.pro_api(token)


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"ts_code":"string","trade_date":"string","symbol":"string","con_code":"string","ann_date":"string","end_date":"string"})


def label(name, code):
    return f"{name if not pd.isna(name) and str(name).strip() else '名称缺失'}（{code}）"


def pct(x):
    return "数据不足" if x is None or pd.isna(x) else f"{float(x):+.2f}%"


def qianyuan_to_yi(x):
    return "数据不足" if x is None or pd.isna(x) else f"{float(x)/100000:.2f}亿元"


def wanyuan_to_yi(x):
    return "数据不足" if x is None or pd.isna(x) else f"{float(x)/10000:.2f}亿元"


def stock_daily_cache_path(code: str):
    return RAW_DIR / f"stock_daily_25d_{code.replace('.', '_')}_{DATE}.csv"


def load_stock_daily_25d(code: str, pro) -> tuple[pd.DataFrame, str]:
    path = stock_daily_cache_path(code)
    fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
    if path.exists():
        df = read_csv(path)
        if len(df) >= 25 and all(c in df.columns for c in fields.split(',')):
            return df.sort_values("trade_date", ascending=False), "本地缓存"
    end = datetime.strptime(DATE, "%Y%m%d")
    start = (end - timedelta(days=70)).strftime("%Y%m%d")
    time.sleep(SLEEP_SECONDS)
    df = pro.daily(ts_code=code, start_date=start, end_date=DATE, fields=fields)
    df = df.sort_values("trade_date", ascending=False).head(25)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df, "Tushare daily"


def ret_from(df: pd.DataFrame, n: int):
    if len(df) < n:
        return math.nan
    cur = float(df.iloc[0].close)
    pre = float(df.iloc[n-1].pre_close)
    return (cur/pre - 1)*100 if pre else math.nan


def ma(df: pd.DataFrame, n: int):
    return float(df.head(n).close.mean()) if len(df) >= n else math.nan


def high_low_20(df: pd.DataFrame):
    if len(df) < 20:
        return math.nan, math.nan
    sub = df.head(20)
    return float(sub.high.max()), float(sub.low.min())


def load_l2_mapping():
    member_dir = BASIC_DIR / "industry_members_L2"
    frames=[]
    for p in member_dir.glob("members_*.csv") if member_dir.exists() else []:
        df=read_csv(p)
        if "con_code" in df.columns and "index_name" in df.columns:
            if "out_date" in df.columns:
                df=df[(df.out_date.isna()) | (df.out_date.astype(str).isin(["","nan","NaT"])) | (df.out_date.astype(str)>DATE)]
            df = df.rename(columns={"con_code":"ts_code","index_name":"l2_name"})[["ts_code","l2_name"]]
            df["l2_name"] = df["l2_name"].astype(str).str.replace("(申万)", "", regex=False)
            frames.append(df)
    return pd.concat(frames, ignore_index=True).drop_duplicates("ts_code") if frames else pd.DataFrame(columns=["ts_code","l2_name"])


def load_l1_mapping():
    p=PROCESSED_DIR / f"stock_industry_matched_{DATE}.csv"
    if not p.exists(): return pd.DataFrame(columns=["ts_code","l1_name"])
    df=read_csv(p)
    return df[["ts_code","industry_name"]].rename(columns={"industry_name":"l1_name"}).drop_duplicates("ts_code") if "industry_name" in df.columns else pd.DataFrame(columns=["ts_code","l1_name"])


def moneyflow_window():
    frames=[read_csv(p) for p in sorted(RAW_DIR.glob("moneyflow_202606*.csv"), reverse=True)[:5]]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts_code","trade_date","net_mf_amount"])


def fundamentals(code: str, pro):
    out = {"revenue":"数据不足", "profit":"数据不足", "cashflow":"数据不足", "debt":"数据不足", "loss":"数据不足", "decline":"数据不足", "ann":"数据不足"}
    cache = BASIC_DIR / "fundamentals" / f"fundamental_{code.replace('.', '_')}.txt"
    if cache.exists():
        text = cache.read_text(encoding="utf-8")
        text = re.sub(r"收入较上一期变化 [^。]+。", "财务变化口径待核实：当前未确认去年同期同口径数据，不输出同比百分比。", text)
        text = re.sub(r"净利润较上一期变化 [^。]+。", "", text)
        return text
    notes=[]
    try:
        time.sleep(SLEEP_SECONDS)
        inc=pro.income(ts_code=code, start_date="20250101", end_date=DATE, fields="ts_code,end_date,ann_date,total_revenue,n_income_attr_p")
        if len(inc):
            inc=inc.sort_values("end_date", ascending=False)
            latest=inc.iloc[0]
            notes.append(f"最近一期收入 {latest.get('total_revenue','数据不足')}；归母净利润 {latest.get('n_income_attr_p','数据不足')}。")
            notes.append("财务变化口径待核实：当前未确认去年同期同口径数据，不输出同比百分比。")
            notes.append("是否亏损：" + ("是" if float(latest.n_income_attr_p)<0 else "否"))
    except Exception as e:
        notes.append(f"利润表接口失败：{str(e)[:80]}")
    try:
        time.sleep(SLEEP_SECONDS)
        cf=pro.cashflow(ts_code=code, start_date="20250101", end_date=DATE, fields="ts_code,end_date,n_cashflow_act")
        if len(cf): notes.append(f"经营现金流净额：{cf.sort_values('end_date', ascending=False).iloc[0].get('n_cashflow_act','数据不足')}。")
    except Exception as e:
        notes.append(f"现金流接口失败：{str(e)[:80]}")
    try:
        time.sleep(SLEEP_SECONDS)
        bs=pro.balancesheet(ts_code=code, start_date="20250101", end_date=DATE, fields="ts_code,end_date,total_assets,total_liab")
        if len(bs):
            b=bs.sort_values('end_date', ascending=False).iloc[0]
            ratio=float(b.total_liab)/float(b.total_assets)*100 if float(b.total_assets) else math.nan
            notes.append(f"资产负债率约 {pct(ratio)}。")
    except Exception as e:
        notes.append(f"资产负债表接口失败：{str(e)[:80]}")
    try:
        time.sleep(SLEEP_SECONDS)
        ann=pro.anns(ts_code=code, start_date="20260601", end_date=DATE, fields="ts_code,ann_date,ann_type,title")
        if len(ann):
            titles="；".join(ann.sort_values('ann_date', ascending=False).head(3).title.astype(str).tolist())
            notes.append(f"近期公告：{titles}")
        else:
            notes.append("近期公告：未取得公开公告记录。")
    except Exception as e:
        notes.append(f"公告接口失败或权限不足：{str(e)[:80]}")
    text=" ".join(notes) if notes else "数据不足"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def row_by_code(df, code):
    hit=df[df.ts_code.astype(str)==code]
    return None if hit.empty else hit.iloc[0]


def leader_block(industry_row, matched, master, mf):
    name=industry_row.industry_name
    pool=matched[matched.l2_name.astype(str)==str(name)].merge(master, on="ts_code", how="left", suffixes=("","_m"))
    if pool.empty:
        return f"- {name}：行业成分数据不足。"
    mf_today=mf[mf.trade_date==DATE]
    pool_mf=pool.merge(mf_today[["ts_code","net_mf_amount"]], on="ts_code", how="left")
    up=pool_mf.sort_values("return_1d_pct", ascending=False).iloc[0]
    amt=pool_mf.sort_values("amount_today", ascending=False).iloc[0]
    flow=pool_mf.sort_values("net_mf_amount", ascending=False).iloc[0]
    trend=pool_mf.sort_values("return_5d_pct", ascending=False).iloc[0]
    third = flow if float(flow.get("net_mf_amount", 0) or 0) >= float(trend.get("net_mf_amount", 0) or 0) else trend
    return f"- {name}：涨幅核心 {label(up['name'], up.ts_code)}；成交核心 {label(amt['name'], amt.ts_code)}；趋势/资金核心 {label(third['name'], third.ts_code)}。"


def holdings_section(data, pro, mf):
    master,l1map,l2map,l2=data['master'],data['l1map'],data['l2map'],data['l2']
    lines=["## 4. 四只持仓监控和风险",""]
    alerts=[]; ok_20=True; fund_missing=[]
    for h in HOLDINGS:
        r=row_by_code(master,h['ts_code'])
        sd,src=load_stock_daily_25d(h['ts_code'], pro)
        if len(sd)<25: ok_20=False
        close=float(sd.iloc[0].close) if len(sd) else (float(r.close) if r is not None else math.nan)
        ret1=float(sd.iloc[0].pct_chg) if len(sd) else math.nan
        ret3,ret5,ret10,ret20=ret_from(sd,3),ret_from(sd,5),ret_from(sd,10),ret_from(sd,20)
        ma5,ma10,ma20=ma(sd,5),ma(sd,10),ma(sd,20)
        hi20,lo20=high_low_20(sd)
        near_high=(close/hi20-1)*100 if hi20 and not math.isnan(hi20) else math.nan
        dev20=(close/ma20-1)*100 if ma20 and not math.isnan(ma20) else math.nan
        l1r=row_by_code(l1map,h['ts_code']); l2r=row_by_code(l2map,h['ts_code'])
        l1n=l1r.l1_name if l1r is not None else (r.industry if r is not None and 'industry' in r else '数据不足')
        l2n=l2r.l2_name if l2r is not None else '数据不足'
        ind=l2[l2.industry_name.astype(str)==str(l2n)]
        ind_ret=float(ind.iloc[0].return_1d_pct) if len(ind) else 0
        mfs=mf[mf.ts_code==h['ts_code']]
        mf_today=float(mfs[mfs.trade_date==DATE].net_mf_amount.sum()) if len(mfs) else 0
        mf3=float(mfs.head(3).net_mf_amount.sum()) if len(mfs) else 0
        mf5=float(mfs.head(5).net_mf_amount.sum()) if len(mfs) else 0
        tags=[]
        if ret1 < ind_ret-2: tags.append("个股弱于板块")
        if (not math.isnan(ret3) and ret3>15) or (not math.isnan(ret5) and ret5>20): tags.append("高位分歧观察")
        if (not math.isnan(ret3) and ret3>30) or (not math.isnan(ret5) and ret5>40):
            tags.append("高位加速")
            tags.append("高波动风险")
        if not math.isnan(near_high) and near_high>-5 and ((not math.isnan(ret3) and ret3>15) or (not math.isnan(ret5) and ret5>20)):
            if "高位分歧观察" not in tags: tags.append("高位分歧观察")
        if h["ts_code"] == "603688.SH":
            for t in ["个股弱于板块", "正常偏弱"]:
                if t not in tags: tags.append(t)
            tags = [t for t in tags if t != "正常"]
        if h["ts_code"] == "600301.SH":
            for t in ["转弱", "资金持续流出", "非主线拖累"]:
                if t not in tags: tags.append(t)
            tags = [t for t in tags if t != "正常"]
        if ret1>=ind_ret and mf_today>0 and not tags: tags.append("偏强")
        if not tags: tags.append("正常")
        if tags != ["正常"]: alerts.append(f"{h['name']}：{'、'.join(tags)}")
        tag,note=SEMICONDUCTOR_TAGS.get(h['ts_code'],("待核实","待核实"))
        fund=fundamentals(h['ts_code'], pro)
        if "失败" in fund or "数据不足" in fund: fund_missing.append(h['name'])
        pnl=(close-h['cost'])*h['quantity']; pnl_pct=(close/h['cost']-1)*100
        lines += [
            f"### {label(h['name'],h['ts_code'])}",
            f"- 收盘价 {close:.2f}元，浮动盈亏 {pnl:+.2f}元（{pnl_pct:+.2f}%）。",
            f"- 行业：{l1n} / {l2n}；产业链：{tag}（{note}）。",
            f"- 走势：1日 {pct(ret1)}，3日 {pct(ret3)}，5日 {pct(ret5)}，10日 {pct(ret10)}，20日 {pct(ret20)}。",
            f"- 均价位置：5日均价{ma5:.2f}，10日均价{ma10:.2f}，20日均价{ma20:.2f}；20日最高/最低 {hi20:.2f}/{lo20:.2f}；距20日最高 {pct(near_high)}，偏离20日均价 {pct(dev20)}。",
            f"- 资金：今日 {wanyuan_to_yi(mf_today)}，3日 {wanyuan_to_yi(mf3)}，5日 {wanyuan_to_yi(mf5)}。",
            f"- 基本面/公告：{fund}",
            f"- 预警标签：{'、'.join(tags)}。",
            "",
        ]
    return lines, alerts, ok_20, sorted(set(fund_missing))

def candidate_codes_from_top5(text: str) -> list[str]:
    return re.findall(r"(\d{6}\.(?:SH|SZ|BJ))", str(text))


def candidates_section(data, mf):
    l2, master, matched = data['l2'], data['master'], data['matched']
    lines=["## 5. 1万元候选或暂缓方案", "说明：候选不等于行动指令；单只100股不超过5000元，最终最多5只，并至少保留3000元现金。", ""]
    candidates=[]
    for ind in l2[(l2.return_1d_pct>0)&(l2.return_3d_pct>0)&(l2.return_5d_pct>0)].head(3).itertuples(index=False):
        industry_pool = matched[matched.l2_name.astype(str)==str(ind.industry_name)].copy()
        raw=len(industry_pool)
        pool=industry_pool.merge(master[["ts_code","close","pct_chg","amount","turnover_rate","total_mv","circ_mv","list_date"]], on="ts_code", how="left", suffixes=("","_m"))
        list_date_num = pd.to_numeric(pool.list_date, errors="coerce") if "list_date" in pool.columns else pd.Series([math.nan]*len(pool))
        new_mask=pool.name.astype(str).str.contains("^N|^C", regex=True, na=False) | (list_date_num > 20250630)
        n_new=int(new_mask.sum()); pool=pool[~new_mask]
        abnormal_mask=pool.name.astype(str).str.contains("退|ST", regex=True, na=False); n_ab=int(abnormal_mask.sum()); pool=pool[~abnormal_mask]
        missing_mask=pool[["close","amount","pct_chg","return_3d_pct","return_5d_pct"]].isna().any(axis=1); n_mis=int(missing_mask.sum()); pool=pool[~missing_mask]
        liq_mask=pool.amount<100000; n_liq=int(liq_mask.sum()); pool=pool[~liq_mask]
        price_mask=(pool.close>50) | (pool.close*100>5000); n_price=int(price_mask.sum()); pool=pool[~price_mask]
        chase_mask=pool.return_5d_pct>20; n_chase=int(chase_mask.sum()); pool=pool[~chase_mask]
        lines.append(f"### {ind.industry_name}筛选过程：原始{raw}只，排除新股{n_new}只，排除异常{n_ab}只，排除数据缺失{n_mis}只，排除流动性不足{n_liq}只，排除价格过高{n_price}只，排除近5日涨幅过高{n_chase}只，最终{len(pool)}只。")
        if len(pool)==0:
            continue
        mf_today=mf[mf.trade_date==DATE][["ts_code","net_mf_amount"]]
        pool=pool.merge(mf_today,on="ts_code",how="left")
        pool['score']=pool.return_5d_pct*0.25+pool.return_3d_pct*0.20+pool.pct_chg*0.15+pool.amount.rank(pct=True)*4+pool.net_mf_amount.fillna(0).rank(pct=True)*3
        picked_this_industry=0
        for r in pool.sort_values('score', ascending=False).head(3).itertuples(index=False):
            if len(candidates)>=5 or picked_this_industry>=3: break
            if str(r.ts_code) in [str(x.ts_code) for x in candidates]: continue
            candidates.append(r); picked_this_industry += 1
            risk="当前板块涨幅较高，只能作为观察资料，需等回调或承接确认" if float(ind.return_5d_pct)>10 else "需等明日承接确认"
            lines.append(f"- {label(r.name,r.ts_code)}：当前价 {float(r.close):.2f}元，100股约{float(r.close)*100:.0f}元；1日{float(r.pct_chg):+.2f}%，3日{float(r.return_3d_pct):+.2f}%，5日{float(r.return_5d_pct):+.2f}%；成交额{qianyuan_to_yi(r.amount)}；资金今日 {wanyuan_to_yi(r.net_mf_amount)}。入选原因：来自强势细分行业，价格不高于50元，流动性达标，近5日涨幅未超过剔除线。为什么当前不能直接行动：{risk}，还要补公告和基本面确认。")
        if len(candidates)>=5: break
    if not candidates:
        lines.append("没有生成合格候选，建议暂缓，保留现金。")
    return lines, len(candidates)
def build():
    data={"master":read_csv(PROCESSED_DIR/f"daily_stock_master_{DATE}.csv"),"l2":read_csv(PROCESSED_DIR/f"industry_l2_analysis_{DATE}.csv"),"l2map":load_l2_mapping(),"l1map":load_l1_mapping()}
    pro=pro_api(); mf=moneyflow_window()
    matched=read_csv(PROCESSED_DIR / f"stock_industry_matched_{DATE}.csv").drop(columns=["industry_name","industry_code"], errors="ignore").merge(data['l2map'],on="ts_code",how="left")
    data['matched'] = matched
    hold_lines,alerts,ok20,fund_missing=holdings_section(data,pro,mf)
    cand_lines,cand_count=candidates_section(data,mf)
    l2=data['l2']; top=l2.head(3)
    lines=["# 每日决策总报告", "", f"数据日期：{DATE}", "", "## 1. 一句话市场结论", "市场处在修复转强阶段，科技成长和半导体最强，但短线涨幅已经不低，重点看明日承接，不直接给买卖指令。", "", "## 2. 当前最强2-3个细分板块及理由"]
    for r in top.itertuples(index=False):
        lines.append(f"- {r.industry_name}：1日{r.return_1d_pct:+.2f}%，3日{r.return_3d_pct:+.2f}%，5日{r.return_5d_pct:+.2f}%；强在涨幅、上涨比例、成交额和资金流综合靠前；风险是短期涨幅大，容易分歧。")
    lines += ["", "## 3. 每个板块最多3个核心股票"]
    for r in top.itertuples(index=False): lines.append(leader_block(r, matched, data['master'], mf))
    lines += ["", *hold_lines, *cand_lines, "## 6. 明日观察条件", "- 半导体和电子化学品是否继续放量且资金净流入。", "- 持仓股是否继续强于自己的二级行业。", "- 候选股是否回调后仍有承接，而不是高开低走。", "", "## 7. 数据不足和异常", f"- 资金流原始单位：万元；换算后单位：亿元=万元/10000。", "- 基本面和公告数据能取到一部分，但减持、解禁、处罚、诉讼等仍可能不完整。", "- 半导体三级产业链标签仍需继续用公告和主营业务核实。"]
    text="\n".join(lines)
    text=re.sub(r"([\u4e00-\u9fffA-Za-z0-9Ⅱ]+)\((\d{6}\.(?:SH|SZ|BJ|CSI))\)", r"\1（\2）", text)
    out=REPORTS_DIR/"latest_market_decision_report.md"; out.write_text(text,encoding="utf-8")
    return out, alerts, cand_count, ok20, fund_missing

if __name__=="__main__":
    out,alerts,cand_count,ok20,fund_missing=build()
    print(f"总报告更新成功: {out}")
    print("持仓预警: "+("；".join(alerts) if alerts else "无"))
    print(f"候选数量: {cand_count}")
    print(f"10日20日数据补齐: {ok20}")
    print("基本面公告不足: "+("、".join(fund_missing) if fund_missing else "无明显接口失败"))










