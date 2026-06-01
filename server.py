import argparse
import socket
import subprocess
import threading
import time

from packet import MAX_PAYLOAD, TYPE_ACK, TYPE_HELLO, TYPE_RETRANSMIT_REQUEST
from ustp import USTPSender, parse_packet


def main() -> None:
    ap = argparse.ArgumentParser(description="USTP Server: FFmpeg -> USTP/UDP")
    ap.add_argument("--peer-ip", required=True, help="Expected client public IP or domain")
    ap.add_argument("--peer-port", type=int, default=0, help="Optional fixed client base port; 0 = learn from HELLO source port")
    ap.add_argument("--bind-ip", default="0.0.0.0")
    ap.add_argument("--bind-port", type=int, default=40001)
    ap.add_argument("--video", required=True)
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--rto", type=float, default=0.25)
    ap.add_argument("--loss", type=int, default=0, help="Simulated outbound packet loss percent (0-100)")
    ap.add_argument("--congestion-control", action="store_true", help="Enable optional AIMD congestion control")
    ap.add_argument("--connections", type=int, default=1, help="Parallel USTP connections (1-10)")
    args = ap.parse_args()

    connections = max(1, min(10, args.connections))
    resolved_peer_ip = socket.gethostbyname(args.peer_ip)

    senders = []
    socks = []
    known_client_endpoints = set()
    ep_lock = threading.Lock()

    for i in range(connections):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((args.bind_ip, args.bind_port + i))
        peer = (resolved_peer_ip, (args.peer_port if args.peer_port > 0 else 40000) + i)
        sender = USTPSender(
            sock=s,
            peer=peer,
            window=args.window,
            rto=args.rto,
            loss_percent=args.loss,
            congestion_control=args.congestion_control,
        )
        sender.start()
        socks.append(s)
        senders.append(sender)

    print(
        f"[USTP-SERVER] peer={args.peer_ip} resolved={resolved_peer_ip} base_port={args.bind_port} "
        f"connections={connections} cc={'on' if args.congestion_control else 'off'}"
    )

    running = True

    def ctrl_loop(idx: int) -> None:
        nonlocal running
        socki = socks[idx]
        sender = senders[idx]
        while running:
            try:
                raw, addr = socki.recvfrom(65535)
            except Exception:
                continue
            if addr[0] != resolved_peer_ip:
                continue

            with ep_lock:
                known_client_endpoints.add(addr)
                if len(known_client_endpoints) > 10:
                    # Hard cap: never accept more than 10 client endpoints.
                    continue

            if args.peer_port == 0 and sender.peer != addr:
                sender.peer = addr
                print(f"[USTP-SERVER] conn={idx} learned client endpoint {addr[0]}:{addr[1]}")

            pkt = parse_packet(raw)
            if not pkt:
                continue
            if pkt.pkt_type in (TYPE_ACK, TYPE_RETRANSMIT_REQUEST, TYPE_HELLO):
                sender.on_control(pkt)

    for i in range(connections):
        threading.Thread(target=ctrl_loop, args=(i,), daemon=True).start()

    cmd = ["ffmpeg", "-re", "-i", args.video, "-c", "copy", "-mpegts_flags", "+resend_headers", "-f", "mpegts", "-"]
    print("[USTP-SERVER]", " ".join(cmd))

    proc = None
    rr = 0
    next_stream_pos = 0
    try:
        while True:
            if proc is None or proc.poll() is not None:
                if proc is not None:
                    print(f"[USTP-SERVER] ffmpeg exited code={proc.returncode}, restarting in 1s")
                    time.sleep(1.0)
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

            if proc.stdout is None:
                time.sleep(0.2)
                continue

            chunk = proc.stdout.read(MAX_PAYLOAD)
            if not chunk:
                try:
                    proc.terminate()
                except Exception:
                    pass
                proc = None
                continue

            sender = senders[rr]
            sender.queue_payload(chunk, stream_pos=next_stream_pos)
            next_stream_pos += len(chunk)
            rr = (rr + 1) % connections
    except KeyboardInterrupt:
        print("[USTP-SERVER] Interrupted")
    finally:
        running = False
        for s in senders:
            s.stop()
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        time.sleep(0.2)


if __name__ == "__main__":
    main()
