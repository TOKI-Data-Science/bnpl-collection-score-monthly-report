from __future__ import annotations

import argparse
import html
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import oracledb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from dotenv import load_dotenv
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent


def aged_before(as_of: date, maturity_days: int = 25) -> date:
    return as_of - timedelta(days=maturity_days) + timedelta(days=1)


def load_data(sql_path: Path, cutoff: date) -> pd.DataFrame:
    sql = sql_path.read_text(encoding="utf-8")
    required = ("DWH_USER", "DWH_PASSWORD", "DWH_DSN")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    with oracledb.connect(
        user=os.environ["DWH_USER"],
        password=os.environ["DWH_PASSWORD"],
        dsn=os.environ["DWH_DSN"],
    ) as connection:
        return pd.read_sql(
            sql,
            connection,
            params={"aged_before": cutoff.isoformat()},
        )


def auc_or_nan(group: pd.DataFrame) -> float:
    if group["event"].nunique() < 2:
        return np.nan
    score = pd.to_numeric(group["collection_score"], errors="coerce")
    valid = score.notna() & group["event"].notna()
    if group.loc[valid, "event"].nunique() < 2:
        return np.nan
    auc = roc_auc_score(group.loc[valid, "event"], score[valid])
    return auc if os.getenv("HIGH_SCORE_IS_RISK", "false").lower() == "true" else 1 - auc


