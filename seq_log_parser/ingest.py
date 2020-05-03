import itertools
import os
import logging
import requests
import re
import json
from flask import Flask, request
from flask_json import FlaskJSON

logger = logging.getLogger(__name__)

app = Flask(__name__)
FlaskJSON(app)

SERVER_URL = os.environ['SEQ_ADDRESS']
if not SERVER_URL.endswith('/'):
    SERVER_URL = SERVER_URL + '/'


FIELD_TO_PARSE = os.environ.get('FIELD_TO_PARSE', '@mt')

OVERWRITE_CONTENTS = os.environ.get('OVERWRITE_CONTENTS')


if 'REGEX' in os.environ:
    REGEX_LIST = [re.compile(os.environ['REGEX'])]
else:
    REGEX_LIST = []
    for i in itertools.count(1):
        if f'REGEX{i}' in os.environ:
            REGEX_LIST.append(re.compile(os.environ[f'REGEX{i}']))
        else:
            break


def transform_entry(entry):
    """Note that this will modify the entry in-place"""
    message_field = entry[FIELD_TO_PARSE]

    for regex in REGEX_LIST:
        if match := regex.match(message_field):

            if 'Properties' not in entry:
                entry['Properties'] = {}

            for key, value in match.groupdict():
                entry['Properties'][key] = value

            if OVERWRITE_CONTENTS:
                entry[FIELD_TO_PARSE] = match.group(OVERWRITE_CONTENTS)

            break
    else:
        raise ValueError('No regex would match')

    return entry


@app.route('/api/events/raw')
def ingest():
    # Try to obtain API key
    api_key_headers = request.headers.get('X-Seq-ApiKey')
    api_key_get = request.args.get('apiKey')

    api_key = api_key_headers or api_key_get
    has_api_key = api_key is not None

    # Decode input
    is_clef = 'clef' in request.args or request.headers.get('Content-Type') == 'application/vnd.serilog.clef'
    try:
        if is_clef:
            entries = [json.loads(entry.strip()) for entry in request.data.split('\n') if entry.strip()]
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
            logger.warning('Error processing entry', exc_info=e, extra={'entry': entry})

    # Prepare headers
    headers = {'Content-Type': 'application/json'}
    if has_api_key:
        headers['X-Seq-ApiKey'] = api_key

    # Send the message
    try:
        resp = requests.post(SERVER_URL+'api/events/raw', json={'Events': new_entries}, headers=headers)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error('Failed connecting the Seq server', exc_info=e)
