import argparse
import logging
import typing

import cherrypy
import requests
import toml


class DNSAPIException(Exception):
    def __init__(self, error_code: int, error_data: typing.Union[str, dict]):
        self.error_code = error_code
        self.error_data = error_data

    def __str__(self):
        return f"{self.error_code} - {self.error_data}"


class HostingDEDNSAPIClient:
    def __init__(self, config):
        self.base_url = "https://secure.hosting.de/api/dns/v1/json"
        self.zone = config["zone"]
        self.token = config["token"]
        self.default_ttl = config["default_ttl"]

    def api_request(self, endpoint: str, payload: dict):
        response = requests.post(f"{self.base_url}/{endpoint}", json=payload)

        if response.status_code != 200:
            try:
                error_text = response.json()
            except ValueError:
                error_text = response.content.decode("utf-8")

            raise DNSAPIException(response.status_code, error_text)

        json_data = response.json()

        # hosting.de return 200 on failed transactions, very nice! /s
        # Probably because errors and successes can be mixed.
        # We only do one transaction at a time, so it's either an error or a success.
        if "errors" in json_data and len(json_data["errors"]):
            error_data = json_data["errors"][0]
            if error_data.get("value"):
                error_text = f"{error_data['value']} - {error_data['text']}"
            else:
                error_text = error_data['text']

            raise DNSAPIException(error_data["code"], error_text)

        return response.json()["response"]

    def get_resource_record_id(self, record_name: str, record_type: str):
        result = self.api_request(
            "recordsFind",
            {
                "authToken": self.token,
                "filter": {
                    "subFilterConnective": "AND",
                    "subFilter": [
                        {
                            "field": "RecordName",
                            "value": record_name
                        },
                        {
                            "field": "RecordType",
                            "value": record_type
                        }
                    ]
                }
            }
        )

        if len(result["data"]) == 0:
            raise DNSAPIException(404, "No matching record found.")
        elif len(result["data"]) > 1:
            raise DNSAPIException(400, "More than one matching record found, cannot continue.")
        elif not result["data"][0].get("id"):
            raise DNSAPIException(404, "Could not find ID for record in response.")

        return result["data"][0]["id"]

    def update_resource_record(self, record_name: str, record_type: str, record_data: str, record_ttl: int = None):
        record_id = self.get_resource_record_id(record_name, record_type)
        result = self.api_request(
            "recordsUpdate",
            {
                "authToken": self.token,
                "zoneName": self.zone,
                "recordsToModify": [
                    {
                        "id": record_id,
                        "name": record_name,
                        "type": record_type,
                        "content": record_data,
                        "comments": "DynDNS Record - automatically managed, do not change!",
                        # Minimum TTL for hosting.de is 60s
                        "ttl": record_ttl if record_ttl and record_ttl >= 60 else self.default_ttl
                    }
                ]
            }
        )

        filtered = list(filter(lambda entry: entry.get("id") == record_id, result.get("records", [])))
        if len(filtered) == 0:
            raise DNSAPIException(
                500,
                "Update succeeded, but failed to find updated record in success response. This should not happen."
            )
        elif len(filtered) > 1:
            raise DNSAPIException(
                500,
                "Update succeeded, but found more than one result in success response. This should not happen."
            )

        return filtered[0]


class Root:
    def __init__(self, dns_client: HostingDEDNSAPIClient, allowed_domains: typing.Union[bool, list]):
        if allowed_domains and not isinstance(allowed_domains, list):
            raise ValueError("allowed_domains has to be a list or False to allow all domains.")

        self.allowed_domains = allowed_domains
        self.dns_client = dns_client

    @cherrypy.expose
    @cherrypy.tools.params()  # Auto-cast query parameters according to type annotations
    def dyndns(self, domain: str = None, ipv4: str = None, ipv6: str = None, ttl: int = None):
        if not domain:
            cherrypy.response.status = 400
            return "DynDNS target domain missing."

        if self.allowed_domains and domain not in self.allowed_domains:
            cherrypy.response.status = 403
            return "Requested DynDNS domain ist not on the allowlist."

        results = []

        def update_wrapper(record_type, record_data):
            try:
                result = self.dns_client.update_resource_record(domain, record_type, record_data, ttl)
                logging.info(
                    f"Successfully updated {record_type} record for {result['name']}:"
                    f" {result['content']}, TTL {result['ttl']} at {result['lastChangeDate']}"
                )
                results.append(f"Successfully updated {record_type} record for {result['name']} to {result['content']}")
            except DNSAPIException as e:
                logging.error(
                    f"Failed to update {record_type} record for {domain}"
                    f" with address {record_data} and TTL {ttl if ttl else '<default>'}: {e}"
                )
                results.append(f"Failed to update {record_type} record: {e}")
                cherrypy.response.status = 400

        if not ipv4 and not ipv6:
            logging.error(f"Update request for {domain} received, but neither a v4 nor a v6 address given.")
            cherrypy.response.status = 400
            return "Neither a v4 nor a v6 address given."

        if ipv4:
            update_wrapper("A", ipv4)

        if ipv6:
            update_wrapper("AAAA", ipv6)

        cherrypy.response.headers['Content-Type'] = 'text/plain'
        return "\n".join(results)


def main():
    parser = argparse.ArgumentParser(
        description="DynDNS server providing an interface for updates via generic URL"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.toml",
        help="Config file for the DynDNS server. Defaults to 'config.toml' in the current working directory."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)8s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    with open(args.config, "r") as fh:
        config = toml.load(fh)

    cherrypy.config.update({"global": {"environment": "production"}})
    cherrypy.log.screen = True

    if "bind_socket" in config:
        cherrypy.server.socket_file = config["main"]["bind_socket"]
    else:
        cherrypy.server.socket_host = config["main"]["bind_host"]
        cherrypy.server.socket_port = config["main"]["bind_port"]

    allowed_domains = config["main"]["allowed_domains"]
    hosting_de_dns_api_client = HostingDEDNSAPIClient(config["hosting_de_dns_api"])
    root = Root(hosting_de_dns_api_client, allowed_domains)

    cherrypy.quickstart(root)


if __name__ == "__main__":
    main()