def prepare_data(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = frame.columns.str.lower()
    required = {"user_id", "base_date", "collection_score", "collection_score_grade", "event"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing columns: {', '.join(sorted(missing))}")
    frame["base_date"] = pd.to_datetime(frame["base_date"])
    frame["event"] = pd.to_numeric(frame["event"], errors="raise").astype(int)
    if not frame["event"].isin([0, 1]).all():
        raise ValueError("event must contain only 0 and 1")
    frame["month"] = frame["base_date"].dt.to_period("M").astype(str)
    return frame


def metric_tables(frame: pd.DataFrame, cutoff: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = (
        frame.groupby(frame["base_date"].dt.date, dropna=False)
        .apply(auc_or_nan, include_groups=False)
        .rename("auc")
        .reset_index()
    )
    monthly_outcomes = (
        frame.groupby("month", dropna=False)["event"]
        .agg(customers="size", events="sum", event_rate="mean")
        .reset_index()
    )
    monthly_auc = frame.groupby("month", dropna=False).apply(auc_or_nan, include_groups=False).rename("auc").reset_index()
    monthly = monthly_outcomes.merge(monthly_auc, on="month")
    month_end = pd.to_datetime(monthly["month"]) + pd.offsets.MonthEnd(0)
    effective_cutoff = pd.Timestamp(cutoff) if cutoff else frame["base_date"].max().normalize() + pd.Timedelta(days=1)
    monthly["coverage_through"] = month_end.where(month_end < effective_cutoff, effective_cutoff - pd.Timedelta(days=1))
    monthly["status"] = np.where(month_end < effective_cutoff, "Complete", "Partial - aged rows only")
    grade = (
        frame.groupby("collection_score_grade", dropna=False)["event"]
        .agg(customers="size", events="sum", event_rate="mean")
        .reset_index()
    )
    grade["grade_order"] = pd.to_numeric(grade["collection_score_grade"], errors="coerce")
    grade = grade.sort_values(["grade_order", "collection_score_grade"], na_position="last").drop(columns="grade_order")
    return daily, monthly, grade


def figure_html(figure) -> str:
    return pio.to_html(figure, include_plotlyjs=False, full_html=False, config={"displayModeBar": False})


def render_report(frame: pd.DataFrame, output: Path, cutoff: date, as_of: date) -> None:
    daily, monthly, grade = metric_tables(frame, cutoff)
    train_auc = 0.722
    oot_auc = 0.688
    monthly_x = ["Train", "OOT-valid", *monthly["month"].tolist()]
    monthly_y = [train_auc, oot_auc, *monthly["auc"].tolist()]
    monthly_chart = go.Figure(go.Scatter(
        x=monthly_x, y=monthly_y, mode="lines+markers+text", text=[f"{value:.3f}" for value in monthly_y],
        textposition="top center", line=dict(color="#22d3ee", width=3, shape="spline", smoothing=0.8),
        marker=dict(size=9, color="#22d3ee", line=dict(color="#cffafe", width=1)),
        hovertemplate="%{x}<br>AUC %{y:.3f}<extra></extra>",
    ))
    daily_chart = go.Figure(go.Scatter(
        x=daily["base_date"], y=daily["auc"], mode="lines+markers",
        line=dict(color="#22d3ee", width=2.5, shape="spline", smoothing=0.7),
        marker=dict(size=6, color="#67e8f9"), hovertemplate="%{x}<br>AUC %{y:.3f}<extra></extra>",
    ))
    grades = grade["collection_score_grade"].astype(str).tolist()
    grade_chart = go.Figure()
    grade_chart.add_bar(
        x=grades, y=grade["customers"], name="Population", marker_color="#164e63",
        hovertemplate="Grade %{x}<br>Population %{y:,}<extra></extra>",
    )
    grade_chart.add_scatter(
        x=grades, y=grade["event_rate"], name="Event rate", yaxis="y2", mode="lines+markers",
        line=dict(color="#fb923c", width=3, shape="spline", smoothing=0.8),
        marker=dict(size=8, color="#fb923c"),
        hovertemplate="Grade %{x}<br>Event rate %{y:.2%}<extra></extra>",
    )
    chart_titles = ((monthly_chart, "Monthly AUC trajectory"), (daily_chart, "Daily AUC"), (grade_chart, "Grade population & event rate"))
    for figure, title in chart_titles:
        figure.update_layout(
            title=dict(text=title, font=dict(size=16, color="#e5f9fc"), x=0.02),
            paper_bgcolor="#0b141a", plot_bgcolor="#0b141a", font=dict(family="Segoe UI", color="#8ba5af"),
            margin=dict(l=52, r=52, t=62, b=48), hoverlabel=dict(bgcolor="#10242d", font_color="#e5f9fc"),
            xaxis=dict(showgrid=False, zeroline=False, fixedrange=True),
            yaxis=dict(showgrid=False, zeroline=False, fixedrange=True),
            legend=dict(orientation="h", y=1.12, x=1, xanchor="right"),
        )
    monthly_chart.update_layout(
        xaxis=dict(
            type="category", categoryorder="array", categoryarray=monthly_x,
            tickmode="array", tickvals=monthly_x, ticktext=monthly_x,
            showgrid=False, zeroline=False, fixedrange=True,
        )
    )
    monthly_chart.update_yaxes(range=[0.45, 0.8], tickformat=".2f")
    daily_chart.update_yaxes(range=[0.45, 0.8], tickformat=".2f")
    for level, color, label in (
        (0.70, "#22c55e", "0.70"),
        (0.65, "#eab308", "0.65"),
        (0.60, "#f97316", "0.60"),
    ):
        daily_chart.add_hline(
            y=level, line_width=1.5, line_dash="dot", line_color=color,
            annotation_text=label, annotation_position="right",
            annotation_font_color=color, annotation_bgcolor="#0b141a",
        )
    grade_chart.update_layout(
        xaxis=dict(type="category", categoryorder="array", categoryarray=grades, showgrid=False, title="Grade"),
        yaxis=dict(showgrid=False, title="Population", rangemode="tozero"),
        yaxis2=dict(showgrid=False, title="Event rate", overlaying="y", side="right", tickformat=".0%", rangemode="tozero"),
        barmode="group",
    )
    overall_auc = auc_or_nan(frame)
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    latest_auc = monthly["auc"].dropna().iloc[-1] if monthly["auc"].notna().any() else np.nan
    auc_drop = oot_auc - latest_auc
    if np.isnan(latest_auc):
        action_level, action_title, action_text = "neutral", "Insufficient signal", "Latest month has only one event class. Wait for more outcomes."
    elif auc_drop >= 0.1:
        action_level, action_title, action_text = "critical", "Redevelop model", "AUC has dropped by at least 0.100 from OOT-valid. Begin model redevelopment."
    elif auc_drop >= 0.05:
        action_level, action_title, action_text = "warning", "Retrain / wait one month", "AUC has dropped by at least 0.050. Retrain now or confirm persistence next month."
    else:
        action_level, action_title, action_text = "healthy", "Continue monitoring", "AUC remains within 0.050 of OOT-valid. No model change is required."
    latest_auc_text = "N/A" if np.isnan(latest_auc) else f"{latest_auc:.3f}"
    auc_drop_text = "N/A" if np.isnan(auc_drop) else f"{auc_drop:+.3f}"
    report = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BNPL Collection Score V1</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{{--bg:#060b0f;--surface:#0b141a;--surface2:#102028;--line:#17313b;--text:#e5f9fc;--muted:#78909a;--cyan:#22d3ee}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Segoe UI",sans-serif}}
nav{{height:68px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100% - 1180px)/2));background:#081116}}
.brand{{font-size:16px;font-weight:650}} .brand span{{color:var(--cyan)}} .runtime{{color:var(--muted);font-size:12px;text-align:right}}
main{{max-width:1180px;margin:auto;padding:34px 24px 50px}} section{{margin-bottom:26px}} h2{{font-size:13px;text-transform:uppercase;color:#8ba5af;margin:0 0 12px}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}} .kpi,.chart,.action{{background:var(--surface);border:1px solid var(--line);border-radius:6px}}
.kpi{{padding:20px}} .label{{color:var(--muted);font-size:11px;text-transform:uppercase}} .value{{font-size:28px;font-weight:650;margin-top:5px}}
.chart{{min-height:390px;padding:6px}} .action{{padding:22px;border-left:3px solid var(--cyan);display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center}}
.action.critical{{border-left-color:#fb7185}} .action.warning{{border-left-color:#fbbf24}} .action.healthy{{border-left-color:#34d399}}
.action h3{{margin:0 0 5px;font-size:18px}} .action p{{margin:0;color:#8ba5af}} .delta{{font-size:24px;font-weight:650;text-align:right}} .delta small{{display:block;font-size:11px;color:var(--muted);font-weight:400}}
.meta{{color:var(--muted);font-size:12px;margin-top:10px}} footer{{color:#58707a;border-top:1px solid var(--line);padding-top:18px}}
@media(max-width:700px){{nav{{height:auto;padding-top:14px;padding-bottom:14px;gap:12px}}.kpis{{grid-template-columns:1fr}}.action{{grid-template-columns:1fr}}.delta{{text-align:left}}}}
</style></head><body><nav><div class="brand">BNPL Collection Score <span>V1</span></div><div class="runtime">Report run<br>{html.escape(generated_at)}</div></nav>
<main><section><h2>Overview</h2><div class="kpis"><div class="kpi"><div class="label">N</div><div class="value">{len(frame):,}</div></div>
<div class="kpi"><div class="label">Event rate</div><div class="value">{frame['event'].mean():.2%}</div></div>
<div class="kpi"><div class="label">Overall AUC</div><div class="value">{overall_auc:.3f}</div></div></div><div class="meta">Aged score dates through {cutoff - timedelta(days=1):%Y-%m-%d}</div></section>
<section><h2>Monthly performance</h2><div class="chart">{figure_html(monthly_chart)}</div></section>
<section><h2>Daily performance</h2><div class="chart">{figure_html(daily_chart)}</div></section>
<section><h2>Grade performance</h2><div class="chart">{figure_html(grade_chart)}</div></section>
<section><h2>Needed action</h2><div class="action {action_level}"><div><h3>{action_title}</h3><p>{action_text}</p></div><div class="delta">{auc_drop_text}<small>OOT 0.688 → latest {latest_auc_text}</small></div></div></section>
<footer>Event: overdue_days &gt;= 31 at base_date + 25. Higher collection scores indicate lower risk.</footer></main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the monthly BNPL collection score report.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--input-csv", type=Path, help="Use a local CSV instead of querying DWH.")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "report.html")
    parser.add_argument("--dry-run", action="store_true", help="Print the maturity cutoff without connecting to DWH.")
    return parser.parse_args()


def main() -> None:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    cutoff = aged_before(args.as_of)
    if args.dry_run:
        print(f"aged_before={cutoff.isoformat()} score_dates_through={cutoff - timedelta(days=1)} output={args.output}")
        return
    frame = pd.read_csv(args.input_csv) if args.input_csv else load_data(ROOT / "data.sql", cutoff)
    frame = prepare_data(frame)
    if frame.empty:
        raise RuntimeError("The selected cohort returned no rows.")
    render_report(frame, args.output, cutoff, args.as_of)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()