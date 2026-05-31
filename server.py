import argparse
import subprocess
import threading
import time

from packet import MAX_PAYLOAD, TYPE_ACK, TYPE_RETRANSMIT_REQUEST, TYPE_HELLO
from ustp import USTPSender, parse_packet


def main() -> None:
    ap = argparse.ArgumentParser(description="USTP Server: FFmpeg -> USTP/UDP")
    ap.add_argument("--peer-ip", required=True, help="Expected client public IP")
    ap.add_argument("--peer-port", type=int, default=0, help="Optional fixed client port; 0 = learn from HELLO source port")
    ap.add_argument("--bind-ip", default="0.0.0.0")
    ap.add_argument("--bind-port", type=int, default=40001)
    ap.add_argument("--video", required=True)
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--rto", type=float, default=0.25)
    ap.add_argument("--loss", type=int, default=0, help="Simulated outbound packet loss percent (0-100)")
    args = ap.parse_args()

    sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_DGRAM)
    sock.bind((args.bind_ip, args.bind_port))
    peer = (args.peer_ip, args.peer_port if args.peer_port > 0 else 40000)

    sender = USTPSender(sock=sock, peer=peer, window=args.window, rto=args.rto, loss_percent=args.loss)
    sender.start()

    running = True

    def ctrl_loop() -> None:
        nonlocal running
        while running:
            try:
                raw, addr = sock.recvfrom(65535)
            except Exception:
                continue
            if addr[0] != args.peer_ip:
                continue
            # NAT fix: always reply to observed source endpoint from client control traffic.
            if args.peer_port == 0 and sender.peer != addr:
                sender.peer = addr
                print(f"[USTP-SERVER] learned client endpoint {addr[0]}:{addr[1]}")
            pkt = parse_packet(raw)
            if not pkt:
                continue
            if pkt.pkt_type in (TYPE_ACK, TYPE_RETRANSMIT_REQUEST, TYPE_HELLO):
                sender.on_control(pkt)

    threading.Thread(target=ctrl_loop, daemon=True).start()

    cmd = ["ffmpeg", "-re", "-i", args.video, "-c", "copy", "-mpegts_flags", "+resend_headers", "-f", "mpegts", "-"]
    print("[USTP-SERVER]", " ".join(cmd))

    proc = None
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
                # transient source glitch/end; ffmpeg will be restarted in next loop
                try:
                    proc.terminate()
                except Exception:
                    pass
                proc = None
                continue

            sender.queue_payload(chunk)
    except KeyboardInterrupt:
        print("[USTP-SERVER] Interrupted")
    finally:
        running = False
        sender.stop()
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        time.sleep(0.2)


if __name__ == "__main__":
    main()
