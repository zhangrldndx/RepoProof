"""Replay server for open-API workspaces under sealed verification.

A tool that reads public hosts at runtime cannot be verified by letting it
reach those hosts: the answers would change under the verifier's feet and the
sealed run would need the network it exists to deny.  Instead the fixture
carries the recorded responses and this server replays them on 127.0.0.1.
The tool is pointed at it through one environment variable; the sandbox opens
exactly that port and nothing else.

The server is also the observation point.  Every request is ledgered, an
unrecorded request answers 404 and is never a silent success, and a canary
token that the sealed environment plants is flagged the moment it appears in
a request — a tool that forwards credentials to the hosts it talks to is
caught without any credential ever existing.

Only the standard library is used, so the same module can be copied next to
frozen acceptance tests and run inside the Harness test toolchain.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import shutil
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

# The one environment variable a tool must honour: JSON mapping each allowed
# host to the base URL that stands in for it.
BASE_URLS_ENV = "REPOPROOF_OPEN_API_BASE_URLS"
# A random value planted only during sealed runs; its appearance in any
# request or output is a credential leak by construction.
CANARY_ENV = "REPOPROOF_CANARY_TOKEN"
RESPONSES_DIRNAME = "__responses__"
MANIFEST_FILENAME = "manifest.json"
UNRECORDED = "UNRECORDED_REQUEST"

_MAX_BODY = 32 * 1024 * 1024


def canonical_query(query: str) -> str:
    """Parameter order is not content: ``b=2&a=1`` and ``a=1&b=2`` are one request."""

    pairs = sorted(parse_qsl(query or "", keep_blank_values=True))
    return urlencode(pairs)


def request_key(method: str, host: str, path: str, query: str) -> tuple[str, str, str, str]:
    return (
        str(method or "GET").upper(),
        str(host or "").strip().lower(),
        "/" + str(path or "").strip().lstrip("/"),
        canonical_query(query),
    )


def write_manifest(responses_dir: Path, rows: list[dict]) -> Path:
    """Write the recorded-response manifest a fixture builder produces."""

    responses_dir = Path(responses_dir)
    responses_dir.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": 1, "responses": list(rows)}
    path = responses_dir / MANIFEST_FILENAME
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def unused_recording_keys(manifest_rows, ledger_rows) -> list[str]:
    """Recorded keys the producer never asked for, canonicalised the way the stub matches.

    Requests and recordings agree in both directions: an unrecorded request is
    the producer's problem (UNRECORDED), and a recording nobody requests is a
    scenario inconsistency the judge would otherwise treat as truth
    (incident-recording-nobody-requested-becomes-the-judges-truth-*).
    """

    def _key(row: dict) -> tuple[str, str, str, str] | None:
        if not isinstance(row, dict):
            return None
        host = str(row.get("host") or "").strip().lower()
        if not host:
            return None
        return request_key(row.get("method", "GET"), host, row.get("path", ""), row.get("query", ""))

    requested = {key for key in (_key(row) for row in ledger_rows or ()) if key is not None}
    unused: list[str] = []
    for row in manifest_rows or ():
        key = _key(row)
        if key is None or key in requested:
            continue
        text = f"{key[0]} {key[1]}{key[2]}" + (f"?{key[3]}" if key[3] else "")
        if text not in unused:
            unused.append(text)
    return sorted(unused)


def load_manifest(responses_dir: Path) -> dict[tuple[str, str, str, str], dict]:
    """Index the manifest by request key; a body file outside the directory is refused."""

    responses_dir = Path(responses_dir)
    document = json.loads((responses_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    rows = document.get("responses") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError("responses manifest must carry a list under 'responses'")
    index: dict[tuple[str, str, str, str], dict] = {}
    root = responses_dir.resolve()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every recorded response is an object")
        body_name = str(row.get("body") or "")
        body_path = (responses_dir / body_name).resolve()
        if not body_name or body_path.parent != root or not body_path.is_file():
            # Say the rule, not just the verdict: a body under a subdirectory
            # *is* inside the directory, and four builder rewrites kept it there
            # (incident-recorded-body-rule-not-stated-*).
            bare = Path(body_name).name if body_name else "<missing>"
            raise ValueError(
                f"recorded body must be a bare file name directly inside {RESPONSES_DIRNAME} "
                f"(no subdirectory, no '/' or '..'), and that file must exist: got {body_name!r}"
                + (f"; write the file as {RESPONSES_DIRNAME}/{bare} and name it {bare!r}" if bare != body_name else "")
            )
        key = request_key(row.get("method", "GET"), row.get("host", ""), row.get("path", ""), row.get("query", ""))
        index[key] = {
            "status": int(row.get("status") or 200),
            "headers": {str(k): str(v) for k, v in (row.get("headers") or {}).items()},
            "body_path": body_path,
        }
    return index


class ReplayServer:
    """Serve ``http://127.0.0.1:PORT/<host>/<path>?<query>`` from recorded responses."""

    def __init__(self, responses_dir: Path, *, canary: str | None = None) -> None:
        self.responses_dir = Path(responses_dir)
        self.canary = canary or None
        self.ledger: list[dict] = []
        self._index: dict[tuple[str, str, str, str], dict] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------
    def start(self) -> ReplayServer:
        self._index = load_manifest(self.responses_dir)
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # silence stderr
                pass

            def do_GET(self) -> None:  # noqa: N802 - http.server API
                outer._serve(self, "GET")

            def do_HEAD(self) -> None:  # noqa: N802
                outer._serve(self, "HEAD")

            def do_POST(self) -> None:  # noqa: N802 - writes are never recorded
                outer._serve(self, "POST")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> ReplayServer:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    # -- facts ------------------------------------------------------------
    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("replay server is not running")
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def unrecorded(self) -> list[dict]:
        return [row for row in self.ledger if not row["matched"]]

    def canary_leaks(self) -> list[dict]:
        return [row for row in self.ledger if row["canary_seen"]]

    # -- serving ----------------------------------------------------------
    def _serve(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        parts = urlsplit(handler.path)
        segments = parts.path.lstrip("/").split("/", 1)
        host = segments[0] if segments else ""
        path = "/" + (segments[1] if len(segments) > 1 else "")
        key = request_key(method, host, path, parts.query)
        header_blob = " ".join(f"{k}: {v}" for k, v in handler.headers.items())
        canary = self.canary
        canary_seen = canary is not None and (
            canary in header_blob or canary in (parts.query or "")
        )
        record = self._index.get(key) if method in {"GET", "HEAD"} else None
        row = {
            "method": key[0],
            "host": key[1],
            "path": key[2],
            "query": key[3],
            "matched": record is not None,
            "canary_seen": canary_seen,
        }
        with self._lock:
            self.ledger.append(row)
        if record is None:
            payload = json.dumps(
                {"error": UNRECORDED, "method": key[0], "host": key[1], "path": key[2], "query": key[3]}
            ).encode("utf-8")
            handler.send_response(404)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            if method != "HEAD":
                handler.wfile.write(payload)
            return
        body = record["body_path"].read_bytes()[:_MAX_BODY]
        handler.send_response(record["status"])
        for name, value in record["headers"].items():
            if name.lower() in {"content-length", "transfer-encoding", "connection"}:
                continue
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        if method != "HEAD":
            handler.wfile.write(body)


def base_urls_env(server: ReplayServer, hosts: tuple[str, ...] | list[str]) -> dict[str, str]:
    """The environment a sealed tool receives: every allowed host → the replay base."""

    mapping = {
        str(host).strip().lower(): f"{server.base_url}/{str(host).strip().lower()}"
        for host in hosts
    }
    return {BASE_URLS_ENV: json.dumps(mapping, sort_keys=True, separators=(",", ":"))}


class ReplaySession:
    """One managed run of an open-API tool: hidden recordings, stubbed hosts, a canary, a verdict."""

    def __init__(
        self,
        *,
        tool_input: Path,
        env: dict[str, str],
        server: ReplayServer | None,
        canary: str | None,
        view: Path | None,
    ) -> None:
        self.tool_input = tool_input
        self.env = env
        self.server = server
        self.canary = canary
        self._view = view

    def verdict(self, artifact_dir: Path | None) -> list[str]:
        """Public codes for everything the tool did outside the sealed session."""

        if self.server is None:
            return []
        codes: list[str] = []
        if self.server.unrecorded():
            codes.append("WORKSPACE_REFERENCE_UNRECORDED_REQUEST")
        leaked = bool(self.server.canary_leaks())
        if not leaked and self.canary and artifact_dir is not None and Path(artifact_dir).is_dir():
            needle = self.canary.encode("utf-8")
            for path in sorted(Path(artifact_dir).rglob("*")):
                if path.is_file() and not path.is_symlink() and needle in path.read_bytes():
                    leaked = True
                    break
        if leaked:
            codes.append("WORKSPACE_REFERENCE_CREDENTIAL_LEAK")
        if not self.server.ledger:
            codes.append("WORKSPACE_REFERENCE_NO_API_CALLS")
        return codes

    def details(self) -> list[str]:
        if self.server is None:
            return []
        return [
            f"{row.get('method', 'GET')} {row.get('host', '')}{row.get('path', '')}"
            + (f"?{row['query']}" if row.get("query") else "")
            for row in self.server.unrecorded()[:8]
        ]


@contextlib.contextmanager
def replay_session(
    input_path: Path,
    *,
    hosts: tuple[str, ...] | list[str],
    stage_dir: Path,
    canary: str | None = None,
) -> Iterator[ReplaySession]:
    """Run a tool the sealed way when its input carries recordings; pass through otherwise.

    The same session serves the pre-freeze self-check, the frozen acceptance
    tests and the post-release fresh audit, so the rules cannot drift between
    them.  An input without ``__responses__`` is an offline tool's input and is
    handed over untouched.
    """

    input_path = Path(input_path)
    responses = input_path / RESPONSES_DIRNAME
    if not responses.is_dir():
        yield ReplaySession(tool_input=input_path, env={}, server=None, canary=None, view=None)
        return
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    view = stage_dir / "tool-input"
    shutil.copytree(input_path, view, ignore=shutil.ignore_patterns(RESPONSES_DIRNAME))
    token = canary or secrets.token_hex(16)
    recorded_hosts = {key[1] for key in load_manifest(responses)}
    allowed = sorted({*(str(h).strip().lower() for h in hosts), *recorded_hosts})
    server = ReplayServer(responses, canary=token)
    server.start()
    try:
        env = {**base_urls_env(server, allowed), CANARY_ENV: token}
        yield ReplaySession(tool_input=view, env=env, server=server, canary=token, view=view)
    finally:
        server.stop()
        shutil.rmtree(view, ignore_errors=True)


def json_shape(value: object, depth: int = 2) -> object:
    """A bounded description of a JSON value: keys and value types, array lengths.

    Shared by the live probe (what the real host answered with) and the judge's
    repair context (what the recordings hold).
    """

    if isinstance(value, dict):
        if depth <= 0:
            return "object"
        return {str(key): json_shape(item, depth - 1) for key, item in list(value.items())[:40]}
    if isinstance(value, list):
        head = value[0] if value else None
        if isinstance(head, dict) and depth > 0:
            inner = ", ".join(f"{key}: {json_shape(item, 0)}" for key, item in list(head.items())[:20])
            return f"array[{len(value)}] of {{{inner}}}"
        return f"array[{len(value)}]"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"
