"""
FleetOps AI - Automated Test Suite
====================================
يشغّل مجموعة اختبارات فعلية على النظام كامل ويسجّل النتائج (Expected vs Actual)
في ملف JSON يُستخدم بعدين لبناء Test Report الرسمي.
"""

import sys, json, traceback
sys.path.insert(0, "src")
import pandas as pd
import tools
import agent
import ml_anomaly

results = []


def record(tc_id, name, expected, actual, passed, notes=""):
    results.append({
        "id": tc_id, "name": name, "expected": expected, "actual": actual,
        "passed": bool(passed), "notes": notes,
    })


# --------------------------------------------------------------------------
# TC-01: سلامة البيانات المولّدة
# --------------------------------------------------------------------------
try:
    daily = pd.read_csv("data/fleet_daily_logs.csv")
    equip = pd.read_csv("data/equipment_master.csv")
    ok = (len(daily) == 2700) and (equip["equipment_id"].nunique() == 30) and (daily.isnull().sum().sum() == 0)
    record("TC-01", "Data integrity (row count, no nulls, 30 units)",
           "2700 rows, 30 units, 0 null values",
           f"{len(daily)} rows, {equip['equipment_id'].nunique()} units, {daily.isnull().sum().sum()} nulls",
           ok)
except Exception as e:
    record("TC-01", "Data integrity", "No exceptions", f"Exception: {e}", False)

# --------------------------------------------------------------------------
# TC-02: صحة حساب KPI (Utilization) - مقارنة يدوية
# --------------------------------------------------------------------------
try:
    df = tools._load_data()
    sample_eq = df["equipment_id"].iloc[0]
    sub = df[df["equipment_id"] == sample_eq]
    manual_util = round(sub["operating_hours"].sum() / (sub["operating_hours"].sum() + sub["downtime_hours"].sum()) * 100, 1)
    tool_result = tools.get_top_downtime_equipment(30)["data"]
    tool_row = next(r for r in tool_result if r["equipment_id"] == sample_eq)
    tool_util = round(100 - tool_row["downtime_rate_%"], 1)
    ok = abs(manual_util - tool_util) < 0.5
    record("TC-02", f"KPI calculation accuracy (manual vs tool, {sample_eq})",
           f"Utilization match within 0.5% (manual={manual_util}%)",
           f"Tool output={tool_util}%", ok)
except Exception as e:
    record("TC-02", "KPI calculation accuracy", "No exceptions", f"Exception: {e}", False)

# --------------------------------------------------------------------------
# TC-03: عدالة مقارنة استهلاك الوقود (إصلاح الـ bug: مقارنة بالنوع مش بالكل)
# --------------------------------------------------------------------------
try:
    attention = tools.get_equipment_needing_attention()["data"]
    dump_truck_flags = [r for r in attention if r["equipment_type"] == "Dump Truck" and "استهلاك وقود" in r["reason"]]
    # المتوقع: مفيش Dump Truck اتعلّم غلط بس لأن نوعه بيستهلك وقود أكتر بطبيعته
    all_dump_trucks = tools._load_data()
    total_dump_trucks = all_dump_trucks[all_dump_trucks["equipment_type"] == "Dump Truck"]["equipment_id"].nunique()
    ok = len(dump_truck_flags) < total_dump_trucks  # مش كل الدامب تركس اتعلّموا غلط
    record("TC-03", "Fair fuel comparison (within-type, not fleet-wide)",
           "Not all Dump Trucks flagged just for being naturally fuel-heavy",
           f"{len(dump_truck_flags)}/{total_dump_trucks} Dump Trucks flagged for fuel", ok,
           "Bug found & fixed during development: initial version compared fleet-wide average, "
           "causing false positives on naturally fuel-heavy equipment types.")
except Exception as e:
    record("TC-03", "Fair fuel comparison", "No exceptions", f"Exception: {e}", False)

# --------------------------------------------------------------------------
# TC-04: اكتشاف anomaly الوقود الحقيقي (EQ-008 مزروعة في البيانات)
# --------------------------------------------------------------------------
try:
    fuel_result = tools.analyze_fuel_consumption()["data"]
    detected_ids = [r["equipment_id"] for r in fuel_result]
    ok = "EQ-008" in detected_ids
    record("TC-04", "Fuel anomaly detection (ground truth: EQ-008 was injected with a fuel spike)",
           "EQ-008 appears in anomalies list",
           f"Detected units: {detected_ids}", ok)
except Exception as e:
    record("TC-04", "Fuel anomaly detection", "No exceptions", f"Exception: {e}", False)

