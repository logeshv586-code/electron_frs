from datetime import datetime, timezone
from typing import Optional


def parse_license_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None

    iso_s = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso_s)
    except Exception:
        dt = None

    if dt:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
        except Exception:
            continue
        return datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    return None
