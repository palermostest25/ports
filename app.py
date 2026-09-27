#!/usr/bin/env python3
"""Ports — a read-only Docker port inventory and launchpad."""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import docker
from docker.errors import DockerException
from flask import Flask, jsonify, render_template, request


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def clamp_port(value: int) -> int:
    return max(1, min(65535, value))


@dataclass(frozen=True)
class PortRange:
    start: int
    end: int
    label: str


def parse_ranges(spec: str) -> List[PortRange]:
    output: List[PortRange] = []
    seen: Set[Tuple[int, int]] = set()
    for raw in spec.replace(" ", "").split(","):
        if not raw:
            continue
        try:
            if "-" in raw:
                first, last = raw.split("-", 1)
                start, end = clamp_port(int(first)), clamp_port(int(last))
            else:
                start = end = clamp_port(int(raw))
        except ValueError:
            continue
        if start > end:
            start, end = end, start
        if (start, end) in seen:
            continue
        seen.add((start, end))
        label = str(start) if start == end else (f"{start}+" if end == 65535 else f"{start}–{end}")
        output.append(PortRange(start, end, label))
    return output or [PortRange(1000, 65535, "1000+")]


def parse_port_set(spec: str) -> Set[int]:
    ports: Set[int] = set()
    for raw in spec.replace(" ", "").split(","):
        if not raw:
            continue
        try:
            if "-" in raw:
                first, last = raw.split("-", 1)
                start, end = clamp_port(int(first)), clamp_port(int(last))
                if start > end:
                    start, end = end, start
                ports.update(range(start, end + 1))
            else:
                ports.add(clamp_port(int(raw)))
        except ValueError:
            continue
    return ports


PORT_RANGES = parse_ranges(env("PORT_RANGES", "1000-1999,2000-2999,3000-3999,4000-4999,5000-9999,10000-65535"))
RESERVED_PORTS = parse_port_set(env("RESERVED_PORTS"))
HTTPS_PORTS = parse_port_set(env("HTTPS_PORTS", "443,8443,9443"))
AVAILABLE_COUNT = max(1, min(100, int(env("AVAILABLE_COUNT", "20"))))
SHOW_ALL_CONTAINERS = env_bool("SHOW_ALL_CONTAINERS", True)
CHECK_HOST_BIND = env_bool("CHECK_HOST_BIND", False)
DEMO_MODE = env_bool("DEMO_MODE", False)
SNAPSHOT_TTL = max(0.5, min(30.0, float(env("SNAPSHOT_TTL", "2"))))

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

_client = None
_client_lock = threading.Lock()
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"at": 0.0, "key": None, "value": None}


def docker_client():
    global _client
    with _client_lock:
        if _client is None:
            _client = docker.from_env(timeout=3)
        return _client


def friendly_docker_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "permission denied" in message:
        return "Docker is reachable, but this container cannot read the socket."
    if "connection refused" in message or "no such file" in message or "error while fetching" in message:
        return "Docker is unavailable. Check the socket proxy or Docker socket configuration."
    return "Docker is unavailable. Check the connection and try again."


def docker_status() -> Tuple[bool, Optional[str], Optional[str]]:
    if DEMO_MODE:
        return True, "demo", None
    try:
        client = docker_client()
        client.ping()
        return True, client.version().get("Version"), None
    except Exception as exc:
        return False, None, friendly_docker_error(exc)


def request_host() -> str:
    override = env("LINK_HOST")
    if override:
        return override.strip()
    raw = request.host.rsplit(":", 1)[0] if request.host else "localhost"
    return raw.strip("[]") or "localhost"


def format_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def probe_port(host: str, port: int) -> Optional[bool]:
    if not CHECK_HOST_BIND:
        return None
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def compose_stack(labels: Dict[str, str]) -> str:
    return labels.get("com.docker.compose.project") or labels.get("com.docker.stack.namespace") or ""


def image_name(container) -> str:
    configured = (container.attrs.get("Config", {}).get("Image") or "").split("@", 1)[0]
    if configured:
        return configured
    tags = getattr(container.image, "tags", []) or []
    return tags[0] if tags else container.image.short_id


def health_state(attrs: Dict[str, Any]) -> Optional[str]:
    return (attrs.get("State", {}).get("Health") or {}).get("Status")


