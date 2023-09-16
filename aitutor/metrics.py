from prometheus_client import Counter, Gauge, Histogram


inbound_messages = Counter(
        'inbound_messages',
        'Number of inbound messages from Slack',
        ['workspace', 'channel', 'user'],
        )

replies = Counter(
        'replies',
        'Number of replies successfully sent to Slack',
        ['workspace', 'channel', 'user'],
        )

reply_duration = Histogram(
        'reply_duration',
        'Duration of replies',
        ['relevant', 'success', 'workspace', 'channel'],
        )

engine_quota = Gauge(
        'engine_quota',
        'TPM quota usage for the engine',
        ['engine'],
        )

engine_usage = Histogram(
        'engine_usage',
        'Token usage for user requests',
        ['direction', 'model', 'engine', 'workspace', 'channel', 'user'],
        )

in_flight = Gauge(
        'in_flight',
        'Number of in-flight requests',
        ['app'],
        )

event_count = Counter(
        'event_count',
        'Number of events processed',
        ['app', 'event_type', 'success', 'workspace', 'channel_type', 'channel'],
        )
