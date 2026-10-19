"""TEST ONLY: ephemeral Redis protocol emulator + RQ SimpleWorker for Windows QA.

Production always uses real Redis and worker.py in Compose. This helper loses
queue data when stopped; it never replaces PostgreSQL or alters demo records.
"""

import logging
import os
import socket
from threading import Thread

from fakeredis import TcpFakeServer
from redis import Redis
from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer
from rq.timeouts import TimerDeathPenalty

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = TcpFakeServer(("127.0.0.1", 16379))
    server.daemon_threads = True
    Thread(target=server.serve_forever, daemon=True).start()
    redis = Redis(host="127.0.0.1", port=16379, protocol=3)
    assert redis.ping()
    assert redis.blpop("local-queue-self-check", timeout=0.1) is None
    print("TEST ONLY — ephemeral Redis emulator at 127.0.0.1:16379, RQ SimpleWorker", flush=True)
    worker = SimpleWorker(
        [Queue("proposals", connection=redis, serializer=JSONSerializer)],
        connection=redis,
        serializer=JSONSerializer,
        prepare_for_work=False,
    )
    # TcpFakeServer's CLIENT LIST address format differs from real Redis.
    worker.hostname, worker.pid = socket.gethostname(), os.getpid()
    worker.death_penalty_class = TimerDeathPenalty
    try:
        worker.work()
    finally:
        server.shutdown()
        server.server_close()
