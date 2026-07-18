from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    market = json.loads((ROOT / "examples/demo_market_data.json").read_text(encoding="utf-8"))
    holdings = json.loads((ROOT / "examples/demo_holdings.json").read_text(encoding="utf-8"))
    output = ROOT / "reports/demo/demo_analysis_report.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# DEMO 股票分析报告

> DEMO / 固定脱敏数据 / 数据日期 {market['data_date']} / 不得用于真实交易决策

## 市场与板块

- 市场：{market['market']['state']}，演示量比 {market['market']['volume_ratio']}。
- 板块：{market['sector']['name']}，阶段 {market['sector']['state']}，相对强度 {market['sector']['relative_strength']}。

## 个股与资金

- 标的：{market['stock']['name']}（{market['stock']['code']}）。
- 演示收盘价：{market['stock']['close']}；演示量比：{market['stock']['volume_ratio']}；演示资金字段：{market['stock']['fund_flow']}。

## 仓位与结论

- 虚构持仓：{holdings['holdings'][0]['quantity']} 股，虚构成本 {holdings['holdings'][0]['cost']}。
- 结论：观望。触发条件：接入真实、同日期且完整的数据后重新分析。
- 风险：这是离线格式验证，不代表当前市场、板块或个股状态，不允许据此交易。
"""
    output.write_text(report, encoding="utf-8")
    print(f"DEMO_OK {output.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
