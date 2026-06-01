import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Set, Tuple

MAGIC = b"UST2"
TYPE_DATA = 1
TYPE_ACK = 2
TYPE_RETRANSMIT_REQUEST = 3
TYPE_HELLO = 4
TYPE_CLOSE = 5

# magic(4), type(1), flags(1), conn_id(4), seq(4), length(2)
HEADER_FMT = "!4sBBIIH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_PAYLOAD = 1200


@dataclass
class USTPPacket:
    pkt_type: int
    flags: int
    conn_id: int
    seq: int
    payload: bytes

    def to_bytes(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError(f"payload too large {len(self.payload)} > {MAX_PAYLOAD}")
        h = struct.pack(HEADER_FMT, MAGIC, self.pkt_type, self.flags, self.conn_id, self.seq, len(self.payload))
        return h + self.payload

    @staticmethod
    def from_bytes(raw: bytes) -> "USTPPacket":
        if len(raw) < HEADER_SIZE:
            raise ValueError("short packet")
        magic, t, f, c, s, l = struct.unpack(HEADER_FMT, raw[:HEADER_SIZE])
        if magic != MAGIC:
            raise ValueError("bad magic")
        p = raw[HEADER_SIZE:HEADER_SIZE + l]
        if len(p) != l:
            raise ValueError("bad payload length")
        return USTPPacket(pkt_type=t, flags=f, conn_id=c, seq=s, payload=p)


def mkp(t: int, conn_id: int, seq: int = 0, payload: bytes = b"", flags: int = 0) -> USTPPacket:
    return USTPPacket(pkt_type=t, flags=flags, conn_id=conn_id, seq=seq, payload=payload)


class USTPSession:
    def __init__(self, sock: socket.socket, peer: Tuple[str, int], conn_id: int, rto: float = 0.35, window: int = 256):
        self.sock = sock
        self.peer = peer
        self.conn_id = conn_id
        self.rto = rto
        self.window = window

        self.next_send_seq = 1
        self.next_recv_seq = 1

        self.send_pending: Deque[bytes] = deque()
        self.sent: Dict[int, Tuple[bytes, float]] = {}
        self.recv_buf: Dict[int, bytes] = {}
        self.closed = False

        self.lock = threading.Lock()
        self.data_cv = threading.Condition(self.lock)
        self.read_buf = bytearray()

    def queue_send(self, data: bytes) -> None:
        if not data:
            return
        with self.lock:
            self.send_pending.append(data)
        self.flush()

    def flush(self) -> None:
        burst = 0
        while burst < 128:
            with self.lock:
                if not self.send_pending:
                    return
                if len(self.sent) >= self.window:
                    return
                chunk = self.send_pending.popleft()
                seq = self.next_send_seq
                self.next_send_seq += 1
                pkt = mkp(TYPE_DATA, self.conn_id, seq=seq, payload=chunk).to_bytes()
                self.sent[seq] = (pkt, time.time())
            self.sock.sendto(pkt, self.peer)
            burst += 1

    def on_packet(self, pkt: USTPPacket) -> None:
        if pkt.pkt_type == TYPE_ACK:
            with self.lock:
                self.sent.pop(pkt.seq, None)
            self.flush()
            return

        if pkt.pkt_type == TYPE_RETRANSMIT_REQUEST:
            with self.lock:
                item = self.sent.get(pkt.seq)
                if not item:
                    return
                raw, _ts = item
                self.sent[pkt.seq] = (raw, time.time())
            self.sock.sendto(raw, self.peer)
            return

        if pkt.pkt_type == TYPE_DATA:
            ack = mkp(TYPE_ACK, self.conn_id, seq=pkt.seq).to_bytes()
            self.sock.sendto(ack, self.peer)

            with self.lock:
                if pkt.seq < self.next_recv_seq:
                    return
                if pkt.seq == self.next_recv_seq:
                    self.read_buf.extend(pkt.payload)
                    self.next_recv_seq += 1
                    while self.next_recv_seq in self.recv_buf:
                        self.read_buf.extend(self.recv_buf.pop(self.next_recv_seq))
                        self.next_recv_seq += 1
                    self.data_cv.notify_all()
                else:
                    self.recv_buf[pkt.seq] = pkt.payload
                    for missing in range(self.next_recv_seq, pkt.seq):
                        if missing not in self.recv_buf:
                            nack = mkp(TYPE_RETRANSMIT_REQUEST, self.conn_id, seq=missing).to_bytes()
                            self.sock.sendto(nack, self.peer)
            return

        if pkt.pkt_type == TYPE_CLOSE:
            with self.lock:
                self.closed = True
                self.data_cv.notify_all()

    def recv_bytes(self, max_bytes: int, timeout: float = 1.0) -> bytes:
        end = time.time() + timeout
        with self.lock:
            while not self.read_buf and not self.closed:
                left = end - time.time()
                if left <= 0:
                    break
                self.data_cv.wait(timeout=left)
            if not self.read_buf:
                return b""
            out = bytes(self.read_buf[:max_bytes])
            del self.read_buf[:max_bytes]
            return out

    def retx_tick(self) -> None:
        now = time.time()
        to_send = []
        with self.lock:
            for seq, (raw, ts) in self.sent.items():
                if now - ts >= self.rto:
                    to_send.append((seq, raw))
            for seq, raw in to_send:
                self.sent[seq] = (raw, now)
        for _seq, raw in to_send[:128]:
            self.sock.sendto(raw, self.peer)

    def close(self) -> None:
        pkt = mkp(TYPE_CLOSE, self.conn_id).to_bytes()
        self.sock.sendto(pkt, self.peer)
        with self.lock:
            self.closed = True
            self.data_cv.notify_all()


class USTPNode:
    def __init__(self, bind_ip: str, bind_port: int, rto: float = 0.35, window: int = 256):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, bind_port))
        self.sock.settimeout(0.1)
        self.rto = rto
        self.window = window

        self.sessions: Dict[Tuple[Tuple[str, int], int], USTPSession] = {}
        self.lock = threading.Lock()
        self.running = True

        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._retx_loop, daemon=True).start()

    def get_or_create(self, peer: Tuple[str, int], conn_id: int) -> USTPSession:
        key = (peer, conn_id)
        with self.lock:
            s = self.sessions.get(key)
            if s is None:
                s = USTPSession(self.sock, peer, conn_id, rto=self.rto, window=self.window)
                self.sessions[key] = s
            return s

    def _recv_loop(self) -> None:
        while self.running:
            try:
                raw, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception:
                continue
            try:
                pkt = USTPPacket.from_bytes(raw)
            except Exception:
                continue
            s = self.get_or_create(addr, pkt.conn_id)
            s.on_packet(pkt)

    def _retx_loop(self) -> None:
        while self.running:
            with self.lock:
                sessions = list(self.sessions.values())
            for s in sessions:
                s.retx_tick()
            time.sleep(0.03)

    def stop(self) -> None:
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass
