from datetime import datetime, timezone

from .license_dates import parse_license_datetime


def _assert_future(dt: datetime):
    now = datetime(2026, 2, 14, tzinfo=timezone.utc)
    assert dt.tzinfo is not None
    assert dt >= now


def run():
    dt = parse_license_datetime("2028-02-13T12:53:19.127Z")
    assert dt is not None
    _assert_future(dt)

    dt = parse_license_datetime("13/02/2028")
    assert dt is not None
    _assert_future(dt)

    dt = parse_license_datetime("2028-02-13")
    assert dt is not None
    _assert_future(dt)

    assert parse_license_datetime("") is None
    assert parse_license_datetime(None) is None
    assert parse_license_datetime("not-a-date") is None


if __name__ == "__main__":
    run()
