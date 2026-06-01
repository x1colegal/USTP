import argparse
import json
import random
import socket
import threading
from urllib.parse import urlsplit

from ustp_transport import USTPNode


def read_http_request(conn):
    data = bytearray()
    while b"\r\n\r\n" not in data and len(data) < 128 * 1024:
        b = conn.recv(8192)
        if not b:
            break
        data.extend(b)
    return bytes(data)


def parse_http_request(req: bytes):
    head, _, body = req.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    if not lines:
        return None

    try:
        method, target, version = lines[0].decode("utf-8", errors="replace").split(" ", 2)
    except Exception:
        return None

    headers = {}
    for ln in lines[1:]:
        if b":" not in ln:
            continue
        k, v = ln.split(b":", 1)
        headers[k.decode("utf-8", errors="replace").strip()] = v.decode("utf-8", errors="replace").strip()

    host = headers.get("Host", "").strip()
    path = target

    if target.startswith("http://") or target.startswith("https://"):
        u = urlsplit(target)
        host = u.netloc or host
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
    else:
        if not path.startswith("/"):
            path = "/" + path

    # Compatibility mode: /google.com style
    if path.startswith("/") and host == "":
        maybe = path[1:]
        if maybe and "/" not in maybe and " " not in maybe and "." in maybe:
            host = maybe
            path = "/"

    if not host:
        return None

    return {
        "method": method,
        "target": "",
        "host": host,
        "path": path,
        "version": version,
        "headers": headers,
        "body_len": len(body),
    }


def send_bad_request(conn, msg="bad request"):
    body = msg.encode("utf-8")
    conn.sendall(
        b"HTTP/1.1 400 Bad Request\r\n"
        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8")
        + body
    )


def recv_json_line(sess, timeout=12.0):
    data = bytearray()
    while True:
        b = sess.recv_bytes(4096, timeout=timeout)
        if not b:
            if sess.closed:
                return None
            continue
        data.extend(b)
        if b"\n" in data:
            line, _rest = bytes(data).split(b"\n", 1)
            return json.loads(line.decode("utf-8", errors="replace"))


def handle_http_client(conn, node, server_ip, server_port):
    try:
        req = read_http_request(conn)
        if not req:
            return

        parsed = parse_http_request(req)
        if not parsed:
            send_bad_request(conn, "invalid HTTP request / missing Host")
            return

        conn_id = random.randint(1, 0xFFFFFFFF)
        sess = node.get_or_create((server_ip, server_port), conn_id)
        sess.queue_send((json.dumps(parsed) + "\n").encode("utf-8"))

        meta = recv_json_line(sess)
        if not meta or not meta.get("ok"):
            err = (meta or {}).get("err", "upstream error")
            send_bad_request(conn, f"HoU error: {err}")
            return

        total = int(meta.get("len", 0))
        got = 0
        while got < total:
            b = sess.recv_bytes(min(16384, total - got), timeout=15.0)
            if not b:
                if sess.closed:
                    break
                continue
            conn.sendall(b)
            got += len(b)
    except Exception as e:
        send_bad_request(conn, f"internal error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="HoU Client: local HTTP -> USTP")
    ap.add_argument("--bind-ip", default="127.0.0.1")
    ap.add_argument("--bind-port", type=int, default=8080, help="Local HTTP listen port")
    ap.add_argument("--ustp-bind-ip", default="0.0.0.0")
    ap.add_argument("--ustp-bind-port", type=int, default=50000)
    ap.add_argument("--server-ip", required=True)
    ap.add_argument("--server-port", type=int, default=50001)
    ap.add_argument("--rto", type=float, default=0.35)
    ap.add_argument("--window", type=int, default=256)
    args = ap.parse_args()

    resolved = socket.gethostbyname(args.server_ip)
    node = USTPNode(args.ustp_bind_ip, args.ustp_bind_port, rto=args.rto, window=args.window)

    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind((args.bind_ip, args.bind_port))
    lsock.listen(100)

    print(
        f"[HoU-CLIENT] local HTTP on http://{args.bind_ip}:{args.bind_port} -> "
        f"USTP {args.server_ip}({resolved}):{args.server_port}"
    )

    try:
        while True:
            c, _a = lsock.accept()
            threading.Thread(target=handle_http_client, args=(c, node, resolved, args.server_port), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
