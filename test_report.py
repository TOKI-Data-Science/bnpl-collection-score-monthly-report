from datetime import date

import pandas as pd

from report import aged_before, metric_tables, prepare_data, render_report
from send_to_power_automate import build_payload


def test_cutoff_includes_all_rows_aged_25_days():
    assert aged_before(date(2026, 8, 1)) == date(2026, 7, 8)


def test_metrics_are_calculated_by_day_month_and_grade():
    frame = prepare_data(pd.DataFrame({
        "user_id": [1, 2, 3, 4],
        "base_date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02"],
        "collection_score": [0.9, 0.1, 0.8, 0.2],
        "collection_score_grade": ["A", "D", "A", "D"],
        "event": [0, 1, 0, 1],
    }))
    daily, monthly, grade = metric_tables(frame, date(2026, 6, 3))
    assert daily["auc"].tolist() == [1.0, 1.0]
    assert monthly["auc"].tolist() == [1.0]
    assert monthly["event_rate"].tolist() == [0.5]
    assert monthly["status"].tolist() == ["Partial - aged rows only"]
    assert grade["event_rate"].tolist() == [0.0, 1.0]


def test_html_report_is_generated(tmp_path):
    frame = prepare_data(pd.DataFrame({
        "user_id": [1, 2],
        "base_date": ["2026-06-01", "2026-06-01"],
        "collection_score": [0.9, 0.1],
        "collection_score_grade": ["A", "D"],
        "event": [0, 1],
    }))
    output = tmp_path / "report.html"
    render_report(frame, output, date(2026, 7, 8), date(2026, 8, 1))
    report = output.read_text(encoding="utf-8")
    assert "BNPL Collection Score V1" in report
    assert "score dates through 2026-07-07" in report
    assert "overdue_days &gt;= 31" in report
    assert "Monthly AUC trajectory" in report
    assert "Train" in report and "OOT-valid" in report
    assert "Grade population & event rate" in report
    assert "Needed action" in report
    assert '"type":"category"' in report
    assert "#fb923c" in report
    assert all(color in report for color in ("#22c55e", "#eab308", "#f97316"))


def test_power_automate_payload_contains_report(tmp_path):
    report = tmp_path / "report.html"
    report.write_text("<html>report</html>", encoding="utf-8")
    payload = build_payload(report)
    assert payload["modelName"] == "BNPL Collection Score V1"
    assert payload["reportFileName"] == "report.html"
    assert payload["reportContentBase64"] == "PGh0bWw+cmVwb3J0PC9odG1sPg=="