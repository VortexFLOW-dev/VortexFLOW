# MCP server

VortexFlow ships an [MCP](https://modelcontextprotocol.io/) server so AI agents
and automation can inspect a deployment through a typed tool interface instead of
scraping the REST API. **v1 is read-only.**

## Enabling it

Off by default. Set `VORTEXFLOW_MCP_ENABLED=true` and restart the backend. The
server is then served at **`/mcp`** (streamable HTTP) on the same origin as the
API — e.g. `https://vortexflow.example.com/mcp`.

## Authenticating

Every tool call requires a **personal access token** (Settings → Access Tokens),
sent as a bearer token:

```
Authorization: Bearer vf_pat_<id>_<secret>
```

The token acts as its owning user and inherits that user's role live, so RBAC
applies. Revoked, expired, or inactive-user tokens are rejected uniformly (no
"unknown id vs. bad secret" oracle). Connecting a client (example — Claude Code):

```
claude mcp add --transport http vortexflow https://vortexflow.example.com/mcp \
  --header "Authorization: Bearer vf_pat_..."
```

## Tools (v1 — read-only)

| Tool | Returns |
|---|---|
| `validate_vrl(source, event?)` | Vector compiler diagnostics for a VRL program against a sample event |
| `list_fleets()` | All fleets + generation, instance/component counts |
| `get_fleet(fleet_id)` | One fleet with its component/route/stage summary |
| `list_components(fleet_id)` | A fleet's sources & sinks (type + name) |
| `list_routes(fleet_id)` | A fleet's routes and branch names |
| `list_transforms()` | The saved VRL transform library |
| `get_catalog(kind?)` | Accepted Vector source/sink types |
| `render_fleet_config(fleet_id)` | The Vector YAML the fleet would deploy (**secrets masked**) |
| `list_instances(fleet_id?)` | Instances with role, agent status, and config-generation lag |

Each tool calls the same service functions as the REST API (`vrl_runner`,
`config_render`), so there is a single implementation and nothing to drift.

## Design notes

- **Read-only by design.** Write/deploy tools (create components, deploy a fleet)
  are a deliberate follow-up: they will be RBAC-gated (Editor+ for writes, Admin
  for deploy) and sit behind a separate opt-in (`VORTEXFLOW_MCP_WRITES`) so a
  leaked read token can't mutate a fleet.
- **Stateless transport.** The server uses stateless streamable HTTP, so it works
  behind a load balancer across multiple backend replicas without session
  affinity.
- **Embedding.** The MCP app is mounted into the FastAPI app; its session manager
  runs in the FastAPI lifespan (`app.main`). `validate_vrl` needs the bundled
  Vector binary (present in the container image); without it, the tool returns a
  clear "validation unavailable" result rather than failing.

See `backend/app/mcp/` for the implementation.
