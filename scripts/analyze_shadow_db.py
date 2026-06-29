#!/usr/bin/env python
"""Summarize shadow trading quality from Postgres shadow tables."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (ROOT / ".env", ROOT / "backend" / ".env")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Analyze shadow_decisions and shadow_trades from Postgres."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Optional JSON output path, e.g. logs/shadow_db_summary.json",
    )
    args = parser.parse_args()

    try:
        summary = asyncio.run(analyze())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_report_v2(summary)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        print(f"\nJSON saved: {args.output}")

    return 0


async def analyze() -> dict[str, Any]:
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError(
            "asyncpg is required. Run inside the backend environment/container "
            "or install backend requirements."
        ) from exc

    env = load_env()
    db_url = build_database_url(env)
    attempted_urls = [db_url]

    try:
        conn = await asyncpg.connect(db_url)
    except Exception as first_exc:
        fallback = localhost_fallback_url(db_url)
        if fallback == db_url:
            raise RuntimeError(f"database connection failed: {first_exc}") from first_exc

        attempted_urls.append(fallback)
        try:
            conn = await asyncpg.connect(fallback)
        except Exception as second_exc:
            raise RuntimeError(
                "database connection failed. Tried configured host and localhost fallback: "
                f"{first_exc}; {second_exc}"
            ) from second_exc

    try:
        return await fetch_summary_v2(conn, attempted_urls[-1])
    finally:
        await conn.close()


async def fetch_summary(conn: Any, db_url: str) -> dict[str, Any]:
    decisions = await conn.fetchrow(
        """
        SELECT
            COUNT(*)::int AS total,
            MIN(decided_at) AS first_at,
            MAX(decided_at) AS last_at
        FROM shadow_decisions
        """
    )
    total_decisions = decisions["total"] if decisions else 0

    action_rows = await conn.fetch(
        """
        SELECT coin, final_action, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY coin, final_action
        ORDER BY coin, final_action
        """
    )
    regime_rows = await conn.fetch(
        """
        SELECT market_regime AS value, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY market_regime
        ORDER BY count DESC, value NULLS LAST
        """
    )
    strategy_rows = await conn.fetch(
        """
        SELECT strategy_type AS value, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY strategy_type
        ORDER BY count DESC, value NULLS LAST
        """
    )
    rejection_rows = await conn.fetch(
        """
        SELECT rejection_stage, rejection_reason, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY rejection_stage, rejection_reason
        ORDER BY count DESC, rejection_stage NULLS LAST, rejection_reason NULLS LAST
        """
    )
    score_rows = await conn.fetch(
        """
        SELECT
            COUNT(long_score)::int AS long_count,
            MIN(long_score)::float AS long_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY long_score)::float AS long_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY long_score)::float AS long_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY long_score)::float AS long_p75,
            MAX(long_score)::float AS long_max,
            COUNT(short_score)::int AS short_count,
            MIN(short_score)::float AS short_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY short_score)::float AS short_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY short_score)::float AS short_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY short_score)::float AS short_p75,
            MAX(short_score)::float AS short_max,
            COUNT(risk_score)::int AS risk_count,
            MIN(risk_score)::float AS risk_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY risk_score)::float AS risk_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY risk_score)::float AS risk_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY risk_score)::float AS risk_p75,
            MAX(risk_score)::float AS risk_max,
            AVG(min_long_score)::float AS avg_min_long_score,
            AVG(min_short_score)::float AS avg_min_short_score,
            AVG(max_risk_score)::float AS avg_max_risk_score
        FROM shadow_decisions
        """
    )
    score_by_coin_rows = await conn.fetch(_score_distribution_sql("coin"))
    score_by_regime_rows = await conn.fetch(_score_distribution_sql("market_regime"))
    trade_summary = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status != 'REJECTED')::int AS total,
            COUNT(*) FILTER (WHERE status = 'OPEN')::int AS open_trades,
            COUNT(*) FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD'))::int AS closed_trades,
            COUNT(*) FILTER (
                WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND net_pnl_usdt > 0
            )::int AS wins,
            COALESCE(
                SUM(pnl_usdt) FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')),
                0
            )::float AS gross_pnl,
            COALESCE(
                SUM(pnl_usdt) FILTER (
                    WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND pnl_usdt > 0
                ),
                0
            )::float AS gross_profit,
            COALESCE(
                SUM(pnl_usdt) FILTER (
                    WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND pnl_usdt < 0
                ),
                0
            )::float AS gross_loss
            ,
            COALESCE(
                SUM(net_pnl_usdt) FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')),
                0
            )::float AS net_pnl,
            COALESCE(
                SUM(entry_fee_usdt + exit_fee_usdt)
                    FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')), 0
            )::float AS fees,
            COALESCE(
                SUM(funding_fee_usdt)
                    FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')), 0
            )::float AS funding,
            COALESCE(
                SUM(estimated_slippage_usdt)
                    FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')), 0
            )::float AS slippage,
            COUNT(*) FILTER (
                WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')
                  AND pnl_calculation_status = 'GROSS_FALLBACK'
            )::int AS gross_fallback_count
        FROM shadow_trades
        """
    )
    trade_rr_rows = await conn.fetch(
        """
        SELECT direction, entry_price, tp_price, sl_price
        FROM shadow_trades
        WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')
        """
    )
    trade_pnl_rows = await conn.fetch(
        """
        SELECT net_pnl_usdt::float AS pnl
        FROM shadow_trades
        WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND net_pnl_usdt IS NOT NULL
        ORDER BY closed_at ASC NULLS LAST, opened_at ASC
        """
    )
    trade_metrics = build_trade_metrics(trade_summary, trade_rr_rows, trade_pnl_rows)

    return {
        "source": {
            "database": mask_database_url(db_url),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "decisions": {
            "total": total_decisions,
            "first_at": _json_default(decisions["first_at"]) if decisions else None,
            "last_at": _json_default(decisions["last_at"]) if decisions else None,
            "by_coin_action": build_coin_action_counts(action_rows),
            "market_regime": rows_to_distribution(regime_rows),
            "strategy_type": rows_to_distribution(strategy_rows),
            "rejections": rows_to_rejection_distribution(rejection_rows),
            "score_distribution": score_row_to_distribution(score_rows[0] if score_rows else None),
            "score_distribution_by_coin": grouped_score_rows(score_by_coin_rows),
            "score_distribution_by_market_regime": grouped_score_rows(score_by_regime_rows),
        },
        "shadow_trades": {
            "total": trade_count,
            "performance_status": "성과 판단 불가" if trade_count == 0 else "성과 판단 가능",
        },
    }


async def fetch_summary_v2(conn: Any, db_url: str) -> dict[str, Any]:
    decisions = await conn.fetchrow(
        """
        SELECT
            COUNT(*)::int AS total,
            MIN(decided_at) AS first_at,
            MAX(decided_at) AS last_at
        FROM shadow_decisions
        """
    )
    total_decisions = decisions["total"] if decisions else 0

    action_rows = await conn.fetch(
        """
        SELECT coin, final_action, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY coin, final_action
        ORDER BY coin, final_action
        """
    )
    regime_rows = await conn.fetch(
        """
        SELECT market_regime AS value, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY market_regime
        ORDER BY count DESC, value NULLS LAST
        """
    )
    strategy_rows = await conn.fetch(
        """
        SELECT strategy_type AS value, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY strategy_type
        ORDER BY count DESC, value NULLS LAST
        """
    )
    rejection_rows = await conn.fetch(
        """
        SELECT rejection_stage, rejection_reason, COUNT(*)::int AS count
        FROM shadow_decisions
        GROUP BY rejection_stage, rejection_reason
        ORDER BY count DESC, rejection_stage NULLS LAST, rejection_reason NULLS LAST
        """
    )
    score_rows = await conn.fetch(
        """
        SELECT
            COUNT(long_score)::int AS long_count,
            MIN(long_score)::float AS long_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY long_score)::float AS long_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY long_score)::float AS long_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY long_score)::float AS long_p75,
            MAX(long_score)::float AS long_max,
            COUNT(short_score)::int AS short_count,
            MIN(short_score)::float AS short_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY short_score)::float AS short_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY short_score)::float AS short_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY short_score)::float AS short_p75,
            MAX(short_score)::float AS short_max,
            COUNT(risk_score)::int AS risk_count,
            MIN(risk_score)::float AS risk_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY risk_score)::float AS risk_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY risk_score)::float AS risk_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY risk_score)::float AS risk_p75,
            MAX(risk_score)::float AS risk_max,
            AVG(min_long_score)::float AS avg_min_long_score,
            AVG(min_short_score)::float AS avg_min_short_score,
            AVG(max_risk_score)::float AS avg_max_risk_score
        FROM shadow_decisions
        """
    )
    score_by_coin_rows = await conn.fetch(_score_distribution_sql("coin"))
    score_by_regime_rows = await conn.fetch(_score_distribution_sql("market_regime"))

    trade_summary = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE status != 'REJECTED')::int AS total,
            COUNT(*) FILTER (WHERE status = 'OPEN')::int AS open_trades,
            COUNT(*) FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD'))::int AS closed_trades,
            COUNT(*) FILTER (
                WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND pnl_usdt > 0
            )::int AS wins,
            COALESCE(
                SUM(pnl_usdt) FILTER (WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')),
                0
            )::float AS gross_pnl,
            COALESCE(
                SUM(pnl_usdt) FILTER (
                    WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND pnl_usdt > 0
                ),
                0
            )::float AS gross_profit,
            COALESCE(
                SUM(pnl_usdt) FILTER (
                    WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND pnl_usdt < 0
                ),
                0
            )::float AS gross_loss
        FROM shadow_trades
        """
    )
    trade_rr_rows = await conn.fetch(
        """
        SELECT direction, entry_price, tp_price, sl_price
        FROM shadow_trades
        WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD')
        """
    )
    trade_pnl_rows = await conn.fetch(
        """
        SELECT pnl_usdt::float AS pnl
        FROM shadow_trades
        WHERE status IN ('TP_HIT', 'SL_HIT', 'MAX_HOLD') AND pnl_usdt IS NOT NULL
        ORDER BY closed_at ASC NULLS LAST, opened_at ASC
        """
    )

    return {
        "source": {
            "database": mask_database_url(db_url),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        "decisions": {
            "total": total_decisions,
            "first_at": _json_default(decisions["first_at"]) if decisions else None,
            "last_at": _json_default(decisions["last_at"]) if decisions else None,
            "by_coin_action": build_coin_action_counts(action_rows),
            "market_regime": rows_to_distribution(regime_rows),
            "strategy_type": rows_to_distribution(strategy_rows),
            "rejections": rows_to_rejection_distribution(rejection_rows),
            "score_distribution": score_row_to_distribution(score_rows[0] if score_rows else None),
            "score_distribution_by_coin": grouped_score_rows(score_by_coin_rows),
            "score_distribution_by_market_regime": grouped_score_rows(score_by_regime_rows),
        },
        "shadow_trades": build_trade_metrics(trade_summary, trade_rr_rows, trade_pnl_rows),
    }


def build_trade_metrics(summary: Any, rr_rows: list[Any], pnl_rows: list[Any]) -> dict[str, Any]:
    def _value(name: str, default: Any = 0) -> Any:
        if summary is None:
            return default
        try:
            return summary[name]
        except (KeyError, IndexError, TypeError):
            return default

    total = int(summary["total"] or 0) if summary else 0
    open_trades = int(summary["open_trades"] or 0) if summary else 0
    closed_trades = int(summary["closed_trades"] or 0) if summary else 0
    wins = int(summary["wins"] or 0) if summary else 0
    gross_pnl = float(summary["gross_pnl"] or 0.0) if summary else 0.0
    gross_profit = float(summary["gross_profit"] or 0.0) if summary else 0.0
    gross_loss = float(summary["gross_loss"] or 0.0) if summary else 0.0
    has_net_costs = False
    if summary is not None:
        try:
            summary["net_pnl"]
            has_net_costs = True
        except (KeyError, IndexError, TypeError):
            pass
    net_pnl = float(_value("net_pnl", gross_pnl) or 0.0)
    profit_factor = None
    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = None

    return {
        "total": total,
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "performance_status": "성과 판단 불가" if total == 0 else "성과 판단 가능",
        "win_rate": (wins / closed_trades * 100.0) if closed_trades else None,
        "gross_pnl": gross_pnl if closed_trades else None,
        "net_pnl": net_pnl if closed_trades else None,
        "fees": float(_value("fees", 0) or 0.0),
        "funding": float(_value("funding", 0) or 0.0),
        "slippage": float(_value("slippage", 0) or 0.0),
        "gross_fallback_count": int(_value("gross_fallback_count", 0) or 0),
        "fees_slippage_reflected": has_net_costs,
        "fees_slippage_note": (
            None
            if has_net_costs
            else "legacy rows/schema: net PnL falls back to gross PnL"
        ),
        "profit_factor": profit_factor,
        "max_drawdown": _max_drawdown([float(row["pnl"]) for row in pnl_rows]),
        "average_rr": _average_rr(rr_rows),
    }


def _average_rr(rows: list[Any]) -> float | None:
    values: list[float] = []
    for row in rows:
        entry = float(row["entry_price"])
        tp = float(row["tp_price"])
        sl = float(row["sl_price"])
        if row["direction"] == "LONG":
            risk = entry - sl
            reward = tp - entry
        else:
            risk = sl - entry
            reward = entry - tp
        if risk > 0 and reward > 0:
            values.append(reward / risk)
    return (sum(values) / len(values)) if values else None


def _max_drawdown(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in ENV_FILES:
        if not path.exists():
            continue
        values.update(parse_env_file(path))

    values.update(os.environ)
    return values


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def build_database_url(env: dict[str, str]) -> str:
    db_url = env.get("DATABASE_URL", "").strip()
    if db_url:
        return normalize_asyncpg_url(db_url)

    user = env.get("POSTGRES_USER")
    password = env.get("POSTGRES_PASSWORD")
    db = env.get("POSTGRES_DB")
    host = env.get("POSTGRES_HOST", "localhost")
    port = env.get("POSTGRES_PORT", "5432")
    if not all([user, password, db]):
        raise RuntimeError(
            "DATABASE_URL or POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB must be set "
            "in backend/.env, .env, or the process environment."
        )
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def normalize_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url.removeprefix("postgresql+asyncpg://")
    if url.startswith("postgres+asyncpg://"):
        return "postgresql://" + url.removeprefix("postgres+asyncpg://")
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url


def localhost_fallback_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.hostname != "postgres":
        return url

    netloc = parts.netloc.replace("@postgres:", "@localhost:", 1)
    if netloc == parts.netloc:
        netloc = parts.netloc.replace("@postgres", "@localhost", 1)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def mask_database_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.password:
        return url

    username = parts.username or ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    auth = f"{username}:***@" if username else ""
    return urlunsplit((parts.scheme, f"{auth}{host}{port}", parts.path, parts.query, ""))


def build_coin_action_counts(rows: list[Any]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"LONG": 0, "SHORT": 0, "HOLD": 0})
    for row in rows:
        coin = row["coin"] or "(NULL)"
        action = row["final_action"] or "(NULL)"
        counts[coin][action] = row["count"]
    return dict(sorted(counts.items()))


def rows_to_distribution(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"value": row["value"], "count": row["count"]} for row in rows]


def rows_to_rejection_distribution(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "rejection_stage": row["rejection_stage"],
            "rejection_reason": row["rejection_reason"],
            "count": row["count"],
        }
        for row in rows
    ]


def _score_distribution_sql(group_column: str) -> str:
    if group_column not in {"coin", "market_regime"}:
        raise ValueError(f"unsupported score distribution group: {group_column}")
    return f"""
        SELECT
            {group_column} AS group_value,
            COUNT(long_score)::int AS long_count,
            MIN(long_score)::float AS long_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY long_score)::float AS long_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY long_score)::float AS long_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY long_score)::float AS long_p75,
            MAX(long_score)::float AS long_max,
            COUNT(short_score)::int AS short_count,
            MIN(short_score)::float AS short_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY short_score)::float AS short_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY short_score)::float AS short_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY short_score)::float AS short_p75,
            MAX(short_score)::float AS short_max,
            COUNT(risk_score)::int AS risk_count,
            MIN(risk_score)::float AS risk_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY risk_score)::float AS risk_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY risk_score)::float AS risk_median,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY risk_score)::float AS risk_p75,
            MAX(risk_score)::float AS risk_max
        FROM shadow_decisions
        GROUP BY {group_column}
        ORDER BY {group_column} NULLS LAST
        """


def score_row_to_distribution(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {
        "long_score": _metric_stats(row, "long"),
        "short_score": _metric_stats(row, "short"),
        "risk_score": _metric_stats(row, "risk"),
        "thresholds": {
            "avg_min_long_score": row["avg_min_long_score"],
            "avg_min_short_score": row["avg_min_short_score"],
            "avg_max_risk_score": row["avg_max_risk_score"],
        },
    }


def grouped_score_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "group": row["group_value"],
            "long_score": _metric_stats(row, "long"),
            "short_score": _metric_stats(row, "short"),
            "risk_score": _metric_stats(row, "risk"),
        }
        for row in rows
    ]


def _metric_stats(row: Any, prefix: str) -> dict[str, Any]:
    return {
        "count": row[f"{prefix}_count"],
        "min": row[f"{prefix}_min"],
        "p25": row[f"{prefix}_p25"],
        "median": row[f"{prefix}_median"],
        "p75": row[f"{prefix}_p75"],
        "max": row[f"{prefix}_max"],
    }


def print_report_v2(summary: dict[str, Any]) -> None:
    decisions = summary["decisions"]
    trades = summary["shadow_trades"]

    print("=" * 72)
    print("SHADOW DB QUALITY REPORT")
    print("=" * 72)
    print(f"Database        : {summary['source']['database']}")
    print(f"Generated at    : {summary['source']['generated_at']}")
    print()
    print(f"Total decisions : {decisions['total']:,}")
    print(f"first_at        : {decisions['first_at'] or '-'}")
    print(f"last_at         : {decisions['last_at'] or '-'}")

    print_section("Coin x Final Action")
    if decisions["by_coin_action"]:
        for coin, counts in decisions["by_coin_action"].items():
            print(
                f"{coin:<8} LONG {counts.get('LONG', 0):>5,} | "
                f"SHORT {counts.get('SHORT', 0):>5,} | HOLD {counts.get('HOLD', 0):>5,}"
            )
    else:
        print("(no decisions)")

    print_distribution("Market Regime", decisions["market_regime"], decisions["total"])
    print_distribution("Strategy Type", decisions["strategy_type"], decisions["total"])
    print_score_distribution(
        "Score Distribution",
        decisions["score_distribution"],
        show_thresholds=True,
    )
    print_grouped_score_distribution("Score Distribution by Coin", decisions["score_distribution_by_coin"])
    print_grouped_score_distribution(
        "Score Distribution by Market Regime",
        decisions["score_distribution_by_market_regime"],
    )

    print_section("Rejection Stage / Reason")
    if decisions["rejections"]:
        for item in decisions["rejections"]:
            stage = item["rejection_stage"] or "(none)"
            reason = item["rejection_reason"] or "(none)"
            print(f"{item['count']:>6,}  {stage:<22}  {reason}")
    else:
        print("(no rejection rows)")

    print_trade_metrics(trades)
    print("=" * 72)


def print_trade_metrics(trades: dict[str, Any]) -> None:
    print_section("Shadow Trades")
    print(f"Total shadow_trades : {trades['total']:,}")
    if trades["total"] == 0:
        print("성과 판단 불가: shadow_trades가 0개라 승률/PnL/보유시간 성과는 판단할 수 없습니다.")
        return

    print(f"Open trades         : {trades['open_trades']:,}")
    print(f"Closed trades       : {trades['closed_trades']:,}")
    if trades["closed_trades"] == 0:
        print("성과 판단 불가: open trade만 있고 TP/SL로 닫힌 거래가 아직 없습니다.")
        return

    print(f"Win rate            : {_fmt_pct(trades['win_rate'])}")
    print(f"Gross PnL           : {_fmt_money(trades['gross_pnl'])}")
    print(f"Net PnL             : {_fmt_money(trades['net_pnl'])}")
    print(f"Entry/exit fees     : {_fmt_money(trades['fees'])}")
    print(f"Funding fee         : {_fmt_money(trades['funding'])}")
    print(f"Estimated slippage  : {_fmt_money(trades['slippage'])}")
    print(f"Profit factor       : {_fmt(trades['profit_factor'])}")
    print(f"Max drawdown        : {_fmt_money(trades['max_drawdown'])}")
    print(f"Average R:R         : {_fmt(trades['average_rr'])}")
    print(
        "Fees/slippage       : "
        + ("reflected" if trades["fees_slippage_reflected"] else "not reflected")
    )
    if not trades["fees_slippage_reflected"]:
        print(f"  note: {trades['fees_slippage_note']}")


def print_report(summary: dict[str, Any]) -> None:
    decisions = summary["decisions"]
    trades = summary["shadow_trades"]

    print("=" * 72)
    print("SHADOW DB QUALITY REPORT")
    print("=" * 72)
    print(f"Database        : {summary['source']['database']}")
    print(f"Generated at    : {summary['source']['generated_at']}")
    print()
    print(f"Total decisions : {decisions['total']:,}")
    print(f"first_at        : {decisions['first_at'] or '-'}")
    print(f"last_at         : {decisions['last_at'] or '-'}")

    print_section("Coin x Final Action")
    if decisions["by_coin_action"]:
        for coin, counts in decisions["by_coin_action"].items():
            print(
                f"{coin:<8} LONG {counts.get('LONG', 0):>5,} | "
                f"SHORT {counts.get('SHORT', 0):>5,} | HOLD {counts.get('HOLD', 0):>5,}"
            )
    else:
        print("(no decisions)")

    print_distribution("Market Regime", decisions["market_regime"], decisions["total"])
    print_distribution("Strategy Type", decisions["strategy_type"], decisions["total"])

    print_score_distribution(
        "Score Distribution",
        decisions["score_distribution"],
        show_thresholds=True,
    )
    print_grouped_score_distribution("Score Distribution by Coin", decisions["score_distribution_by_coin"])
    print_grouped_score_distribution(
        "Score Distribution by Market Regime",
        decisions["score_distribution_by_market_regime"],
    )

    print_section("Rejection Stage / Reason")
    if decisions["rejections"]:
        for item in decisions["rejections"]:
            stage = item["rejection_stage"] or "(none)"
            reason = item["rejection_reason"] or "(none)"
            print(f"{item['count']:>6,}  {stage:<22}  {reason}")
    else:
        print("(no rejection rows)")

    print_section("Shadow Trades")
    print(f"Total shadow_trades : {trades['total']:,}")
    if trades["total"] == 0:
        print("성과 판단 불가: shadow_trades가 0개라 승률/PnL/보유시간 성과는 판단할 수 없습니다.")
    else:
        print("성과 판단 가능: trade 성과 분석 스크립트로 승률/PnL을 추가 확인하세요.")

    print("=" * 72)


def print_section(title: str) -> None:
    print()
    print(f"[{title}]")


def print_distribution(title: str, rows: list[dict[str, Any]], total: int) -> None:
    print_section(title)
    if not rows:
        print("(no rows)")
        return

    for row in rows:
        label = row["value"] or "(NULL)"
        count = row["count"]
        pct = (count / total * 100.0) if total else 0.0
        print(f"{str(label):<24} {count:>6,}  {pct:>5.1f}%")


def print_score_distribution(
    title: str,
    score_distribution: dict[str, Any],
    *,
    show_thresholds: bool = False,
) -> None:
    print_section(title)
    if not score_distribution or not score_distribution.get("long_score", {}).get("count"):
        print("(no score diagnostics yet; run migrations and collect new shadow_decisions)")
        return

    if show_thresholds:
        thresholds = score_distribution.get("thresholds") or {}
        print(
            "Threshold avg : "
            f"min_long={_fmt(thresholds.get('avg_min_long_score'))}, "
            f"min_short={_fmt(thresholds.get('avg_min_short_score'))}, "
            f"max_risk={_fmt(thresholds.get('avg_max_risk_score'))}"
        )
    for metric in ("long_score", "short_score", "risk_score"):
        stats = score_distribution[metric]
        print(f"{metric:<12} {_stats_line(stats)}")


def print_grouped_score_distribution(title: str, rows: list[dict[str, Any]]) -> None:
    print_section(title)
    populated = [
        row for row in rows
        if row.get("long_score", {}).get("count")
        or row.get("short_score", {}).get("count")
        or row.get("risk_score", {}).get("count")
    ]
    if not populated:
        print("(no grouped score diagnostics yet)")
        return
    for row in populated:
        print(f"{row['group'] or '(NULL)'}")
        print(f"  long_score  {_stats_line(row['long_score'])}")
        print(f"  short_score {_stats_line(row['short_score'])}")
        print(f"  risk_score  {_stats_line(row['risk_score'])}")


def _stats_line(stats: dict[str, Any]) -> str:
    return (
        f"n={stats['count']:>4,} "
        f"min={_fmt(stats['min'])} "
        f"p25={_fmt(stats['p25'])} "
        f"median={_fmt(stats['median'])} "
        f"p75={_fmt(stats['p75'])} "
        f"max={_fmt(stats['max'])}"
    )


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def _fmt_money(value: Any) -> str:
    return "-" if value is None else f"{float(value):,.2f} USDT"


def _fmt_pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.1f}%"


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
