FROM python:3.8

ADD requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && \
    rm -rf /root/.cache

ADD seq_log_parser /app/seq_log_parser
WORKDIR /app

LABEL maintainer="pmaslanka@smok.co"

CMD ["python", "-m", "seq_log_parser.run"]
STOPSIGNAL SIGKILL
