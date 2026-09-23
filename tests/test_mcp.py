"""Tests: MCP wrapper (mcp_server.py) — protocol + tools, offline only.

No test may touch the network. The harvest tools are exercised only
through paths that fail fast before any HTTP call (invalid input), and
read_manifest / get_schema are fully local by construction.
"""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "mcp_server.py"
sys.path.insert(0, str(ROOT))
import mcp_server  # noqa: E402


# ── Unit tests (in-process) ──────────────────────────────────────────────────
class TestProtocolHandlers(unittest.TestCase):
    def test_initialize_echoes_supported_version(self):
        r = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(r["result"]["serverInfo"]["name"], "xthread-agent")
        self.assertIn("tools", r["result"]["capabilities"])

    def test_initialize_falls_back_to_latest_for_unknown_version(self):
        r = mcp_server.handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(r["result"]["protocolVersion"],
                         mcp_server.LATEST_PROTOCOL_VERSION)

    def test_ping_returns_empty_result(self):
        r = mcp_server.handle_request({"jsonrpc": "2.0", "id": 3,
                                       "method": "ping"})
        self.assertEqual(r["result"], {})

    def test_tools_list_shape(self):
        r = mcp_server.handle_request({"jsonrpc": "2.0", "id": 4,
                                       "method": "tools/list"})
        tools = r["result"]["tools"]
        self.assertEqual([t["name"] for t in tools],
                         ["extract_thread", "lookup_status",
                          "read_manifest", "get_schema"])
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("description", t)

    def test_notification_returns_none(self):
        self.assertIsNone(mcp_server.handle_request({
            "jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method_is_method_not_found(self):
        r = mcp_server.handle_request({"jsonrpc": "2.0", "id": 5,
                                       "method": "resources/list"})
        self.assertEqual(r["error"]["code"], -32601)

    def test_unknown_tool_call_is_tool_error(self):
        r = mcp_server.call_tool("no_such_tool", {})
        self.assertTrue(r["isError"])

    def test_get_schema_returns_draft07_document(self):
        r = mcp_server.call_tool("get_schema", {})
        self.assertFalse(r["isError"])
        doc = json.loads(r["content"][0]["text"])
        self.assertEqual(doc["$schema"].endswith("draft-07/schema#"), True)
        self.assertEqual(doc["properties"]["schema_version"]["const"], "3.0")

    def test_bool_arg_coerces_non_bool_to_default(self):
        self.assertTrue(mcp_server._bool_arg({"x": "yes"}, "x", True))
        self.assertFalse(mcp_server._bool_arg({"x": "yes"}, "x", False))
        self.assertFalse(mcp_server._bool_arg({}, "x", False))

    def test_bool_arg_accepts_explicit_string_booleans(self):
        self.assertFalse(mcp_server._bool_arg({"x": "false"}, "x", True))
        self.assertTrue(mcp_server._bool_arg({"x": "true"}, "x", False))

    def test_env_timeout_ignores_garbage(self):
        import os
        from unittest.mock import patch
        self.assertEqual(
            mcp_server._env_timeout("XTHREAD_NO_SUCH_VAR", 900), 900)
        with patch.dict(os.environ, {"XTHREAD_TEST_TIMEOUT": "not-a-number"}):
            self.assertEqual(
                mcp_server._env_timeout("XTHREAD_TEST_TIMEOUT", 7), 7)
        with patch.dict(os.environ, {"XTHREAD_TEST_TIMEOUT": "321"}):
            self.assertEqual(
                mcp_server._env_timeout("XTHREAD_TEST_TIMEOUT", 7), 321)


# ── Subprocess integration tests (protocol framing over stdio) ──────────────
class MCPClient:
    """Minimal newline-delimited JSON-RPC client for the test server."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            bufsize=1)

    def send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout=60):
        watchdog = threading.Timer(timeout, self.proc.kill)
        watchdog.start()
        try:
            line = self.proc.stdout.readline()
        finally:
            watchdog.cancel()
        if not line:
            raise AssertionError("server closed stdout without a response")
        return json.loads(line)

    def request(self, obj, timeout=60):
        self.send(obj)
        return self.recv(timeout)

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TestMCPOverStdio(unittest.TestCase):
    def test_initialize_handshake(self):
        with MCPClient() as c:
            r = c.request({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18"}})
            self.assertEqual(r["jsonrpc"], "2.0")
            self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")

    def test_notification_produces_no_output(self):
        with MCPClient() as c:
            c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            r = c.request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            self.assertEqual(r["id"], 2)  # first response is the ping's own

    def test_parse_error_yields_error_response(self):
        with MCPClient() as c:
            c.proc.stdin.write("this is not json\n")
            c.proc.stdin.flush()
            r = c.recv()
            self.assertEqual(r["error"]["code"], -32700)

    def test_extract_thread_invalid_input_is_tool_error(self):
        # "not a url" fails normalize_input locally — no network is touched.
        with MCPClient() as c:
            r = c.request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "extract_thread",
                                      "arguments": {"url": "not a url"}}})
            self.assertTrue(r["result"]["isError"])
            payload = json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(payload["status"], "invalid_input")
            self.assertEqual(payload["error"]["code"], "E_INVALID_INPUT")

    def test_extract_thread_missing_url_is_tool_error(self):
        with MCPClient() as c:
            r = c.request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "extract_thread",
                                      "arguments": {}}})
            self.assertTrue(r["result"]["isError"])
            self.assertIn("url", r["result"]["content"][0]["text"])

    def test_read_manifest_returns_fixture_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "thread_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": "3.0", "status": "ok", "posts": []}),
                encoding="utf-8")
            with MCPClient() as c:
                r = c.request({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                               "params": {"name": "read_manifest",
                                          "arguments": {"path": str(manifest)}}})
                self.assertFalse(r["result"]["isError"])
                env = json.loads(r["result"]["content"][0]["text"])
                self.assertEqual(env["schema_version"], "3.0")

    def test_read_manifest_refuses_other_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "secrets.json"
            other.write_text("{}", encoding="utf-8")
            with MCPClient() as c:
                r = c.request({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                               "params": {"name": "read_manifest",
                                          "arguments": {"path": str(other)}}})
                self.assertTrue(r["result"]["isError"])
                self.assertIn("refusing", r["result"]["content"][0]["text"])

    def test_read_manifest_missing_file_is_tool_error(self):
        with MCPClient() as c:
            r = c.request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                           "params": {"name": "read_manifest",
                                      "arguments": {
                                          "path": "/nonexistent/thread_manifest.json"}}})
            self.assertTrue(r["result"]["isError"])
            self.assertIn("not found", r["result"]["content"][0]["text"])

    def test_get_schema_over_stdio(self):
        with MCPClient() as c:
            r = c.request({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                           "params": {"name": "get_schema", "arguments": {}}})
            self.assertFalse(r["result"]["isError"])
            doc = json.loads(r["result"]["content"][0]["text"])
            self.assertEqual(doc["title"].startswith("xthread-agent"), True)

    def test_sequential_requests_keep_framing(self):
        with MCPClient() as c:
            for i in range(5):
                r = c.request({"jsonrpc": "2.0", "id": i, "method": "ping"})
                self.assertEqual(r["id"], i)


if __name__ == "__main__":
    unittest.main()
