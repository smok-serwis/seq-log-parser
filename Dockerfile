FROM python:3.8

ADD requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

ADD seq_log_parser /app/seq_log_parser
WORKDIR /app

CMD ["python", "-m", "seq_log_parser.run"]
