#!/usr/bin/env python3

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


MCP_ENDPOINT = os.environ.get(
    "MCP_ENDPOINT", "https://fabriciq.svc.cloud.microsoft/v1/mcp/fabriciq"
)
MCP_VARIANT = os.environ.get(
    "MCP_VARIANT", "Fabric.Routing.FabricIQ.V1"
)
FABRIC_SCOPE = os.environ.get(
    "FABRIC_SCOPE", "https://api.fabric.microsoft.com/.default"
)
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "120"))


def log(message):
    print(f"[fabriciq-proxy] {message}", file=sys.stderr, flush=True)


class TokenProvider:
    def __init__(self):
        self._token = os.environ.get("FABRIC_TOKEN", "")
        self._expires_at = self._get_expiration(self._token)

    @staticmethod
    def _get_expiration(token):
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            return int(claims["exp"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return 0

    def get_token(self):
        if self._token and self._expires_at > time.time() + 60:
            return self._token

        try:
            result = subprocess.run(
                [
                    "az",
                    "account",
                    "get-access-token",
                    "--scope",
                    FABRIC_SCOPE,
                    "--query",
                    "accessToken",
                    "--output",
                    "tsv",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise RuntimeError(
                "Unable to acquire a Fabric token. Install Azure CLI and run 'az login'."
            ) from error

        self._token = result.stdout.strip()
        if not self._token:
            raise RuntimeError("Azure CLI returned an empty Fabric access token.")

        self._expires_at = self._get_expiration(self._token)
        return self._token


def parse_sse(body):
    messages = []
    data_lines = []

    for line in body.decode("utf-8").splitlines():
        if not line:
            if data_lines:
                messages.append(json.loads("\n".join(data_lines)))
                data_lines = []
            continue

        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        messages.append(json.loads("\n".join(data_lines)))

    return messages


def parse_response(body, content_type):
    if not body:
        return []

    if "text/event-stream" in content_type:
        return parse_sse(body)

    payload = json.loads(body.decode("utf-8"))
    return payload if isinstance(payload, list) else [payload]


class FabricIqProxy:
    def __init__(self):
        self._token_provider = TokenProvider()
        self._protocol_version = ""
        self._session_id = ""

    def _headers(self, method):
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._token_provider.get_token()}",
            "Content-Type": "application/json",
            "User-Agent": "fabriciq-mcp-stdio-proxy/1.0",
            "X-Variants": MCP_VARIANT,
        }

        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        if self._protocol_version and method != "initialize":
            headers["MCP-Protocol-Version"] = self._protocol_version

        return headers

    def _send(self, message):
        method = message.get("method", "") if isinstance(message, dict) else ""
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            MCP_ENDPOINT,
            data=body,
            headers=self._headers(method),
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                response_body = response.read()
                response_headers = response.headers
        except urllib.error.HTTPError as error:
            response_body = error.read()
            response_headers = error.headers
            if not response_body:
                raise RuntimeError(f"Fabric IQ returned HTTP {error.code}.") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Unable to reach Fabric IQ: {error.reason}") from error

        session_id = response_headers.get("Mcp-Session-Id", "")
        if session_id:
            self._session_id = session_id

        content_type = response_headers.get_content_type()
        return parse_response(response_body, content_type)

    def _transform(self, request_message, response_message):
        if request_message.get("method") == "initialize":
            result = response_message.get("result", {})
            protocol_version = result.get("protocolVersion", "")
            if protocol_version:
                self._protocol_version = protocol_version
                log(f"MCP protocol negotiated: {protocol_version}")

        if request_message.get("method") == "tools/call":
            result = response_message.get("result")
            if isinstance(result, dict) and isinstance(
                result.get("structuredContent"), dict
            ):
                for content in result.get("content", []):
                    if content.get("type") != "text":
                        continue
                    try:
                        parsed_content = json.loads(content.get("text", ""))
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(parsed_content, dict):
                        result["structuredContent"] = {
                            **parsed_content,
                            **result["structuredContent"],
                        }
                        break

        return response_message

    @staticmethod
    def _write(message):
        output = json.dumps(message, separators=(",", ":"))
        sys.stdout.write(f"{output}\n")
        sys.stdout.flush()

    def run(self):
        log("Starting stdio proxy")

        for raw_line in sys.stdin:
            if not raw_line.strip():
                continue

            request_message = None
            try:
                request_message = json.loads(raw_line)
                responses = self._send(request_message)
                for response in responses:
                    self._write(self._transform(request_message, response))
            except (json.JSONDecodeError, RuntimeError, ValueError) as error:
                log(str(error))
                if isinstance(request_message, dict) and "id" in request_message:
                    self._write(
                        {
                            "jsonrpc": "2.0",
                            "id": request_message["id"],
                            "error": {"code": -32000, "message": str(error)},
                        }
                    )


if __name__ == "__main__":
    FabricIqProxy().run()