from __future__ import annotations

from datetime import date, datetime, timedelta


def _parse_iso_date(value: str) -> datetime:
    return datetime.strptime(str(value).strip(), "%Y-%m-%d")


def automatic_date_values(start_date: str, end_date: str) -> dict[str, str]:
    """Derive the editable date defaults from one e-commerce reporting period."""
    start = _parse_iso_date(start_date)
    end = _parse_iso_date(end_date)
    month_start = end.replace(day=1)
    kepule_anchor = max(start, month_start)
    return {
        "库存快照日期": start.strftime("%Y-%m-%d"),
        "开普乐销售日期": kepule_anchor.strftime("%Y-%m-%d"),
        "开普乐库存日期": kepule_anchor.strftime("%Y-%m-%d"),
    }


def current_reporting_period(now: date | datetime | None = None) -> dict[str, str]:
    """Build the current Monday-to-Sunday reporting period for GUI defaults."""
    if isinstance(now, datetime):
        current_day = now.date()
    else:
        current_day = now or date.today()
    start = current_day - timedelta(days=current_day.weekday())
    end = start + timedelta(days=6)
    iso_year, iso_week, _ = start.isocalendar()
    return {
        "周期类型": "周",
        "周次编码": f"{iso_year}W{iso_week:02d}",
        "开始日期": start.isoformat(),
        "结束日期": end.isoformat(),
    }
