import argparse
import json
import socket
import ssl
import threading
from urllib.parse import quote, urlsplit

from ustp_transport import USTPNode


MAX_REQ = 32 * 1024
MAX_RESP = 8 * 1024 * 1024


def _recv_message(sess, timeout=10.0):
    data = bytearray()
    while len(data) < MAX_REQ:
        b = sess.recv_bytes(4096, timeout=timeout)
        if not b:
            if sess.closed:
                break
            continue
        data.extend(b)
        if b"\n" in data:
            line, _rest = bytes(data).split(b"\n", 1)
            return line.decode("utf-8", errors="replace")
    return None


def _send_message(sess, obj):
    raw = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sess.queue_send(raw)


def fetch_https_raw_http(target: str) -> bytes:
    target = target.strip()
    if target.startswith("/"):
        target = target[1:]
    if not target:
        return b"HTTP/1.1 400 Bad Request\r\nContent-Length: 13\r\nConnection: close\r\n\r\nmissing target"

    if target.startswith("http://"):
        target = "https://" + target[len("http://"):]
    elif not target.startswith("https://"):
        target = "https://" + target

    u = urlsplit(target)
    host = u.hostname or ""
    if not host:
        return b"HTTP/1.1 400 Bad Request\r\nContent-Length: 12\r\nConnection: close\r\n\r\nbad target\n"
    path = u.path or "/"
    if u.query:
        path += "?" + u.query

    port = u.port or 443
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: HoU/0.1\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n"
    ).encode("utf-8")

    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=10) as s:
        with ctx.wrap_socket(s, server_hostname=host) as tls:
            tls.sendall(req)
            out = bytearray()
            while len(out) < MAX_RESP:
                b = tls.recv(16384)
                if not b:
                    break
                out.extend(b)
            return bytes(out)


def handle_session(sess):
    try:
        line = _recv_message(sess)
        if not line:
            _send_message(sess, {"ok": False, "err": "empty request"})
            return
        try:
            msg = json.loads(line)
        except Exception:
            _send_message(sess, {"ok": False, "err": "bad json"})
            return

        target = str(msg.get("target", "")).strip()
        resp = fetch_https_raw_http(target)
        _send_message(sess, {"ok": True, "len": len(resp)})
        # stream body in chunks
        off = 0
        while off < len(resp):
            sess.queue_send(resp[off:off + 1200])
            off += 1200
        sess.close()
    except Exception as e:
        _send_message(sess, {"ok": False, "err": str(e)})
        try:
            sess.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="HoU Server: HTTPS fetch over USTP")
    ap.add_argument("--bind-ip", default="0.0.0.0")
    ap.add_argument("--bind-port", type=int, default=50001)
    ap.add_argument("--rto", type=float, default=0.35)
    ap.add_argument("--window", type=int, default=256)
    args = ap.parse_args()

    node = USTPNode(args.bind_ip, args.bind_port, rto=args.rto, window=args.window)
    print(f"[HoU-SERVER] listening USTP on {args.bind_ip}:{args.bind_port}")

    handled = set()
    try:
        while True:
            with node.lock:
                items = list(node.sessions.items())
            for key, sess in items:
                if key in handled:
                    continue
                handled.add(key)
                threading.Thread(target=handle_session, args=(sess,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
