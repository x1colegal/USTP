import argparse
import json
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import requests

from ustp_transport import USTPNode

MAX_REQ = 128 * 1024
MAX_RESP = 16 * 1024 * 1024

HOP_BY_HOP = {
    "connection",
    "proxy-connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
}


def _recv_message(sess, timeout=12.0):
    data = bytearray()
    while len(data) < MAX_REQ:
        b = sess.recv_bytes(4096, timeout=timeout)
        if not b:
            if sess.closed:
                break
            continue
        data.extend(b)
        if b"\n" in data:
            line, _ = bytes(data).split(b"\n", 1)
            return line.decode("utf-8", errors="replace")
    return None


def _send_json(sess, obj):
    raw = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sess.queue_send(raw)


def _send_http_error(code: int, message: str) -> bytes:
    body = message.encode("utf-8", errors="replace")
    return (
        f"HTTP/1.1 {code} Error\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Connection: close\r\n\r\n"
    ).encode("utf-8") + body


def _normalize_upstream_url(req: dict) -> str:
    target = str(req.get("target", "")).strip()
    path = str(req.get("path", "")).strip()
    host = str(req.get("host", "")).strip()

    if target:
        if target.startswith("http://"):
            target = "https://" + target[len("http://"):]
        elif not target.startswith("https://"):
            target = "https://" + target
        return target

    if not host:
        raise ValueError("missing host")

    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path

    return f"https://{host}{path}"


def _build_request_headers(in_headers: dict) -> dict:
    out = {}
    for k, v in (in_headers or {}).items():
        if k.lower() in HOP_BY_HOP:
            continue
        out[k] = v
    out["Connection"] = "close"
    if "User-Agent" not in out:
        out["User-Agent"] = "HoU/0.3"
    if "Accept" not in out:
        out["Accept"] = "*/*"
    return out


def _rewrite_location(location: str) -> str:
    # Keep browser inside proxy route: /https://host/path
    if location.startswith("http://"):
        location = "https://" + location[len("http://"):]
    if location.startswith("https://"):
        return "/" + location
    return location


def _response_to_http_bytes(resp: requests.Response, rewrite_redirects: bool = True) -> bytes:
    code = resp.status_code
    reason = resp.reason or "OK"
    body = resp.content or b""

    lines = [f"HTTP/1.1 {code} {reason}\r\n"]
    for k, v in resp.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk == "content-length":
            continue
        if lk == "location" and rewrite_redirects:
            v = _rewrite_location(v)
        lines.append(f"{k}: {v}\r\n")

    lines.append(f"Content-Length: {len(body)}\r\n")
    lines.append("Connection: close\r\n")
    lines.append("\r\n")
    return "".join(lines).encode("utf-8", errors="replace") + body


def handle_session(sess, requests_session: requests.Session, follow_redirects: bool):
    try:
        line = _recv_message(sess)
        if not line:
            _send_json(sess, {"ok": False, "err": "empty request"})
            return

        try:
            req = json.loads(line)
        except Exception:
            _send_json(sess, {"ok": False, "err": "bad json"})
            return

        method = str(req.get("method", "GET")).upper()
        if method not in {"GET", "HEAD"}:
            method = "GET"

        url = _normalize_upstream_url(req)
        headers = _build_request_headers(req.get("headers", {}))

        upstream = requests_session.request(
            method=method,
            url=url,
            headers=headers,
            data=None,
            allow_redirects=follow_redirects,
            timeout=(6, 15),
            stream=False,
        )

        out = _response_to_http_bytes(upstream, rewrite_redirects=not follow_redirects)
        if len(out) > MAX_RESP:
            out = _send_http_error(502, "response too large")

        _send_json(sess, {"ok": True, "len": len(out)})
        for i in range(0, len(out), 1200):
            sess.queue_send(out[i:i + 1200])
        sess.close()
    except Exception as e:
        err = _send_http_error(502, f"upstream error: {e}")
        _send_json(sess, {"ok": True, "len": len(err)})
        for i in range(0, len(err), 1200):
            sess.queue_send(err[i:i + 1200])
        try:
            sess.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="HoU Server: HTTPS fetch/proxy over USTP")
    ap.add_argument("--bind-ip", default="0.0.0.0")
    ap.add_argument("--bind-port", type=int, default=50001)
    ap.add_argument("--rto", type=float, default=0.35)
    ap.add_argument("--window", type=int, default=256)
    ap.add_argument("--follow-redirects", action="store_true", help="Resolve redirects on server and return final content")
    args = ap.parse_args()

    node = USTPNode(args.bind_ip, args.bind_port, rto=args.rto, window=args.window)

    sess_http = requests.Session()
    sess_http.headers.update({"Accept-Encoding": "identity"})

    print(f"[HoU-SERVER] listening USTP on {args.bind_ip}:{args.bind_port} follow_redirects={args.follow_redirects}")

    handled = set()
    try:
        while True:
            with node.lock:
                items = list(node.sessions.items())
            for key, sess in items:
                if key in handled:
                    continue
                handled.add(key)
                threading.Thread(
                    target=handle_session,
                    args=(sess, sess_http, args.follow_redirects),
                    daemon=True,
                ).start()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
