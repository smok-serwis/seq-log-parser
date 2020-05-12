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
entries_dropped = getMetric('entries.dropped', 'counter')
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


def generate_item_for(j: int, env_name: str, env_matcher=lambda x: x, default=None):
    if env_name in os.environ:
        return env_matcher(os.environ[env_name])
    elif f'{env_name}{j}' in os.environ:
        return env_matcher(os.environ[f'{env_name}{j}'])
    else:
        return default


if 'REGEX' in os.environ:
    REGEX_LIST = [re.compile(generate_item_for(0, 'REGEX'))]
    CUSTOM_PROPERTIES = [generate_item_for(0, 'REGEX_PROPERTY', lambda x: x.split('=', 1))]
    OVERWRITE_WITH = [generate_item_for(0, 'OVERWRITE_CONTENTS')]
    SEQ_LOG_LEVEL = [generate_item_for(0, 'SEQ_LOG_LEVEL')]
    STORE_IN_ENTRY = [generate_item_for(0, 'STORE_IN_ENTRY', lambda x: x == 'True', False)]
    DROP_ENTRIES = [generate_item_for(0, 'DROP_ENTRIES', lambda x: x == 'True', False)]
else:
    REGEX_LIST = []
    CUSTOM_PROPERTIES = []
    OVERWRITE_WITH = []
    SEQ_LOG_LEVEL = []
    STORE_IN_ENTRY = []
    DROP_ENTRIES = []
    for i in itertools.count(1):
        if f'REGEX{i}' in os.environ:
            regex = os.environ[f'REGEX{i}']
            logger.info(f'Loading regex {repr(regex)}')
            REGEX_LIST.append(re.compile(regex))
            CUSTOM_PROPERTIES.append(generate_item_for(i, 'REGEX_PROPERTY', lambda x: x.split('=', 1)))
            OVERWRITE_WITH.append(generate_item_for(i, 'OVERWRITE_CONTENTS'))
            SEQ_LOG_LEVEL.append(generate_item_for(i, 'SEQ_LOG_LEVEL'))
            STORE_IN_ENTRY.append(generate_item_for(i, 'STORE_IN_ENTRY', lambda x: x == 'True', False))
            DROP_ENTRIES.append(generate_item_for(i, 'DROP_ENTRIES', lambda x: x == 'True', False))
        else:
            break


logger.info(f'Proceeding with configuration of {REGEX_LIST} {CUSTOM_PROPERTIES} {OVERWRITE_WITH} {SEQ_LOG_LEVEL} {STORE_IN_ENTRY} {DROP_ENTRIES}')


class NoMatchingRegex(Exception):
    pass


def transform_entry(entry):
    """Note that this will modify the entry in-place"""
    message_field = entry[FIELD_TO_PARSE]
    total_entries.runtime(+1)
    i = 0
    for regex, prop, overwrite_with, level_to, store_in_entry, should_drop in zip(REGEX_LIST,
                                                                                  CUSTOM_PROPERTIES,
                                                                                  OVERWRITE_WITH,
                                                                                  SEQ_LOG_LEVEL,
                                                                                  STORE_IN_ENTRY,
                                                                                  DROP_ENTRIES):
        i += 1
        logger.debug(f'Matching {repr(message_field)} against {regex.pattern}')
        match = regex.match(message_field)
        if match:

            matched_regexes.runtime(+1, regex=regex.pattern)

            if should_drop:
                entries_dropped.runtime(+1)
                return

            if 'Properties' not in entry and not store_in_entry:
                entry['Properties'] = {}

            for key, value in match.groupdict().items():
                if store_in_entry:
                    entry[key] = value
                else:
                    entry['Properties'][key] = value

            if prop is not None:
                prop_key, prop_value = prop
                if store_in_entry:
                    entry[prop_key] = prop_value
                else:
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
        raise NoMatchingRegex('No regex would match "%s"' % (message_field, ))

    logger.debug(f'Successfully processed entry {entry}, matched regex {i}')

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
            v = transform_entry(entry)
            if v is None:
                continue
            new_entries.append(v)
        except NoMatchingRegex:
            logger.info('Error processing entry %s"', entry)
            new_entries.append(entry)

    if not new_entries:
        return {}

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
