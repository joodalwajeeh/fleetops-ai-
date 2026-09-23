"""
FleetOps AI - Tool Library (Day 4)
===================================
هذه هي "الأدوات" (Tools) التي سيستدعيها الـ AI Agent (عبر LLM Function Calling)
بناءً على سؤال المستخدم. كل دالة:
  - تاخد بارامترات بسيطة (equipment_id / project / threshold...)
  - ترجع dict منظم (JSON-serializable) يحتوي على data + narrative_hint
    بحيث الـ LLM يقدر يحوّله لإجابة طبيعية بالعربي/الإنجليزي.

الأدوات: pandas + numpy فقط (بدون أي استدعاء LLM هنا).
"""

import pandas as pd
import numpy as np

DAILY_PATH = "data/fleet_daily_logs.csv"
EQUIP_PATH = "data/equipment_master.csv"

# Optional in-memory override, set via set_data_source() — lets the dashboard
# test the same analysis pipeline against a user-uploaded dataset without
# touching the bundled sample files on disk.
_OVERRIDE = {"daily": None, "equip": None}


def set_data_source(equipment_df: pd.DataFrame, daily_df: pd.DataFrame):
    """Point every tool function at a user-supplied dataset instead of the bundled sample data."""
    _OVERRIDE["equip"] = equipment_df
    _OVERRIDE["daily"] = daily_df


def reset_data_source():
    """Revert to the bundled sample dataset."""
    _OVERRIDE["equip"] = None
    _OVERRIDE["daily"] = None


def using_custom_data() -> bool:
    return _OVERRIDE["daily"] is not None


def _load_data():
    if _OVERRIDE["daily"] is not None:
        daily = _OVERRIDE["daily"].copy()
        equip = _OVERRIDE["equip"].copy()
    else:
        daily = pd.read_csv(DAILY_PATH, parse_dates=["date"])
        equip = pd.read_csv(EQUIP_PATH)
    daily["date"] = pd.to_datetime(daily["date"])
    df = daily.merge(equip, on=["equipment_id", "equipment_type", "project"])
    return df