def inferred_scheme(host_port: int, container_port: int, labels: Dict[str, str]) -> str:
    explicit = labels.get(f"ports.scheme.{host_port}") or labels.get(f"ports.scheme.{container_port}")
    if explicit in {"http", "https"}:
        return explicit
    return "https" if host_port in HTTPS_PORTS or container_port in {443, 8443, 9443} else "http"


def inferred_path(host_port: int, container_port: int, labels: Dict[str, str]) -> str:
    path = labels.get(f"ports.path.{host_port}") or labels.get(f"ports.path.{container_port}") or "/"
    return path if path.startswith("/") else f"/{path}"


def published_ports(container, link_host: str) -> List[Dict[str, Any]]:
    attrs = container.attrs
    labels = attrs.get("Config", {}).get("Labels") or {}
    mappings = attrs.get("NetworkSettings", {}).get("Ports") or {}
    result: List[Dict[str, Any]] = []
    for container_binding, bindings in mappings.items():
        if not bindings:
            continue
        container_port_text, _, protocol = container_binding.partition("/")
        try:
            container_port = int(container_port_text)
        except ValueError:
            continue
        for binding in bindings:
            try:
                host_port = int(binding.get("HostPort", ""))
            except (TypeError, ValueError):
                continue
            host_ip = binding.get("HostIp") or "0.0.0.0"
            destination = link_host if host_ip in {"0.0.0.0", "::", ""} else host_ip
            scheme = inferred_scheme(host_port, container_port, labels)
            path = inferred_path(host_port, container_port, labels)
            result.append({
                "host_ip": host_ip,
                "host_port": host_port,
                "container_port": container_port,
                "protocol": protocol or "tcp",
                "scheme": scheme,
                "path": path,
                "href": f"{scheme}://{format_host(destination)}:{host_port}{path}",
                "reachable": probe_port(destination, host_port),
            })
    return sorted(result, key=lambda item: (item["host_port"], item["container_port"]))


def demo_containers(link_host: str) -> List[Dict[str, Any]]:
    samples = [
        ("paperless", "ghcr.io/paperless-ngx/paperless-ngx:latest", "documents", "running", "healthy", [(8010, 8000, "http")]),
        ("home-assistant", "ghcr.io/home-assistant/home-assistant:stable", "home", "running", None, [(8123, 8123, "http")]),
        ("vaultwarden", "vaultwarden/server:latest", "security", "running", "healthy", [(9443, 80, "https")]),
        ("postgres", "postgres:17-alpine", "documents", "running", "healthy", []),
        ("immich-machine-learning", "ghcr.io/immich-app/immich-machine-learning:release", "photos", "exited", None, []),
    ]
    output = []
    for index, (name, image, stack, state, health, ports) in enumerate(samples):
        output.append({
            "id": f"d3m0{index:02d}", "name": name, "image": image, "stack": stack,
            "state": state, "health": health, "created": "2026-09-27T00:00:00Z",
            "ports": [{
                "host_ip": "0.0.0.0", "host_port": hp, "container_port": cp,
                "protocol": "tcp", "scheme": scheme, "path": "/",
                "href": f"{scheme}://{format_host(link_host)}:{hp}/", "reachable": True,
            } for hp, cp, scheme in ports],
        })
    return output


def collect_containers(link_host: str) -> List[Dict[str, Any]]:
    if DEMO_MODE:
        return demo_containers(link_host)
    containers = docker_client().containers.list(all=SHOW_ALL_CONTAINERS)
    output = []
    for container in containers:
        attrs = container.attrs
        labels = attrs.get("Config", {}).get("Labels") or {}
        output.append({
            "id": container.short_id,
            "name": container.name,
            "image": image_name(container),
            "stack": compose_stack(labels),
            "state": attrs.get("State", {}).get("Status", "unknown"),
            "health": health_state(attrs),
            "created": attrs.get("Created"),
            "ports": published_ports(container, link_host),
        })
    return sorted(output, key=lambda item: (item["state"] != "running", item["name"].lower()))


