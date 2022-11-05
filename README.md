# HostingDE-DynDNS

This is a server that accepts GET requests with specific query parameters and interfaces with the hosting.de [DNS API](https://www.hosting.de/api/?json#updating-records-in-a-zone) in order to update DNS records with regularly changing IP addresses automatically.

## Running
Install requirements from [requirements.txt](requirements.txt) either directly for the user or in a venv.
```
pip install -r requirements.txt
```

Execute with python, optionally with a different config path.
```
python3 dyndns.py
python3 dyndns.py -c /path/to/config.toml
```

An template for the config file is given in [config.toml.template](config.toml.template).

#### Help output
```
> python3 dyndns.py -h
usage: dyndns.py [-h] [-c CONFIG]

DynDNS server providing an interface for updates via generic URL

optional arguments:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        Config file for the DynDNS server. Defaults to 'config.toml' in the current working directory.
```

## Request Format
The format of the necessary GET request is
```
GET /dyndns?domain=<domain>&ipv4=<ipv4_address>&ipv6=<ipv6_address>&ttl=<ttl>
```

The query parameters are

| parameter | required            | value                                                                              |
|-----------|---------------------|------------------------------------------------------------------------------------|
| domain    | yes                 | The domain to update.                                                              |
| ipv4      | one of [ipv4, ipv6] | The IPv4 for the A record of the domain. Must exist in the DNS zone already.       |
| ipv6      | one of [ipv4, ipv6] | The IPv6 for the AAAA record of the domain. Must exist in the DNS zone already.    |
| ttl       | no                  | The TTL of the record. If not given, a default value from the config file is used. |

## Security Considerations
* This application is not written to run with SSL and does not provide any authentication. Using a reverse proxy for transport encryption and authentication is expected.
* Records are only updated, never created. This is to prevent this server from creating arbitrary DNS records.
* Additionally, you can provide a list of allowed domains in the config. This prevents editing different records from the ones you want for DynDNS via a simple GET request.
* For the hosting.de API token, you can only select DNS-Service → Zonen → Bearbeiten. There are no additional permissions required, I recommend creating such a least privileges token.