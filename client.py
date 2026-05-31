import argparse
import socket
import threading
import time
from collections import deque

from packet import TYPE_CLOSE, TYPE_DATA, TYPE_HELLO, mkp
from ustp import USTPReceiver, parse_packet


def main() -> None:
    ap = argparse.ArgumentParser(description="USTP Client: USTP/UDP -> TCP localhost:1238")
    ap.add_argument("--peer-ip", required=True)
    ap.add_argument("--peer-port", type=int, default=40001)
    ap.add_argument("--bind-ip", default="0.0.0.0")
    ap.add_argument("--bind-port", type=int, default=40000)
    ap.add_argument("--tcp-host", default="127.0.0.1")
    ap.add_argument("--tcp-port", type=int, default=1238)
    ap.add_argument("--keepalive-interval", type=float, default=0.12)
    args = ap.parse_args()

    usock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    usock.bind((args.bind_ip, args.bind_port))
    peer = (args.peer_ip, args.peer_port)

    recv = USTPReceiver(sock=usock, peer=peer)
    out_by_pos = {}
    next_out_pos = 0

    tsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tsock.bind((args.tcp_host, args.tcp_port))
    tsock.listen(5)

    clients = []
    cl_lock = threading.Lock()

    def accept_loop() -> None:
        while True:
            try:
                c, a = tsock.accept()
            except Exception:
                continue
            with cl_lock:
                clients.append(c)
            print(f"[USTP-CLIENT] TCP client {a}")

    def bcast(data: bytes) -> None:
        dead = []
        with cl_lock:
            for c in clients:
                try:
                    c.sendall(data)
                except Exception:
                    dead.append(c)
            for d in dead:
                try:
                    d.close()
                except Exception:
                    pass
                clients.remove(d)

    running = True

    def keepalive_loop() -> None:
        while running:
            hello = mkp(TYPE_HELLO, payload=(48).to_bytes(2, "big"))
            usock.sendto(hello.to_bytes(), peer)
            time.sleep(args.keepalive_interval)

    def nack_loop() -> None:
        while running:
            recv.maybe_nack()
            time.sleep(0.03)

    threading.Thread(target=accept_loop, daemon=True).start()
    threading.Thread(target=keepalive_loop, daemon=True).start()
    threading.Thread(target=nack_loop, daemon=True).start()

    print(f"[USTP-CLIENT] TCP output on tcp://{args.tcp_host}:{args.tcp_port}")

    try:
        while True:
            raw, addr = usock.recvfrom(65535)
            if addr[0] != args.peer_ip:
                continue
            pkt = parse_packet(raw)
            if not pkt:
                continue
            if pkt.pkt_type == TYPE_CLOSE:
                break
            if pkt.pkt_type == TYPE_DATA:
                # Keep USTP transport behavior (accept out-of-order), but TCP output
                # must be strictly ordered by stream_pos to avoid payload corruption.
                recv.handle_data(pkt)
                out_by_pos[pkt.stream_pos] = pkt.payload
                while next_out_pos in out_by_pos:
                    chunk = out_by_pos.pop(next_out_pos)
                    bcast(chunk)
                    next_out_pos += len(chunk)
    except KeyboardInterrupt:
        print("[USTP-CLIENT] Interrupted")
    finally:
        running = False


if __name__ == "__main__":
    main()
