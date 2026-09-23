"""
FleetOps AI - ML-based Anomaly Detection (Day 7)
===================================================
يستخدم Isolation Forest (Scikit-learn) لاكتشاف المعدات "الشاذة" باعتبار
كل الخصائص التشغيلية مع بعض دفعة واحدة (downtime, fuel efficiency,
maintenance frequency) بدل ما نحط thresholds يدوية لكل واحدة لوحدها.

كمان يحسب "Attention Score" (0-100) لكل معدة يجمع كل الإشارات في رقم واحد
سهل الترتيب عليه - مفيد لعرض قائمة أولويات واضحة في الداشبورد.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

import tools


def detect_ml_anomalies(contamination: float = 0.15) -> dict:
    """
    يكتشف المعدات الشاذة باستخدام Isolation Forest على 4 خصائص مجتمعة:
    downtime_rate, fuel_eff_vs_type_avg, maintenance_events, operating_hours.

    contamination: النسبة المتوقعة من المعدات الشاذة في الأسطول (افتراضي 15%).
    """
    df = tools._load_data()
    agg = df.groupby(["equipment_id", "equipment_type", "project"]).agg(
        operating_hours=("operating_hours", "sum"),
        downtime_hours=("downtime_hours", "sum"),
        fuel_l=("fuel_consumption_l", "sum"),
        maintenance_events=("maintenance_flag", "sum"),
    ).reset_index()

    agg["downtime_rate_%"] = (agg["downtime_hours"] / (agg["operating_hours"] + agg["downtime_hours"]) * 100)
    agg["fuel_eff"] = agg["fuel_l"] / agg["operating_hours"]
    type_avg_fuel = agg.groupby("equipment_type")["fuel_eff"].transform("mean")
    agg["fuel_vs_type_%"] = (agg["fuel_eff"] / type_avg_fuel - 1) * 100

    features = agg[["downtime_rate_%", "fuel_vs_type_%", "maintenance_events", "operating_hours"]].copy()
    X = StandardScaler().fit_transform(features)

    model = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
    agg["anomaly_flag"] = model.fit_predict(X)  # -1 = anomaly, 1 = normal
    agg["anomaly_score"] = -model.score_samples(X)  # كل ما زاد الرقم، زاد الشذوذ

    anomalies = agg[agg["anomaly_flag"] == -1].sort_values("anomaly_score", ascending=False)

    return {
        "tool": "detect_ml_anomalies",
        "method": "Isolation Forest (scikit-learn)",
        "features_used": ["downtime_rate_%", "fuel_vs_type_avg_%", "maintenance_events", "operating_hours"],
        "anomalies_found": len(anomalies),
        "data": anomalies[["equipment_id", "equipment_type", "project", "downtime_rate_%",
                            "fuel_vs_type_%", "maintenance_events", "anomaly_score"]].round(2).to_dict(orient="records"),
        "narrative_hint": (
            "These units are statistical outliers based on the combination of features together (not just one metric), "
            "meaning a unit can be flagged as anomalous even if each individual value looks normal on its own."
        ),
    }


def compute_attention_scores() -> dict:
    """
    يحسب Attention Score (0-100) لكل معدة: كل ما زاد الرقم، زادت أولوية التدخل.
    يجمع: downtime rate (40%) + fuel deviation (25%) + maintenance frequency (20%) + ML anomaly score (15%).
    """
    df = tools._load_data()
    agg = df.groupby(["equipment_id", "equipment_type", "project"]).agg(
        operating_hours=("operating_hours", "sum"),
        downtime_hours=("downtime_hours", "sum"),
        fuel_l=("fuel_consumption_l", "sum"),
        maintenance_events=("maintenance_flag", "sum"),
    ).reset_index()

    agg["downtime_rate_%"] = (agg["downtime_hours"] / (agg["operating_hours"] + agg["downtime_hours"]) * 100)
    agg["fuel_eff"] = agg["fuel_l"] / agg["operating_hours"]
    type_avg_fuel = agg.groupby("equipment_type")["fuel_eff"].transform("mean")
    agg["fuel_dev_%"] = (agg["fuel_eff"] / type_avg_fuel - 1) * 100

    def norm(s):
        rng = s.max() - s.min()
        return (s - s.min()) / rng * 100 if rng > 0 else s * 0

    ml_result = detect_ml_anomalies()
    ml_scores = pd.DataFrame(ml_result["data"])[["equipment_id", "anomaly_score"]] if ml_result["data"] else \
        pd.DataFrame(columns=["equipment_id", "anomaly_score"])
    agg = agg.merge(ml_scores, on="equipment_id", how="left").fillna({"anomaly_score": 0})

    agg["attention_score"] = (
        norm(agg["downtime_rate_%"]) * 0.40
        + norm(agg["fuel_dev_%"].clip(lower=0)) * 0.25
        + norm(agg["maintenance_events"]) * 0.20
        + norm(agg["anomaly_score"]) * 0.15
    ).round(1)

    result = agg.sort_values("attention_score", ascending=False).head(10)
    return {
        "tool": "compute_attention_scores",
        "data": result[["equipment_id", "equipment_type", "project", "attention_score",
                         "downtime_rate_%", "fuel_dev_%", "maintenance_events"]].round(1).to_dict(orient="records"),
        "narrative_hint": "Unified priority ranking of equipment (0-100); higher = higher intervention priority.",
    }


if __name__ == "__main__":
    import json
    print("=== ML Anomaly Detection ===")
    r1 = detect_ml_anomalies()
    print(f"عدد الشذوذات المكتشفة: {r1['anomalies_found']}")
    for row in r1["data"]:
        print(f"  • {row['equipment_id']} ({row['equipment_type']}) — anomaly_score={row['anomaly_score']}")

    print("\n=== Attention Scores (Top 10) ===")
    r2 = compute_attention_scores()
    for row in r2["data"]:
        print(f"  • {row['equipment_id']} — Attention Score: {row['attention_score']}/100")
