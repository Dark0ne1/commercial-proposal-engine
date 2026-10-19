from datetime import timedelta
from socket import gethostname

from rq import Worker

from app.models import as_utc, now
from app.processing import connection

workers = Worker.all(connection=connection())
raise SystemExit(
    0
    if any(
        w.hostname == gethostname()
        and w.last_heartbeat
        and now() - as_utc(w.last_heartbeat) < timedelta(seconds=480)
        for w in workers
    )
    else 1
)
