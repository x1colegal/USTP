import argparse
import json
import random
import socket
import threading
from urllib.parse import urlsplit

from ustp_transport import USTPNode


def read_http_request(conn):
    data = bytearray()
    while b"\r\n\r\n" not in data and len(data) < 64 * 1024:
        b = conn.recv(4096)
        if not b:
            break
        data.extend(b)
    return bytes(data)


def parse_target(req: bytes) -> str:
    try:
        line = req.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
        parts = line.split(" ")
        if len(parts) < 2:
            return ""
        path = parts[1].strip()
        # expected: /google.com or /https://google.com/search?q=x
        if path.startswith("/"):
            path = path[1:]
        return path
    except Exception:
        return ""


def send_bad_request(conn, msg="bad request"):
    body = msg.encode("utf-8")
    conn.sendall(
        b"HTTP/1.1 400 Bad Request\r\n"
        + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("utf-8")
        + body
    )


def recv_json_line(sess, timeout=10.0):
    data = bytearray()
    while True:
        b = sess.recv_bytes(4096, timeout=timeout)
        if not b:
            if sess.closed:
                return None
            continue
        data.extend(b)
        if b"\n" in data:
            line, rest = bytes(data).split(b"\n", 1)
            # keep remainder by prepending back to read buffer is not supported;
            # protocol guarantees next bytes are body only after this line.
            return json.loads(line.decode("utf-8", errors="replace"))


def handle_http_client(conn, node, server_ip, server_port):
    try:
        req = read_http_request(conn)
        if not req:
            return
        target = parse_target(req)
        if not target:
            send_bad_request(conn, "use /domain-or-url (example: /google.com)")
            return

        conn_id = random.randint(1, 0xFFFFFFFF)
        sess = node.get_or_create((server_ip, server_port), conn_id)
        sess.queue_send((json.dumps({"target": target}) + "\n").encode("utf-8"))

        meta = recv_json_line(sess)
        if not meta or not meta.get("ok"):
            err = (meta or {}).get("err", "upstream error")
            send_bad_request(conn, f"HoU error: {err}")
            return

        total = int(meta.get("len", 0))
        got = 0
        while got < total:
            b = sess.recv_bytes(min(16384, total - got), timeout=10.0)
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
    lsock.listen(50)

    print(
        f"[HoU-CLIENT] local HTTP on http://{args.bind_ip}:{args.bind_port} -> "
        f"USTP {args.server_ip}({resolved}):{args.server_port}"
    )
    print("[HoU-CLIENT] request style: GET /google.com or /https://google.com/search?q=test")

    try:
        while True:
            c, _a = lsock.accept()
            threading.Thread(
                target=handle_http_client,
                args=(c, node, resolved, args.server_port),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
