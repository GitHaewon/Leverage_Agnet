from __future__ import annotations

from scripts.run_shadow_live import build_shadow_decision_config


def test_shadow_live_config_defaults_to_conservative_thresholds(monkeypatch):
    monkeypatch.delenv("SHADOW_MIN_LONG_SCORE", raising=False)
    monkeypatch.delenv("SHADOW_MIN_SHORT_SCORE", raising=False)
    monkeypatch.delenv("SHADOW_MAX_RISK_SCORE", raising=False)

    cfg = build_shadow_decision_config()

    assert cfg["profile"] == "shadow"
    assert cfg["min_long_score"] == 75.0
    assert cfg["min_short_score"] == 75.0
    assert cfg["max_risk_score"] == 55.0
    assert cfg["max_risk_trend"] == 55.0


def test_shadow_live_config_reads_env(monkeypatch):
    monkeypatch.setenv("SHADOW_MIN_LONG_SCORE", "60")
    monkeypatch.setenv("SHADOW_MIN_SHORT_SCORE", "61")
    monkeypatch.setenv("SHADOW_MAX_RISK_SCORE", "70")

    cfg = build_shadow_decision_config()

    assert cfg["min_long_score"] == 60.0
    assert cfg["min_short_score"] == 61.0
    assert cfg["max_risk_score"] == 70.0
    assert cfg["max_risk_scalping"] == 70.0


def test_shadow_live_config_cli_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("SHADOW_MIN_LONG_SCORE", "60")
    monkeypatch.setenv("SHADOW_MIN_SHORT_SCORE", "61")
    monkeypatch.setenv("SHADOW_MAX_RISK_SCORE", "70")

    cfg = build_shadow_decision_config(
        min_long_score=55,
        min_short_score=56,
        max_risk_score=80,
    )

    assert cfg["min_long_score"] == 55.0
    assert cfg["min_short_score"] == 56.0
    assert cfg["max_risk_score"] == 80.0
