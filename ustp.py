import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Set, Tuple

from packet import MAX_PAYLOAD, TYPE_ACK, TYPE_CLOSE, TYPE_DATA, TYPE_HELLO, TYPE_RETRANSMIT_REQUEST, USTPPacket, mkp


@dataclass
class SentItem:
    pkt: USTPPacket
    raw: bytes
    last_sent: float


class USTPSender:
    def __init__(self, sock: socket.socket, peer: Tuple[str, int], window: int = 512, rto: float = 0.25, loss_percent: int = 0):
        self.sock = sock
        self.peer = peer
        self.window = window
        self.rto = rto
        self.loss_percent = max(0, min(100, loss_percent))

        self.next_seq = 1
        self.next_stream_pos = 0
        self.pending: Deque[bytes] = deque()
        self.sent: Dict[int, SentItem] = {}
        self.retx_queue: Deque[int] = deque()
        self.retx_set: Set[int] = set()

        self.lock = threading.Lock()
        self.running = False

    def start(self) -> None:
        self.running = True
        threading.Thread(target=self._retx_loop, daemon=True).start()
        print("[USTP-SENDER] started")

    def stop(self) -> None:
        self.running = False

    def queue_payload(self, payload: bytes) -> None:
        if not payload:
            return
        with self.lock:
            self.pending.append(payload)
        self.flush()

    def _send_raw(self, raw: bytes) -> None:
        if self.loss_percent > 0:
            if __import__("random").randint(1, 100) <= self.loss_percent:
                return
        self.sock.sendto(raw, self.peer)

    def flush(self) -> None:
        burst = 0
        while burst < 256:
            with self.lock:
                in_flight = len(self.sent)
                if in_flight >= self.window:
                    return

                # retransmit priority (can send 5,6,4,7,8 physically)
                seq = None
                if self.retx_queue:
                    seq = self.retx_queue.popleft()
                    self.retx_set.discard(seq)
                    it = self.sent.get(seq)
                    if not it:
                        continue
                    raw = it.raw
                    it.last_sent = time.time()
                elif self.pending:
                    payload = self.pending.popleft()
                    seq = self.next_seq
                    self.next_seq += 1
                    sp = self.next_stream_pos
                    self.next_stream_pos += len(payload)
                    pkt = mkp(TYPE_DATA, seq=seq, stream_pos=sp, payload=payload)
                    raw = pkt.to_bytes()
                    self.sent[seq] = SentItem(pkt=pkt, raw=raw, last_sent=time.time())
                else:
                    return

            self._send_raw(raw)
            burst += 1

    def on_control(self, pkt: USTPPacket) -> None:
        if pkt.pkt_type == TYPE_ACK:
            with self.lock:
                if pkt.seq in self.sent:
                    del self.sent[pkt.seq]
            return

        if pkt.pkt_type == TYPE_RETRANSMIT_REQUEST:
            missing = pkt.seq
            with self.lock:
                if missing in self.sent and missing not in self.retx_set:
                    self.retx_set.add(missing)
                    self.retx_queue.append(missing)
            self.flush()

    def _retx_loop(self) -> None:
        while self.running:
            now = time.time()
            timed_out = []
            with self.lock:
                for seq, it in self.sent.items():
                    if now - it.last_sent >= self.rto and seq not in self.retx_set:
                        timed_out.append(seq)
                for seq in timed_out:
                    self.retx_set.add(seq)
                    self.retx_queue.append(seq)
            if timed_out:
                print(f"[USTP-SENDER] RTO queued {len(timed_out)}")
                self.flush()
            time.sleep(0.03)


class USTPReceiver:
    def __init__(self, sock: socket.socket, peer: Tuple[str, int]):
        self.sock = sock
        self.peer = peer

        self.buffer_by_pos: Dict[int, bytes] = {}
        self.seq_to_pos: Dict[int, int] = {}
        self.next_pos = 0
        self.started = False

        self.received_seq: Set[int] = set()
        self.nack_ts: Dict[int, float] = {}

    def handle_data(self, pkt: USTPPacket) -> bytes:
        seq = pkt.seq
        pos = pkt.stream_pos

        # ACK every unique seq quickly
        if seq not in self.received_seq:
            self.received_seq.add(seq)
            ack = mkp(TYPE_ACK, seq=seq)
            self.sock.sendto(ack.to_bytes(), self.peer)

        if seq in self.seq_to_pos:
            return b""

        self.seq_to_pos[seq] = pos
        self.buffer_by_pos[pos] = pkt.payload

        if not self.started:
            self.started = True
            self.next_pos = min(self.buffer_by_pos.keys())

        out = b""
        while self.next_pos in self.buffer_by_pos:
            chunk = self.buffer_by_pos.pop(self.next_pos)
            out += chunk
            self.next_pos += len(chunk)

        return out

    def maybe_nack(self) -> None:
        # gap detection by seq continuity around observed set
        if not self.received_seq:
            return
        now = time.time()
        mn = min(self.received_seq)
        mx = max(self.received_seq)
        sent = 0
        for s in range(mn, mx):
            if s in self.received_seq:
                continue
            last = self.nack_ts.get(s, 0.0)
            if now - last < 0.2:
                continue
            self.nack_ts[s] = now
            nack = mkp(TYPE_RETRANSMIT_REQUEST, seq=s)
            self.sock.sendto(nack.to_bytes(), self.peer)
            sent += 1
            if sent >= 32:
                break
        if sent:
            print(f"[USTP-RECV] NACK sent={sent}")


def parse_packet(raw: bytes) -> Optional[USTPPacket]:
    try:
        return USTPPacket.from_bytes(raw)
    except Exception:
        return None
