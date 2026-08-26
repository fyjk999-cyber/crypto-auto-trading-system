# UTC TIME POLICY

- All review scheduling uses timezone-aware UTC.
- Production clock: UtcClock.now() -> datetime.now(UTC).
- Tests use FakeUtcClock and are TZ-independent.
- No datetime.now()/date.today()/naive local time in evolution scheduling.
