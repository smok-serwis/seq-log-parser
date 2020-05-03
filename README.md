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
      REGEX: "(?P<source>.*): \\[(?P<time(\\d+)\\.(\\d+))\] (?P<interface>.*): (?P<message>.*)"
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
  "source": "kernel",
  "time": "341690.053545", 
  "interface": "341690.053545",
  "message": "renamed from eth0"
  "hostname": "hypervisor1",
}
```

Now isn't that much nicer?

# Usage

The container is configured by following envs:

| Env name           | Description                                                                             | Required? | Default |
|--------------------|-----------------------------------------------------------------------------------------|-----------|---------|
| SEQ_ADDRESS        | Address of the real Seq server                                                          | True      | N/A     |
| REGEX              | Regex to use to match. It must be a valid Python regex with named groups                | True      | N/A     |
| OVERWRITE_CONTENTS | If this env is defined, FIELD_TO_PARSE will be overwritten by value of this named group | False     | False   |
| FIELD_TO_PARSE     | Name of the received field to parse against                                             | False     | @mt     |
| BIND_ADDR          | Address to bind the listening port on                                                   | False     | 0.0.0.0 |
| BIND_PORT          | Port to bind the listening port on                                                      | False     | 80      |
| LOGGING_LEVEL      | Default Python logging level to configure                                               | False     | INFO    |

Take care for your regexes to be valid Python [named group regexes](https://docs.python.org/3.8/library/re.html#index-17).
Don't forget about escaping the escape character if you're writing YAML for deployment!

What matches given named group will be added to log's Properties.

# Multiple regexes

If you input can be matched by multiple regexes, just specify them as environment variables REGEX1, REGEX2, REGEX3 instead of a single REGEX. 