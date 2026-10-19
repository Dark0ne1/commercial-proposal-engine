"""Linux RQ worker; Windows local smoke uses RQ SimpleWorker in tests."""

import logging

from rq import Queue, Worker
from rq.serializers import JSONSerializer

from app.processing import connection

logging.basicConfig(level=logging.INFO)
if __name__ == "__main__":
    redis = connection(worker=True)
    Worker(
        [Queue("proposals", connection=redis, serializer=JSONSerializer)],
        connection=redis,
        serializer=JSONSerializer,
    ).work()
