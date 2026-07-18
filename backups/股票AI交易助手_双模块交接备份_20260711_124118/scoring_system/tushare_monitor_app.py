from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from scoring_system.tushare_probe import format_probe_text, probe_tushare

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICON_PATH = ASSETS / "stock_assistant.ico"

STATUS_COLORS = {
    "PASS": "#0f7b0f",
    "WARN": "#b26a00",
    "BLOCKED": "#b00020",
}


class TushareMonitorApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("股票AI交易助手 - Tushare监测")
        self.root.geometry("820x620")
        self.root.minsize(760, 560)
        try:
            if ICON_PATH.exists():
                self.root.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

        self.auto_refresh = tk.BooleanVar(value=True)
        self.interval_ms = 30000
        self._after_id: str | None = None
        self._running = False

        self.status_var = tk.StringVar(value="等待检测")
        self.summary_var = tk.StringVar(value="打开后会自动执行一次探测。")
        self.connection_var = tk.StringVar(value="连接结果: -")
        self.permission_var = tk.StringVar(value="接口权限: -")
        self.permission_detail_var = tk.StringVar(value="权限明细: -")
        self.category_var = tk.StringVar(value="分类权限: -")
        self.token_var = tk.StringVar(value="Token: -")
        self.tier_var = tk.StringVar(value="积分档位: -")

        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Tushare 实时监测", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        self.status_label = ttk.Label(top, textvariable=self.status_var, font=("Microsoft YaHei UI", 11, "bold"))
        self.status_label.pack(anchor="w", pady=(8, 2))
        ttk.Label(top, textvariable=self.summary_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        ttk.Label(top, textvariable=self.connection_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(4, 0))
        ttk.Label(top, textvariable=self.permission_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        ttk.Label(top, textvariable=self.permission_detail_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        ttk.Label(top, textvariable=self.category_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        ttk.Label(top, textvariable=self.tier_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        ttk.Label(top, textvariable=self.token_var, font=("Microsoft YaHei UI", 10)).pack(anchor="w")

        controls = ttk.Frame(top)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="立即刷新", command=self.refresh_now).pack(side="left")
        ttk.Checkbutton(controls, text="自动刷新(30秒)", variable=self.auto_refresh, command=self._reset_timer).pack(side="left", padx=(10, 0))

        body = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)

        self.text = tk.Text(body, wrap="word", font=("Consolas", 10))
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", "等待检测...")
        self.text.configure(state="disabled")

        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        scrollbar.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scrollbar.set)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh_now()

    def _set_text(self, value: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.configure(state="disabled")

    def _update_ui(self, result: dict[str, object]) -> None:
        status = str(result.get("status", "BLOCKED"))
        latest = str(result.get("latest_trade_date", "")) or "-"
        data_trade_date = str(result.get("data_trade_date", "")) or "-"
        daily_rows = result.get("daily_rows", 0)
        basic_rows = result.get("daily_basic_rows", 0)
        message = str(result.get("message", ""))
        trade_cal_ok = bool(result.get("trade_cal_ok", False))
        stock_basic_ok = bool(result.get("stock_basic_ok", False))
        token_present = bool(result.get("token_present", False))
        token_masked = str(result.get("token_masked", "")) or "-"
        endpoint = str(result.get("endpoint", "")) or "-"
        permission_summary = self._build_permission_summary(result)
        permission_detail = self._build_permission_detail(result)
        category_summary = self._build_category_summary(result)
        tier_summary = self._build_tier_summary(result)
        self.status_var.set(f"当前状态: {status}")
        self.summary_var.set(f"最新交易日: {latest} | 数据日期: {data_trade_date} | daily: {daily_rows} | daily_basic: {basic_rows} | {message}")
        self.connection_var.set(f"连接结果: {'已连上' if status == 'PASS' else '未完全连上'} | stock_basic: {'通过' if stock_basic_ok else '失败'} | trade_cal: {'通过' if trade_cal_ok else '失败'}")
        self.permission_var.set(f"接口权限: {permission_summary}")
        self.permission_detail_var.set(f"权限明细: {permission_detail}")
        self.category_var.set(f"分类权限: {category_summary}")
        self.tier_var.set(f"积分档位: {tier_summary}")
        self.token_var.set(f"Token: {'已检测到 ' + token_masked if token_present else '未检测到'} | Endpoint: {endpoint}")
        color = STATUS_COLORS.get(status, "#333333")
        self.status_label.configure(foreground=color)
        self._set_text(format_probe_text(result))
        self._running = False
        self._reset_timer()

    def _run_probe(self) -> None:
        try:
            result = probe_tushare()
        except Exception as exc:
            result = {"status": "BLOCKED", "message": f"{type(exc).__name__}: {exc}"}
        self.root.after(0, lambda: self._update_ui(result))

    def refresh_now(self) -> None:
        if self._running:
            return
        self._running = True
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.status_var.set("当前状态: 检测中")
        self.summary_var.set("正在调用 Tushare，请稍候...")
        self._set_text("正在检测...")
        threading.Thread(target=self._run_probe, daemon=True).start()

    def _reset_timer(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        if self.auto_refresh.get() and not self._running:
            self._after_id = self.root.after(self.interval_ms, self.refresh_now)

    def _on_close(self) -> None:
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self.root.destroy()

    def _build_permission_summary(self, result: dict[str, object]) -> str:
        token_present = bool(result.get("token_present", False))
        summary = result.get("permission_summary", {}) or {}
        passed_count = int(summary.get("passed_count", 0) or 0)
        checked_count = int(summary.get("checked_count", 0) or 0)
        if not token_present:
            return "缺少 Token，无法判断 1500 积分接口"
        if checked_count and passed_count == checked_count:
            return f"已验证 {passed_count}/{checked_count} 个接口均可用"
        if checked_count and passed_count > 0:
            return f"已验证 {passed_count}/{checked_count} 个接口可用，存在部分失败"
        return "Token 已识别，但接口矩阵未通过"

    def _build_permission_detail(self, result: dict[str, object]) -> str:
        checks = result.get("permission_checks", []) or []
        if not checks:
            return "暂无明细"
        passed = [str(item.get("api_name")) for item in checks if bool(item.get("ok", False))]
        failed = [str(item.get("api_name")) for item in checks if not bool(item.get("ok", False))]
        passed_text = "通过: " + ", ".join(passed[:6]) if passed else "通过: 无"
        failed_text = "失败: " + ", ".join(failed[:4]) if failed else "失败: 无"
        return f"{passed_text} | {failed_text}"

    def _build_tier_summary(self, result: dict[str, object]) -> str:
        token_present = bool(result.get("token_present", False))
        summary = result.get("permission_summary", {}) or {}
        passed_count = int(summary.get("passed_count", 0) or 0)
        checked_count = int(summary.get("checked_count", 0) or 0)
        if token_present and checked_count and passed_count >= max(6, checked_count // 2):
            return "1500积分档位（实测多接口可用，偏高可信）"
        if token_present and passed_count > 0:
            return "1500积分档位（有部分接口通过，仍需继续核验）"
        if token_present:
            return "Token 已在，但积分档位未验证"
        return "未识别"

    def _build_category_summary(self, result: dict[str, object]) -> str:
        categories = result.get("permission_categories", {}) or {}
        ordered = ["行情", "资金流", "财务", "板块行业", "指数", "复权", "基础资料"]
        parts: list[str] = []
        for name in ordered:
            item = categories.get(name)
            if not item:
                continue
            status = str(item.get("status", "-"))
            passed = int(item.get("passed_count", 0) or 0)
            checked = int(item.get("checked_count", 0) or 0)
            parts.append(f"{name}:{status}({passed}/{checked})")
        return " | ".join(parts) if parts else "暂无分类结果"

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    return TushareMonitorApp().run()
