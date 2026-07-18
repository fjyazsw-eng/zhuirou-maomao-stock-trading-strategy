from __future__ import annotations

from typing import Any

import pandas as pd


SW_MEMBER_ALL_FIELDS = [
    "l1_code",
    "l1_name",
    "l2_code",
    "l2_name",
    "l3_code",
    "l3_name",
    "ts_code",
    "name",
    "in_date",
    "out_date",
    "is_new",
]

CI_MEMBER_FIELDS = [
    "l1_code",
    "l1_name",
    "l2_code",
    "l2_name",
    "l3_code",
    "l3_name",
    "ts_code",
    "name",
    "in_date",
    "out_date",
    "is_new",
]

STANDARD_MEMBER_FIELDS = ["index_code", "index_name", "con_code", "con_name", "in_date", "out_date", "is_new"]


def _empty_standard_members() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_MEMBER_FIELDS)


def _query(pro: Any, api_name: str, fields: list[str], **params: Any) -> pd.DataFrame:
    clean_params = {key: value for key, value in params.items() if value not in (None, "")}
    frame = pro.query(api_name, fields=",".join(fields), **clean_params)
    if frame is None:
        return pd.DataFrame(columns=fields)
    return frame


def _level_columns(level: str) -> tuple[str, str, str]:
    normalized = str(level or "L3").upper()
    if normalized == "L1":
        return "l1_code", "l1_name", "l1_code"
    if normalized == "L2":
        return "l2_code", "l2_name", "l2_code"
    return "l3_code", "l3_name", "l3_code"


def normalize_sw_member_all(frame: pd.DataFrame, level: str = "L3") -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_standard_members()
    code_col, name_col, _ = _level_columns(level)
    required = {code_col, name_col, "ts_code", "name", "in_date", "out_date", "is_new"}
    missing = required.difference(frame.columns)
    if missing:
        return _empty_standard_members()
    out = pd.DataFrame(
        {
            "index_code": frame[code_col],
            "index_name": frame[name_col],
            "con_code": frame["ts_code"],
            "con_name": frame["name"],
            "in_date": frame["in_date"],
            "out_date": frame["out_date"],
            "is_new": frame["is_new"],
        }
    )
    out["in_date"] = out["in_date"].fillna("00000000").astype(str)
    out["out_date"] = out["out_date"].fillna("").astype(str)
    out["is_new"] = out["is_new"].fillna("").astype(str)
    return out[STANDARD_MEMBER_FIELDS].drop_duplicates(["index_code", "con_code", "in_date"])


def fetch_sw_index_members(pro: Any, index_code: str, level: str = "L3", is_new: str = "Y") -> pd.DataFrame:
    _, _, param_name = _level_columns(level)
    frame = _query(pro, "index_member_all", SW_MEMBER_ALL_FIELDS, **{param_name: index_code, "is_new": is_new})
    return normalize_sw_member_all(frame, level=level)


def fetch_sw_stock_membership(pro: Any, ts_code: str, is_new: str = "Y") -> pd.DataFrame:
    return _query(pro, "index_member_all", SW_MEMBER_ALL_FIELDS, ts_code=ts_code, is_new=is_new)


def fetch_ci_stock_membership(pro: Any, ts_code: str, is_new: str = "Y") -> pd.DataFrame:
    return _query(pro, "ci_index_member", CI_MEMBER_FIELDS, ts_code=ts_code, is_new=is_new)


def _row_text(frame: pd.DataFrame, column: str) -> str:
    if frame is None or frame.empty or column not in frame.columns:
        return ""
    value = frame.iloc[0].get(column)
    return "" if pd.isna(value) else str(value)


def fetch_stock_industry_profile(pro: Any, ts_code: str) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "ts_code": ts_code,
        "sw_status": "EMPTY",
        "ci_status": "EMPTY",
        "sw": {},
        "ci": {},
        "errors": [],
    }
    try:
        sw = fetch_sw_stock_membership(pro, ts_code=ts_code, is_new="Y")
        if sw is not None and not sw.empty:
            profile["sw_status"] = "OK"
            profile["sw"] = {
                "l1_code": _row_text(sw, "l1_code"),
                "l1_name": _row_text(sw, "l1_name"),
                "l2_code": _row_text(sw, "l2_code"),
                "l2_name": _row_text(sw, "l2_name"),
                "l3_code": _row_text(sw, "l3_code"),
                "l3_name": _row_text(sw, "l3_name"),
            }
    except Exception as exc:
        profile["sw_status"] = "ERROR"
        profile["errors"].append(f"index_member_all: {type(exc).__name__}: {str(exc)[:160]}")

    try:
        ci = fetch_ci_stock_membership(pro, ts_code=ts_code, is_new="Y")
        if ci is not None and not ci.empty:
            profile["ci_status"] = "OK"
            profile["ci"] = {
                "l1_code": _row_text(ci, "l1_code"),
                "l1_name": _row_text(ci, "l1_name"),
                "l2_code": _row_text(ci, "l2_code"),
                "l2_name": _row_text(ci, "l2_name"),
                "l3_code": _row_text(ci, "l3_code"),
                "l3_name": _row_text(ci, "l3_name"),
            }
    except Exception as exc:
        profile["ci_status"] = "ERROR"
        profile["errors"].append(f"ci_index_member: {type(exc).__name__}: {str(exc)[:160]}")

    return profile
