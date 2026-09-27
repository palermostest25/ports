import os
import unittest
from types import SimpleNamespace

os.environ["DEMO_MODE"] = "1"

import app  # noqa: E402


class PortsAppTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_pages_and_legacy_endpoints_are_healthy(self):
        for path in (
            "/",
            "/healthz",
            "/api/snapshot",
            "/api/containers",
            "/api/used_ports",
            "/api/ranges",
            "/api/collisions",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_demo_snapshot_has_expected_summary(self):
        data = self.client.get("/api/snapshot?refresh=1").get_json()
        self.assertTrue(data["connected"])
        self.assertEqual(data["docker_version"], "demo")
        self.assertEqual(
            data["metrics"],
            {"total": 5, "running": 4, "stopped": 1, "published": 3, "unique_ports": 3},
        )
        self.assertEqual(data["collisions"], [])

    def test_service_links_use_the_request_host(self):
        data = self.client.get("/api/snapshot?refresh=1", headers={"Host": "dockerbox.local:5000"}).get_json()
        first_link = data["containers"][0]["ports"][0]["href"]
        self.assertEqual(first_link, "http://dockerbox.local:8010/")

    def test_security_headers_are_set(self):
        response = self.client.get("/api/snapshot")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_ipv4_and_ipv6_wildcard_bindings_are_not_duplicated(self):
        container = SimpleNamespace(attrs={
            "Config": {"Labels": {}},
            "NetworkSettings": {"Ports": {
                "3000/tcp": [
                    {"HostIp": "0.0.0.0", "HostPort": "9002"},
                    {"HostIp": "::", "HostPort": "9002"},
                ],
            }},
        })
        ports = app.published_ports(container, "dockerbox.local")
        self.assertEqual(len(ports), 1)
        self.assertEqual(ports[0]["host_ip"], "0.0.0.0")
        self.assertEqual(ports[0]["href"], "http://dockerbox.local:9002/")


if __name__ == "__main__":
    unittest.main()
