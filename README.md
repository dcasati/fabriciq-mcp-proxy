# FabricIQ MCP Proxy

A small, dependency-free Python proxy that connects stdio MCP clients to the
FabricIQ HTTP MCP endpoint.

## What it does

- Reads MCP JSON-RPC messages from stdin and forwards them to FabricIQ over HTTP.
- Authenticates with `FABRIC_TOKEN` or an Azure CLI access token.
- Tracks the negotiated MCP protocol version and remote session ID.
- Supports JSON and server-sent event responses.
- Keeps human-readable `content` while augmenting `structuredContent` with JSON
  result fields, so MCP clients receive query data and upstream metadata together.

## Requirements

- Python 3.9 or newer
- Azure CLI
- Access to FabricIQ

Authenticate before starting the proxy:

```bash
az login
```

## VS Code setup

Add the server to your user or workspace `mcp.json`:

```json
{
  "servers": {
    "FabricIQ-Proxy": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absolute/path/to/fabriciq-mcp-proxy.py"]
    }
  }
}
```

Start `FabricIQ-Proxy` from VS Code's MCP server menu. Its FabricIQ tools will
then be available directly in chat.

## Configuration

| Variable | Default |
| --- | --- |
| `MCP_ENDPOINT` | `https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq` |
| `MCP_VARIANT` | `Fabric.Routing.FabricIQ.V1` |
| `FABRIC_SCOPE` | `https://api.fabric.microsoft.com/.default` |
| `FABRIC_TOKEN` | Azure CLI token when unset |
| `HTTP_TIMEOUT` | `120` seconds |

The proxy writes protocol messages to stdout and diagnostics to stderr.