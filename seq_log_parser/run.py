# Copyright 2020 SMOK sp. z o. o.
import gevent.monkey
gevent.monkey.patch_all(httplib=True)

import os
import logging
from werkzeug import run_simple

logging.basicConfig(level=getattr(logging, os.environ.get('LOGGING_LEVEL', 'WARNING')))

from seq_log_parser.ingest import app


if __name__ == '__main__':

    run_simple(os.environ.get('BIND_ADDRESS', '0.0.0.0'),
               int(os.environ.get('BIND_PORT', '80')),
               app,
               threaded=True, use_reloader=False)