# ---------------------------------------------------------------------------
# Tool 1: أعلى المعدات من حيث التوقف
# ---------------------------------------------------------------------------
def get_top_downtime_equipment(top_n: int = 5) -> dict:
    """يرجع المعدات الأكثر توقفًا (Downtime) مع نسبة الاستخدام والتوقف."""
    df = _load_data()
    agg = df.groupby(["equipment_id", "equipment_type", "project"]).agg(
        operating_hours=("operating_hours", "sum"),
        downtime_hours=("downtime_hours", "sum"),
        maintenance_events=("maintenance_flag", "sum"),
    ).reset_index()
    agg["downtime_rate_%"] = (
        agg["downtime_hours"] / (agg["operating_hours"] + agg["downtime_hours"]) * 100
    ).round(1)
    top = agg.sort_values("downtime_rate_%", ascending=False).head(top_n)

    return {
        "tool": "get_top_downtime_equipment",
        "data": top.to_dict(orient="records"),
        "narrative_hint": (
            f"Top {top_n} equipment by downtime rate, sorted descending. "
            "Compare each unit's downtime_rate_% against the fleet average to identify outliers."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 2: المعدات التي تحتاج تدخل فوري
# ---------------------------------------------------------------------------
def get_equipment_needing_attention(downtime_threshold_pct: float = 15.0) -> dict:
    """يحدد المعدات التي تحتاج تدخل فوري بناءً على تركيبة من Downtime + Maintenance + Fuel anomaly."""
    df = _load_data()
    agg = df.groupby(["equipment_id", "equipment_type", "project"]).agg(
        operating_hours=("operating_hours", "sum"),
        downtime_hours=("downtime_hours", "sum"),
        fuel_l=("fuel_consumption_l", "sum"),
        maintenance_events=("maintenance_flag", "sum"),
    ).reset_index()
    agg["downtime_rate_%"] = (
        agg["downtime_hours"] / (agg["operating_hours"] + agg["downtime_hours"]) * 100
    ).round(1)
    agg["fuel_eff_l_per_hr"] = (agg["fuel_l"] / agg["operating_hours"]).round(2)

    # المقارنة العادلة: كل معدة تُقارن بمتوسط *نوعها* هي، مش بمتوسط كل الأسطول
    # (لأن شاحنة قلابة بطبيعتها تستهلك وقود أكتر من رافعة مثلاً - مش ده anomaly)
    type_avg_fuel_eff = agg.groupby("equipment_type")["fuel_eff_l_per_hr"].transform("mean")
    agg["fuel_vs_type_avg_%"] = ((agg["fuel_eff_l_per_hr"] / type_avg_fuel_eff - 1) * 100).round(1)

    maint_mean, maint_std = agg["maintenance_events"].mean(), agg["maintenance_events"].std()
    maint_threshold = maint_mean + 1.5 * maint_std  # outlier حقيقي، مش أي معدة فوق المتوسط بشوية

    flagged = agg[
        (agg["downtime_rate_%"] >= downtime_threshold_pct)
        | (agg["maintenance_events"] >= maint_threshold)
        | (agg["fuel_vs_type_avg_%"] >= 20)
    ].copy()

    reasons = []
    for _, row in flagged.iterrows():
        r = []
        if row["downtime_rate_%"] >= downtime_threshold_pct:
            r.append(f"High downtime ({row['downtime_rate_%']}%)")
        if row["fuel_vs_type_avg_%"] >= 20:
            r.append(f"Fuel use {row['fuel_vs_type_avg_%']}% above its own type average ({row['equipment_type']})")
        if row["maintenance_events"] >= maint_threshold:
            r.append(f"Abnormally frequent maintenance ({int(row['maintenance_events'])} events vs fleet avg {maint_mean:.1f})")
        reasons.append(" + ".join(r))
    flagged["reason"] = reasons
    flagged = flagged.sort_values("downtime_rate_%", ascending=False)

    return {
        "tool": "get_equipment_needing_attention",
        "data": flagged[["equipment_id", "equipment_type", "project", "downtime_rate_%",
                          "fuel_eff_l_per_hr", "fuel_vs_type_avg_%", "maintenance_events", "reason"]].to_dict(orient="records"),
        "narrative_hint": "Equipment requiring immediate intervention, with the main reason for each.",
    }


# ---------------------------------------------------------------------------
# Tool 3: تحليل سبب انخفاض معدل الاستخدام (Utilization)
# ---------------------------------------------------------------------------
def explain_utilization_trend(project: str | None = None) -> dict:
    """يحلل اتجاه معدل الاستخدام أسبوعيًا (لكل الأسطول أو لمشروع محدد) ويحدد إن كان في تراجع."""
    df = _load_data()
    if project:
        df = df[df["project"] == project]
        if df.empty:
            return {"tool": "explain_utilization_trend", "error": f"No project found named {project}"}

    df["week"] = df["date"].dt.isocalendar().week
    weekly = df.groupby("week").apply(
        lambda x: x["operating_hours"].sum() / (x["operating_hours"].sum() + x["downtime_hours"].sum()) * 100
    ).reset_index(name="utilization_%")

    first3 = weekly["utilization_%"].head(3).mean()
    last3 = weekly["utilization_%"].tail(3).mean()
    delta = round(last3 - first3, 1)

    # تحديد السبب المرجّح: تحليل توزيع الـ downtime حسب نوع المعدة في آخر الفترة
    recent_cutoff = df["date"].max() - pd.Timedelta(days=21)
    recent = df[df["date"] >= recent_cutoff]
    downtime_by_type = recent.groupby("equipment_type")["downtime_hours"].sum().sort_values(ascending=False)
    likely_driver = downtime_by_type.index[0] if not downtime_by_type.empty else None

    return {
        "tool": "explain_utilization_trend",
        "scope": project or "Entire fleet",
        "weekly_trend": weekly.to_dict(orient="records"),
        "first_3_weeks_avg_%": round(first3, 1),
        "last_3_weeks_avg_%": round(last3, 1),
        "change_%": delta,
        "likely_driver_equipment_type": likely_driver,
        "narrative_hint": (
            "Compare first_3_weeks_avg with last_3_weeks_avg. If change_% is negative and large, "
            "explain it using likely_driver_equipment_type (the equipment type contributing most to downtime in the last 3 weeks)."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 4: تحليل أسباب ارتفاع استهلاك الوقود
# ---------------------------------------------------------------------------
def analyze_fuel_consumption(equipment_id: str | None = None) -> dict:
    """يكتشف القفزات غير الطبيعية (Anomalies) في استهلاك الوقود مقارنة بمتوسط المعدة نفسها."""
    df = _load_data()
    if equipment_id:
        df = df[df["equipment_id"] == equipment_id]
        if df.empty:
            return {"tool": "analyze_fuel_consumption", "error": f"لا توجد معدة باسم {equipment_id}"}

    df = df.sort_values("date")
    results = []
    for eq_id, g in df.groupby("equipment_id"):
        g = g.copy()
        g["fuel_per_hr"] = g["fuel_consumption_l"] / g["operating_hours"].replace(0, np.nan)
        baseline = g["fuel_per_hr"].iloc[: max(1, len(g) // 2)].mean()  # أول نصف الفترة كـ baseline
        recent = g["fuel_per_hr"].tail(14).mean()  # آخر أسبوعين
        pct_change = round(((recent - baseline) / baseline) * 100, 1) if baseline else 0
        if abs(pct_change) >= 15:  # اعتبره anomaly لو تغيّر 15% أو أكتر
            results.append({
                "equipment_id": eq_id,
                "equipment_type": g["equipment_type"].iloc[0],
                "baseline_l_per_hr": round(baseline, 2),
                "recent_l_per_hr": round(recent, 2),
                "change_%": pct_change,
                "flag": "Suspicious increase" if pct_change > 0 else "Notable decrease",
            })

    results = sorted(results, key=lambda x: abs(x["change_%"]), reverse=True)
    return {
        "tool": "analyze_fuel_consumption",
        "anomalies_found": len(results),
        "data": results,
        "narrative_hint": (
            "These units show an abnormal change in fuel consumption compared to their own typical performance. "
            "A sudden increase is usually a sign of a mechanical issue (leak, clogged filter, engine problem) rather than just increased usage."
        ),
    }


# ---------------------------------------------------------------------------
# Tool 5: تقرير أداء الأسطول الشامل
# ---------------------------------------------------------------------------
def generate_fleet_report() -> dict:
    """يجمع كل المؤشرات في تقرير واحد شامل يصلح كأساس لتقرير أداء شهري."""
    df = _load_data()
    total_hours = df["operating_hours"].sum()
    total_downtime = df["downtime_hours"].sum()
    total_fuel = df["fuel_consumption_l"].sum()

    by_project = df.groupby("project").agg(
        operating_hours=("operating_hours", "sum"),
        downtime_hours=("downtime_hours", "sum"),
        fuel_l=("fuel_consumption_l", "sum"),
    ).reset_index()
    by_project["utilization_%"] = (
        by_project["operating_hours"] / (by_project["operating_hours"] + by_project["downtime_hours"]) * 100
    ).round(1)

    top_issues = get_top_downtime_equipment(3)["data"]
    fuel_anomalies = analyze_fuel_consumption()["data"]

    return {
        "tool": "generate_fleet_report",
        "period": f"{df['date'].min().date()} - {df['date'].max().date()}",
        "fleet_size": df["equipment_id"].nunique(),
        "total_operating_hours": round(total_hours, 1),
        "total_downtime_hours": round(total_downtime, 1),
        "overall_utilization_%": round(total_hours / (total_hours + total_downtime) * 100, 1),
        "total_fuel_l": round(total_fuel, 1),
        "by_project": by_project.to_dict(orient="records"),
        "top_downtime_equipment": top_issues,
        "fuel_anomalies": fuel_anomalies,
        "narrative_hint": "Use this as the basis for a monthly performance report: overview + top 3 issues + recommendations.",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_top_downtime_equipment(3), ensure_ascii=False, indent=2, default=str))


Tools addition · PY
 
# ---------------------------------------------------------------------------
# Tool 6: تنبؤ حقيقي بالمخاطر المستقبلية (اتجاه فعلي مبني على البيانات)
# ---------------------------------------------------------------------------
def forecast_equipment_risk(horizon_days: int = 30, downtime_alert_threshold: float = 20.0) -> dict:
    """
    تنبؤ حقيقي (مش أرقام ثابتة): يحسب اتجاه معدل التوقف أسبوعيًا لكل معدة
    خلال آخر 8 أسابيع، ويمد الاتجاه (linear trend) للأمام Xهورايزون يوم.
    r2_fit_quality يعكس مدى انتظام الاتجاه (كلما قرب من 1 كان الاتجاه أوضح وأقل ضجيج).
    """
    df = _load_data()
    max_date = df["date"].max()
    results = []
 
    for eq_id, g in df.groupby("equipment_id"):
        g = g.set_index("date").sort_index()
        weekly = g.resample("W").agg(
            operating_hours=("operating_hours", "sum"),
            downtime_hours=("downtime_hours", "sum"),
        ).reset_index()
        weekly["rate_%"] = (
            weekly["downtime_hours"] / (weekly["operating_hours"] + weekly["downtime_hours"]).replace(0, np.nan) * 100
        ).fillna(0)
        weekly = weekly.tail(8)
        if len(weekly) < 4:
            continue
 
        x = np.arange(len(weekly))
        y = weekly["rate_%"].values
        slope, intercept = np.polyfit(x, y, 1)
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = round(max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0.0, 2)
 
        future_x = x.max() + (horizon_days / 7)
        projected = float(np.clip(slope * future_x + intercept, 0, 100))
 
        # تقدير موعد الصيانة القادمة من متوسط الفاصل بين أحداث الصيانة السابقة
        maint_dates = g.loc[g["maintenance_flag"] == 1].index.sort_values()
        days_until_maintenance = None
        if len(maint_dates) >= 2:
            avg_interval = maint_dates.to_series().diff().dt.days.dropna().mean()
            days_since_last = (max_date - maint_dates.max()).days
            days_until_maintenance = max(0, round(avg_interval - days_since_last))
 
        results.append({
            "equipment_id": eq_id,
            "equipment_type": g["equipment_type"].iloc[0] if "equipment_type" in g.columns else None,
            "project": g["project"].iloc[0] if "project" in g.columns else None,
            "current_downtime_rate_%": round(y[-1], 1),
            "trend_%_per_week": round(slope, 2),
            "projected_downtime_rate_%": round(projected, 1),
            "r2_fit_quality": r2,
            "days_until_next_maintenance_est": days_until_maintenance,
            "risk_flag": bool(projected >= downtime_alert_threshold or (days_until_maintenance is not None and days_until_maintenance <= 14)),
        })
 
    results = sorted(results, key=lambda r: r["projected_downtime_rate_%"], reverse=True)
    return {
        "tool": "forecast_equipment_risk",
        "horizon_days": horizon_days,
        "data": results,
        "narrative_hint": (
            "projected_downtime_rate_% extrapolates each unit's own weekly trend forward. "
            "r2_fit_quality shows how reliable that trend is (low = noisy history, treat the number as a rough signal, not a guarantee). "
            "risk_flag units deserve inspection priority."
        ),
    }
 
 
# ---------------------------------------------------------------------------
# Tool 7: حاسبة ROI شفافة (صيغة واضحة، مو رقم جاهز)
# ---------------------------------------------------------------------------
def calculate_roi_potential(hourly_equipment_value: float = 150.0, horizon_days: int = 30) -> dict:
    """
    يحسب التوفير المتوقع لو المعدات المعرضة للخطر رجعت لمعدل توقف الأسطول العادي.
    hourly_equipment_value: القيمة التشغيلية التقديرية لساعة تشغيل واحدة (ريال/دولار)،
    هذا رقم قابل للتعديل من المستخدم، مو مفروض كحقيقة ثابتة.
    """
    df = _load_data()
    fleet_avg_rate = (
        df["downtime_hours"].sum() / (df["operating_hours"].sum() + df["downtime_hours"].sum()) * 100
    )
 
    risk = forecast_equipment_risk(horizon_days=horizon_days)["data"]
    flagged = [r for r in risk if r["risk_flag"]]
 
    breakdown = []
    total_hours_saved = 0.0
    for r in flagged:
        eq_daily_hours = df[df["equipment_id"] == r["equipment_id"]]["operating_hours"].tail(30).mean()
        rate_gap = max(0.0, r["projected_downtime_rate_%"] - fleet_avg_rate) / 100
        hours_at_risk = eq_daily_hours * horizon_days * rate_gap
        total_hours_saved += hours_at_risk
        breakdown.append({
            "equipment_id": r["equipment_id"],
            "extra_downtime_hours_if_untreated": round(hours_at_risk, 1),
        })
 
    estimated_savings = round(total_hours_saved * hourly_equipment_value, 0)
 
    return {
        "tool": "calculate_roi_potential",
        "assumption_hourly_equipment_value": hourly_equipment_value,
        "fleet_avg_downtime_rate_%": round(fleet_avg_rate, 1),
        "flagged_units_count": len(flagged),
        "total_at_risk_hours_next_%d_days" % horizon_days: round(total_hours_saved, 1),
        "estimated_savings_if_addressed": estimated_savings,
        "breakdown": breakdown,
        "formula": "Σ (unit's avg daily hours × horizon_days × (projected_rate − fleet_avg_rate)) × hourly_equipment_value",
        "narrative_hint": "This is a transparent estimate, not a guarantee — it depends on the hourly_equipment_value assumption, which the user should adjust to match their real fleet economics.",
    }
 

