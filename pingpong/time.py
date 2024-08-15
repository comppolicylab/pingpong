import arrow


def convert_seconds(s: int) -> str:
    now = arrow.utcnow()
    return now.shift(seconds=s).humanize(now, only_distance=True)
