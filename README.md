seq-log-parser
==============

Have you ever noticed that standard syslog or gelf
entries that Seq extracts with sqelf and squiflog are
quite bland, ie. that they don't contain many useful properties,
that make Seq such a powerhouse? No need to fear.

seq-log-parser is an intermediate proxy in which
sqelf, squiflog and all the other things can relay
their logging entries to. Seq-log-parser will then
extract properties with the awesome power of regex
and relay them straight back to the Seq server,
even using the same API keys!

Oh, it's available as a [Docker container](https://hub.docker.com/repository/docker/smokserwis/seq-log-parser)
as well!

# Rationale

Consider such docker-compose file:

```yaml
version: '3.5'
services:
  seq:
    image: datalust/seq
    environment:
        ACCEPT_EULA: "Y"
  squiflog:
    image: datalust/squiflog
    environment:
      SEQ_ADDRESS: "http://seq:80"
    ports:
      - published: 514
        target: 514
        protocol: udp
        mode: ingress
```

In this case, say you configure your server to deposit
logs there. Example log entry you might get is:

```json
{
  "@t": "2020-05-03T20:41:39.0000000Z",
  "@mt": "kernel: [341690.053545] veth2c1b259: renamed from eth0",
  "@m": "kernel: [341690.053545] veth2c1b259: renamed from eth0",
  "@i": "5dceda5b",
  "facility": "kern",
  "hostname": "hypervisor1",
}
```

Not too useful, isn't it? Now say you use seq-log-parser in 
such a way:

```yaml
version: '3.5'
services:
  seq:
    image: datalust/seq
    environment:
        ACCEPT_EULA: "Y"
  seq-log-parser:
    image: smokserwis/seq-log-parser
    environment:
      SEQ_ADDRESS: "http://seq"
      FIELD_TO_PARSE: "@mt"
      REGEX: "(?P<source>.*): \\[(?P<uptime(\\d+)\\.(\\d+))\] (?P<interface>.*): (?P<message>.*)"
      OVERWRITE_CONTENTS: "message"
  sqelf:
    image: datalust/sqelf
    ports:
      - published: 12201
        target: 12201
        protocol: udp
        mode: ingress
    environment:
      SEQ_ADDRESS: "http://seq-log-parser"
```

And now the log entry will look like this:

```json
{
  "@t": "2020-05-03T20:41:39.0000000Z",
  "@mt": "renamed from eth0",
  "@m": "kernel: [341690.053545] veth2c1b259: renamed from eth0",
  "@i": "5dceda5b",
  "facility": "kern", 
  "Properties": {
    "source": "kernel",
    "uptime": "341690.053545", 
    "interface": "341690.053545",
    "message": "renamed from eth0"
  },
  "hostname": "hypervisor1"
}
```

Now isn't that much nicer?

# Usage

The container is configured by following envs:

| Env name           | Description                                                                             | Required? | Default |
|--------------------|------------------------------------------------------------------------------------------|-----------|---------|
| SEQ_ADDRESS        | Address of the real Seq server                                                           | True      | N/A     |
| REGEX              | Regex to use to match. It must be a valid Python regex with named groups                 | True      | N/A     |
| OVERWRITE_CONTENTS | If this env is defined, the text will be overwritten by value of this named group        | False     | False   |
| FIELD_TO_PARSE     | Name of the received field to parse against                                              | False     | @mt     |
| BIND_ADDR          | Address to bind the listening port on                                                    | False     | 0.0.0.0 |
| BIND_PORT          | Port to bind the listening port on                                                       | False     | 80      |
| LOGGING_LEVEL      | Default Python logging level to configure                                                | False     | INFO    |
| REGEX_PROPERTY     | A pair of key=value, a custom property to attach to entries                              | False     | _none_  |

Take care for your regexes to be valid Python [named group regexes](https://docs.python.org/3.8/library/re.html#index-17).
Don't forget about escaping the escape character if you're writing YAML for deployment!

What matches given named group will be added to log's Properties.

If you are using a list of regexes, and you want to add some kind of a property depending on which regex matched, 
you can specify envs called `REGEX_PROPERTY`_i_ with _i_ being the number of your regex.
You specify them in a format `key=value`.

If you want to add a custom property but are using only a single regex, just name your env `REGEX_PROPERTY`
and also specify it in form of `key=value`.

If an entry doesn't match any of the regexes, it will be sent as-is.

OVERWRITE_CONTENTS will update both the FIELD_TO_PARSE, as well as a `MessageTemplate` field, if it's present.

# Multiple regexes

If you input can be matched by multiple regexes, just specify them as environment variables REGEX1, REGEX2, REGEX3 instead of a single REGEX. 