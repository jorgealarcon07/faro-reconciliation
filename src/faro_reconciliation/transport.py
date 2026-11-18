"""Local fixture producer and resumable file/HTTP consumers."""

import json
import threading
import time
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from . import store
from .contracts import ReconciliationError, encode

MAX_PAGE = 2000


def page_inputs(offset, size, total):
    if not 0 <= offset <= total or not 1 <= size <= MAX_PAGE:
        raise ReconciliationError("Invalid page cursor or page size")


class FileFeed:
    def __init__(self, feed_id, events):
        self.feed_id = feed_id
        self.events = events

    def page(self, offset, limit):
        page_inputs(offset, limit, len(self.events))
        return self.events[offset : offset + limit]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpFeed:
    def __init__(self, url, feed_id):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or not parsed.port
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ReconciliationError("HTTP feed requires a bare loopback URL with a port")
        self.url = url.rstrip("/")
        self.feed_id = feed_id
        self.retries = Counter()
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def page(self, offset, limit):
        path = "/events?" + urlencode({"cursor": offset, "limit": limit})
        for attempt in range(4):
            delay = None
            try:
                with self.opener.open(self.url + path, timeout=4) as response:
                    raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise ReconciliationError("HTTP page exceeds 16 MiB")
                data = json.loads(raw)
                rows = data["events"]
                if (
                    data["feed_id"] != self.feed_id
                    or data["cursor"] != offset
                    or not isinstance(rows, list)
                    or len(rows) > limit
                    or data["next_cursor"] != offset + len(rows)
                ):
                    raise ReconciliationError("HTTP stream or page does not match requested cursor")
                return rows
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504):
                    raise ReconciliationError(f"Non-retryable HTTP {exc.code}") from None
                status = str(exc.code)
                header = exc.headers.get("Retry-After", "")
                delay = min(2, int(header)) if header.isascii() and header.isdecimal() else None
                exc.close()
            except (URLError, TimeoutError):
                status = "connection"
            if attempt == 3:
                break
            self.retries[status] += 1
            time.sleep(max(0.05 * 2**attempt, delay or 0))
        raise ReconciliationError("HTTP retry budget exhausted")


def server_for(feed, port, faults=False):
    arrivals = Counter()
    mutex = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                parsed = urlsplit(self.path)
                if parsed.path != "/events":
                    self.send_error(404)
                    return
                args = parse_qs(parsed.query, max_num_fields=2, strict_parsing=True)
                offset, limit = int(args["cursor"][0]), int(args["limit"][0])
                rows = feed.page(offset, limit)
            except (KeyError, ValueError, ReconciliationError):
                self.send_error(400)
                return
            with mutex:
                arrivals[offset] += 1
                attempt = arrivals[offset]
            if faults and offset == 0 and attempt in (1, 2):
                self.send_response(429 if attempt == 1 else 500)
                self.send_header("Retry-After", "0")
                self.end_headers()
                return
            body = encode(
                {
                    "feed_id": feed.feed_id,
                    "cursor": offset,
                    "events": rows,
                    "next_cursor": offset + len(rows),
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


@contextmanager
def simulator(feed, *, faults=False):
    server = server_for(feed, 0, faults)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def ingest(conn, case_id, feed, *, page_size=500, until=None, failpoint=None):
    if not 1 <= page_size <= MAX_PAGE or (until is not None and until < 0):
        raise ReconciliationError("Invalid page size or end position")
    first = offset = store.cursor(conn, case_id, feed.feed_id)
    started = time.perf_counter()
    pages = 0
    while until is None or offset < until:
        limit = page_size if until is None else min(page_size, until - offset)
        rows = feed.page(offset, limit)
        if not rows:
            break
        offset = store.commit_page(conn, case_id, feed.feed_id, offset, rows, failpoint)
        pages += 1
    elapsed = time.perf_counter() - started
    return {
        "processed_n": offset - first,
        "start_cursor": first,
        "next_cursor": offset,
        "pages": pages,
        "elapsed_seconds": elapsed,
        "deliveries_per_second": (offset - first) / elapsed if elapsed else None,
        "retries": dict(getattr(feed, "retries", {})),
    }