def port_analysis(containers: Iterable[Dict[str, Any]]) -> Tuple[Set[int], List[Dict[str, Any]]]:
    used: Set[int] = set()
    bindings: Dict[str, List[str]] = {}
    for container in containers:
        for port in container["ports"]:
            used.add(port["host_port"])
            key = f"{port['host_ip']}:{port['host_port']}"
            bindings.setdefault(key, []).append(container["name"])
    collisions = [{"binding": key, "containers": names} for key, names in sorted(bindings.items()) if len(names) > 1]
    return used, collisions


def ranges_payload(used: Set[int]) -> List[Dict[str, Any]]:
    payload = []
    for item in PORT_RANGES:
        used_in_range = sorted(port for port in used if item.start <= port <= item.end)
        available: List[int] = []
        available_total = 0
        reserved_total = 0
        for port in range(item.start, item.end + 1):
            if port in used:
                continue
            if port in RESERVED_PORTS:
                reserved_total += 1
                continue
            available_total += 1
            if len(available) < AVAILABLE_COUNT:
                available.append(port)
        payload.append({
            "label": item.label, "start": item.start, "end": item.end,
            "size": item.end - item.start + 1, "used": used_in_range,
            "used_count": len(used_in_range), "reserved_count": reserved_total,
            "available": available, "available_count": available_total,
        })
    return payload


def public_settings() -> Dict[str, Any]:
    return {
        "show_all_containers": SHOW_ALL_CONTAINERS,
        "check_host_bind": CHECK_HOST_BIND,
        "available_count": AVAILABLE_COUNT,
        "demo_mode": DEMO_MODE,
    }


def empty_snapshot(error: str, version: Optional[str] = None) -> Dict[str, Any]:
    return {
        "connected": False, "docker_version": version, "error": error, "containers": [],
        "ranges": ranges_payload(set()), "collisions": [],
        "metrics": {"total": 0, "running": 0, "stopped": 0, "published": 0, "unique_ports": 0},
        "generated_at": time.time(), "settings": public_settings(),
    }


def build_snapshot(link_host: str) -> Dict[str, Any]:
    connected, version, error = docker_status()
    if not connected:
        return empty_snapshot(error or "Docker is unavailable.", version)
    try:
        containers = collect_containers(link_host)
        used, collisions = port_analysis(containers)
        running = sum(1 for container in containers if container["state"] == "running")
        return {
            "connected": True, "docker_version": version, "error": None,
            "containers": containers, "ranges": ranges_payload(used), "collisions": collisions,
            "metrics": {
                "total": len(containers), "running": running, "stopped": len(containers) - running,
                "published": sum(1 for container in containers if container["ports"]), "unique_ports": len(used),
            },
            "generated_at": time.time(), "settings": public_settings(),
        }
    except (DockerException, OSError) as exc:
        return empty_snapshot(friendly_docker_error(exc), version)


def snapshot(force: bool = False) -> Dict[str, Any]:
    key = request_host()
    now = time.monotonic()
    with _cache_lock:
        if not force and _cache["value"] is not None and _cache["key"] == key and now - _cache["at"] < SNAPSHOT_TTL:
            return _cache["value"]
    value = build_snapshot(key)
    with _cache_lock:
        _cache.update({"at": now, "key": key, "value": value})
    return value


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    connected, version, error = docker_status()
    return jsonify({"service": "ok", "docker": connected, "docker_version": version, "error": error}), 200 if connected else 503


@app.get("/api/snapshot")
def api_snapshot():
    return jsonify(snapshot(force=request.args.get("refresh") == "1"))


@app.get("/api/containers")
def api_containers():
    data = snapshot()
    return jsonify(data["containers"]) if data["connected"] else (jsonify({"error": data["error"]}), 503)


@app.get("/api/used_ports")
def api_used_ports():
    data = snapshot()
    ports = sorted({port["host_port"] for item in data["containers"] for port in item["ports"]})
    return jsonify(ports) if data["connected"] else (jsonify({"error": data["error"]}), 503)


@app.get("/api/ranges")
def api_ranges():
    data = snapshot()
    return jsonify(data["ranges"]) if data["connected"] else (jsonify({"error": data["error"]}), 503)


@app.get("/api/collisions")
def api_collisions():
    data = snapshot()
    return jsonify(data["collisions"]) if data["connected"] else (jsonify({"error": data["error"]}), 503)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(env("PORT", "5000")), threaded=True)
