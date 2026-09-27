# Ports

[![Tests](https://github.com/palermostest25/ports/actions/workflows/test.yml/badge.svg)](https://github.com/palermostest25/ports/actions/workflows/test.yml)
[![Container](https://github.com/palermostest25/ports/actions/workflows/container.yml/badge.svg)](https://github.com/palermostest25/ports/actions/workflows/container.yml)

A fast, polished, read-only dashboard for understanding the ports exposed by a Docker host.

Ports turns a wall of container metadata into a useful network map: see running and stopped containers, open published HTTP services, search by name/image/stack/port, spot duplicate bindings, and find the next available port at a glance. The interface is self-contained, responsive, and works well on phones.

## Highlights

- Live container and published-port inventory
- One-click service links and port copying
- Search plus running/stopped filters
- Configurable free-port ranges and reserved ports
- Host-binding collision detection
- Optional reachability indicators
- Dark and light themes
- Auto-refresh with manual refresh control
- Friendly Docker-offline state
- No JavaScript, font, or CSS CDNs
- Multi-architecture image for `linux/amd64` and `linux/arm64`
- Straightforward direct Docker socket connection

## Run it

```bash
git clone https://github.com/palermostest25/ports.git
cd ports
docker compose up -d
```

Open `http://YOUR-SERVER:1100`.

The Compose stack pulls `ghcr.io/palermostest25/ports:latest` and connects directly to the host Docker socket. The filesystem remains read-only and all Linux capabilities are dropped. Compose runs the process as root so it can open the root-owned Docker socket on standard Linux hosts.

There is no `.env` file to create or maintain. To change the dashboard port or any optional setting, edit the plainly listed values in `compose.yaml`, then run `docker compose up -d` again.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| Published port | `1100` | Change the left side of `1100:5000` in `compose.yaml` |
| `LINK_HOST` | request hostname | Override the hostname used in clickable service links |
| `PORT_RANGES` | `1000-1999,...,10000-65535` | Comma-separated ranges shown in Available |
| `RESERVED_PORTS` | empty | Single ports/ranges excluded from available results |
| `HTTPS_PORTS` | `443,8443,9443` | Published ports treated as HTTPS |
| `AVAILABLE_COUNT` | `20` | Suggested free ports shown per range (1–100) |
| `SHOW_ALL_CONTAINERS` | `true` | Include stopped containers |
| `CHECK_HOST_BIND` | `false` | Probe each published TCP port for reachability |
| `SNAPSHOT_TTL` | `2` | Backend snapshot cache in seconds (0.5–30) |

## Link hints with Docker labels

Ports normally infers HTTP or HTTPS from the port number. You can override the scheme and add a path for an individual service:

```yaml
services:
  example:
    labels:
      ports.scheme.8443: https
      ports.path.8443: /admin
```

Labels can use either the published host port or the internal container port.

## Docker socket security

Direct Docker socket access is simple and reliable, but it effectively grants the container control of the Docker host. The `:ro` bind option prevents replacing the socket file; it does not make Docker API requests read-only. Ports itself only calls Docker's read endpoints. Do not expose the dashboard directly to the public internet.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DEMO_MODE=1 flask --app app run --port 5000
```

`DEMO_MODE=1` supplies realistic sample containers and does not require Docker.

## API

- `GET /api/snapshot` — full dashboard snapshot
- `GET /api/containers` — containers and published bindings
- `GET /api/used_ports` — unique published host ports
- `GET /api/ranges` — configured ranges and available suggestions
- `GET /api/collisions` — duplicate exact bindings
- `GET /healthz` — application and Docker connectivity health

## License

[MIT](LICENSE)