# --------------------------------------------------------------------------
# TC-05: تطابق ML (Isolation Forest) مع النتائج اليدوية
# --------------------------------------------------------------------------
try:
    ml_result = ml_anomaly.detect_ml_anomalies()["data"]
    ml_ids = set(r["equipment_id"] for r in ml_result)
    manual_top3 = set(r["equipment_id"] for r in tools.get_top_downtime_equipment(3)["data"])
    overlap = ml_ids & manual_top3
    ok = len(overlap) >= 2  # على الأقل 2 من أعلى 3 لازم يظهروا في الـ ML كمان
    record("TC-05", "ML anomaly detection cross-validates manual downtime ranking",
           "At least 2 of top-3 manual downtime units also flagged by Isolation Forest",
           f"Overlap: {overlap} ({len(overlap)}/3)", ok)
except Exception as e:
    record("TC-05", "ML cross-validation", "No exceptions", f"Exception: {e}", False)

# --------------------------------------------------------------------------
# TC-06: التوجيه الصحيح للأسئلة الخمسة الأساسية (Agent Routing)
# --------------------------------------------------------------------------
question_tool_map = [
    ("ما المعدات التي لديها أعلى Downtime؟", "get_top_downtime_equipment", "\"Which equipment has the highest downtime?\""),
    ("أي المعدات تحتاج إلى تدخل فوري؟", "get_equipment_needing_attention", "\"Which equipment needs urgent attention?\""),
    ("لماذا انخفض معدل استخدام المعدات؟", "explain_utilization_trend", "\"Why did utilization drop?\""),
    ("ما أسباب ارتفاع استهلاك الوقود؟", "analyze_fuel_consumption", "\"What's causing the fuel increase?\""),
    ("أنشئ لي تقريرًا عن أداء الأسطول", "generate_fleet_report", "\"Generate a fleet performance report\""),
]
for q, expected_tool, label in question_tool_map:
    try:
        actual_tool, _ = agent._route_question(q)
        ok = actual_tool == expected_tool
        record("TC-06", f"Agent routing: {label}", f"Routes to {expected_tool}", f"Routed to {actual_tool}", ok)
    except Exception as e:
        record("TC-06", f"Agent routing: {label}", f"Routes to {expected_tool}", f"Exception: {e}", False)

# --------------------------------------------------------------------------
# TC-07: التعامل الآمن مع الحالات الحدية (Edge Cases)
# --------------------------------------------------------------------------
edge_cases = [
    ("", "(empty input)"),
    ("ما هذا؟", "(vague question, Arabic)"),
    ("asdkjaslkdj", "(random gibberish)"),
    ("1234", "(numeric-only input)"),
]
for q, label in edge_cases:
    try:
        answer = agent.ask_agent(q)
        ok = isinstance(answer, str) and len(answer) > 0
        record("TC-07", f"Edge case handling: {label}",
               "No crash, returns a safe fallback answer", "Returned valid response, no exception", ok)
    except Exception as e:
        record("TC-07", f"Edge case handling: {label}",
               "No crash", f"Exception raised: {e}", False)

# --------------------------------------------------------------------------
# TC-08: بناء الملفات (تقرير PDF + عرض PPTX) بدون أخطاء
# --------------------------------------------------------------------------
import os
ok_pdf = os.path.exists("reports/FleetOps_AI_Project_Report.pdf") and os.path.getsize("reports/FleetOps_AI_Project_Report.pdf") > 1000
ok_pptx = os.path.exists("presentation/FleetOps_AI_Presentation.pptx") and os.path.getsize("presentation/FleetOps_AI_Presentation.pptx") > 1000
record("TC-08a", "Project report PDF generated successfully", "File exists, size > 1KB",
       f"Exists={os.path.exists('reports/FleetOps_AI_Project_Report.pdf')}", ok_pdf)
record("TC-08b", "Presentation PPTX generated successfully", "File exists, size > 1KB",
       f"Exists={os.path.exists('presentation/FleetOps_AI_Presentation.pptx')}", ok_pptx)

# --------------------------------------------------------------------------
# النتيجة النهائية
# --------------------------------------------------------------------------
with open("reports/test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

total = len(results)
passed = sum(1 for r in results if r["passed"])
print(f"\n{'='*60}\nإجمالي الاختبارات: {total} | ناجحة: {passed} | فاشلة: {total - passed}\n{'='*60}")
for r in results:
    status = "✅" if r["passed"] else "❌"
    print(f"{status} [{r['id']}] {r['name']}")
