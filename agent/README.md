# vortexflow-agent

The on-host agent that keeps a Vector host's config converged to the stream
config published by VortexFlow. Pull-based: the agent reaches out to the control
plane, so it works behind NAT/firewalls (outbound-only). See the
[agent reference](../docs/guide/reference/agent.md) for details.

## What it does

Every poll interval it:

1. `GET /api/v1/agent/{instance_id}/config` with its token and last `ETag`.
2. On `304` — nothing changed; sends a heartbeat status.
3. On `200` — runs `vector validate` on the new config; **only if valid** does it
   atomically swap the file into place and reload Vector. A bad config never
   reaches a running pipeline.
4. Reports `applied_generation` + health back via `POST /agent/{instance_id}/status`.

Network/server errors trigger exponential backoff with jitter.

## Configuration (environment)

| Var | Required | Default | Notes |
|---|---|---|---|
| `VORTEXFLOW_URL` | yes | — | Control-plane base URL, e.g. `https://vf.example.com` |
| `INSTANCE_ID` | yes | — | From the registration response |
| `AGENT_TOKEN` | yes | — | From the registration response (kept `0600`) |
| `AGENT_POLL_INTERVAL` | no | `15s` | Go duration; floored at `1s` |
| `VECTOR_CONFIG_PATH` | no | `/etc/vector/vortexflow.yaml` | Managed config file |
| `VECTOR_BIN` | no | `vector` | Path to the Vector binary |
| `VECTOR_RELOAD_CMD` | no | `systemctl kill -s HUP vector` | Command to reload Vector |
| `AGENT_INSECURE_SKIP_VERIFY` | no | `false` | Disable TLS verification (dev only) |

systemd loads these from `/etc/vortexflow/agent.env` (written by the installer).

## Build

```sh
make build              # -> bin/vortexflow-agent (static, CGO disabled)
make release VERSION=x  # -> dist/ cross-compiled for linux/darwin amd64/arm64
make vet                # go vet
```

No third-party dependencies — standard library only.
