# Copyright 2020 SMOK sp. z o. o.
import itertools
import os
import logging
import requests
import re
import json
from flask import Flask, request
from flask_json import FlaskJSON, as_json
from flask_satella_metrics.prometheus_exporter import PrometheusExporter
from satella.instrumentation.metrics import getMetric

matched_regexes = getMetric('matched.regex', 'counter')
matched_nothing = getMetric('matched.nothing', 'counter')
total_entries = getMetric('entries.total', 'counter')
calls_made = getMetric('entries.calls', 'counter')

seq_successes = getMetric('seq.successes', 'counter')
seq_failures = getMetric('seq.failures', 'counter')

logger = logging.getLogger(__name__)

app = Flask(__name__)
FlaskJSON(app)

app.register_blueprint(PrometheusExporter())

SERVER_URL = os.environ['SEQ_ADDRESS']
if not SERVER_URL.endswith('/'):
    SERVER_URL = SERVER_URL + '/'

SEQ_LOG_LEVEL_FIELDS = {'@L', '@l', '@Level'}

FIELD_TO_PARSE = os.environ.get('FIELD_TO_PARSE', '@mt')


if 'REGEX' in os.environ:
    REGEX_LIST = [re.compile(os.environ['REGEX'])]
    if 'REGEX_PROPERTY' in os.environ:
        CUSTOM_PROPERTIES = [os.environ.split('=', 1)]
    if 'OVERWRITE_CONTENTS' in os.environ:
        OVERWRITE_WITH = [os.environ['OVERWRITE_CONTENTS']]
    else:
        OVERWRITE_WITH = [None]
    if 'SEQ_LOG_LEVEL' in os.environ:
        SEQ_LOG_LEVEL = [os.environ['SEQ_LOG_LEVEL']]
    else:
        SEQ_LOG_LEVEL = [None]
else:
    REGEX_LIST = []
    CUSTOM_PROPERTIES = []
    OVERWRITE_WITH = []
    SEQ_LOG_LEVEL = []
    for i in itertools.count(1):
        if f'REGEX{i}' in os.environ:
            REGEX_LIST.append(re.compile(os.environ[f'REGEX{i}']))
            if f'REGEX_PROPERTY{i}' in os.environ:
                CUSTOM_PROPERTIES.append(os.environ[f'REGEX_PROPERTY{i}'].split('=', 1))
            else:
                CUSTOM_PROPERTIES.append(None)

            if 'OVERWRITE_CONTENTS' in os.environ:
                OVERWRITE_WITH.append(os.environ['OVERWRITE_CONTENTS'])
            elif f'OVERWRITE_CONTENTS{i}' in os.environ:
                OVERWRITE_WITH.append(os.environ[f'OVERWRITE_CONTENTS{i}'])
            else:
                OVERWRITE_WITH.append(None)

            if 'SEQ_LOG_LEVEL' in os.environ:
                SEQ_LOG_LEVEL.append(os.environ['SEQ_LOG_LEVEL'])
            elif f'SEQ_LOG_LEVEL{i}' in os.environ:
                SEQ_LOG_LEVEL.append(os.environ[f'SEQ_LOG_LEVEL{i}'])
            else:
                SEQ_LOG_LEVEL.append(None)
        else:
            break


def transform_entry(entry):
    """Note that this will modify the entry in-place"""
    message_field = entry[FIELD_TO_PARSE]
    total_entries.runtime(+1)

    for regex, prop, overwrite_with, level_to in zip(REGEX_LIST, CUSTOM_PROPERTIES, OVERWRITE_WITH, SEQ_LOG_LEVEL):
        if match := regex.match(message_field):

            matched_regexes.runtime(+1, regex=regex.pattern)

            if 'Properties' not in entry:
                entry['Properties'] = {}

            for key, value in match.groupdict().items():
                entry['Properties'][key] = value

            if prop is not None:
                prop_key, prop_value = prop
                entry['Properties'][prop_key] = prop_value

            if overwrite_with:
                fmt = overwrite_with.format(**match.groupdict())
                if 'MessageTemplate' in entry:
                    entry['MessageTemplate'] = fmt
                entry[FIELD_TO_PARSE] = fmt

            if level_to:
                # Remove all existing levels
                for field in SEQ_LOG_LEVEL_FIELDS:
                    if field in entry:
                        del entry[field]

                # Assign new level
                level = level_to.format(**match.groupdict())
                entry['@l'] = level.upper()

            break
    else:
        matched_nothing.runtime(+1)
        raise ValueError('No regex would match "%s"' % (message_field, ))

    logger.debug(f'Successfully processed entry {entry}')

    return entry


@app.route('/api/events/raw', methods=['POST'])
@as_json
def ingest():
    # Try to obtain API key
    api_key_headers = request.headers.get('X-Seq-ApiKey')
    api_key_get = request.args.get('apiKey')

    api_key = api_key_headers or api_key_get
    has_api_key = api_key is not None

    calls_made.runtime(+1)

    # Decode input
    is_clef = 'clef' in request.args or \
              request.headers.get('Content-Type', '').startswith('application/vnd.serilog.clef')
    try:
        if is_clef:
            entries = [json.loads(entry.strip()) for entry in request.data.decode('utf8').split('\n') if entry.strip()]
        else:
            data = request.get_json()
            entries = data['Events']

    except json.decoder.JSONDecodeError as e:
        logger.warning('Invalid payload, type was %s', 'clef' if is_clef else 'json',
                       exc_info=e,
                       extra={'payload': request.data})
    new_entries = []
    for entry in entries:
        try:
            new_entries.append(transform_entry(entry))
        except ValueError as e:
            logger.info('Error processing entry %s"', entry)
            new_entries.append(entry)

    # Prepare headers
    headers = {'Content-Type': 'application/vnd.serilog.clef'}
    if has_api_key:
        headers['X-Seq-ApiKey'] = api_key

    # Send the message
    try:
        data = '\n'.join(json.dumps(entry) for entry in new_entries)
        resp = requests.post(SERVER_URL+'api/events/raw', data=data, headers=headers)
        resp.raise_for_status()
        seq_successes.runtime(+1)
    except requests.RequestException as e:
        seq_failures.runtime(+1)
        try:
            resp
        except NameError:
            logger.error('Failed connecting the Seq server', exc_info=e)
        else:
            logger.error(f'Got an error response from the Seq server: {resp.status_code} {resp.text}',
                         exc_info=e)

    return {}
