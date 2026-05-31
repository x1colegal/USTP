# USTP (UDP Speedy Transmission Protocol)

USTP is a reliable transport protocol built over UDP with selective retransmission.

## What it does
- Reliable delivery over UDP (ACK + selective retransmit)
- Out-of-order reception with in-order reconstruction
- NAT-friendly endpoint learning on server side
- Live MPEG-TS forwarding (for VLC testing)
- Generic file transfer over USTP

## Protocol behavior (loss case)
Example sequence:
1, 2, 3, 4(lost), 5, 6, 7, 8

Receiver behavior:
- Accepts 5, 6, 7, 8 immediately
- Buffers out-of-order packets
- Requests retransmit for missing 4
- When 4 arrives, reconstructs and delivers in correct order

## Project files
- `packet.py`: USTP packet format
- `ustp.py`: USTP sender/receiver core for stream mode
- `server.py`: USTP stream sender (FFmpeg -> USTP/UDP)
- `client.py`: USTP stream receiver (USTP/UDP -> TCP localhost:1238)
- `ustp_file_server.py`: USTP file transfer sender
- `ustp_file_client.py`: USTP file transfer receiver
- `sender.py` / `receiver.py`: thin wrappers
- `HoU/`: experimental HTTP-over-USTP work (ignored by default)

## Requirements
- Python 3
- FFmpeg (for stream mode)
- UDP reachable between peers

No root is required on Android for USTP (regular UDP sockets).

---

## 1) Stream mode (MPEG-TS over USTP)

### Server (VPS/PC)
```bash
python3 server.py \
  --peer-ip <CLIENT_PUBLIC_IP> \
  --peer-port 0 \
  --bind-ip 0.0.0.0 \
  --bind-port 40001 \
  --video "<VIDEO_URL_OR_LOCAL_FILE>" \
  --window 512 \
  --rto 0.25 \
  --loss 0
```

Notes:
- `--peer-port 0` enables endpoint learning from client HELLO source port (NAT-friendly).
- `--loss` is simulated outbound packet loss on server side.

### Client (Android/PC)
```bash
python3 client.py \
  --peer-ip <SERVER_PUBLIC_IP> \
  --peer-port 40001 \
  --bind-ip 0.0.0.0 \
  --bind-port 40000 \
  --tcp-host 127.0.0.1 \
  --tcp-port 1238 \
  --keepalive-interval 0.12
```

### VLC
Open:
```text
tcp://127.0.0.1:1238
```

---

## 2) File transfer mode (generic bytes over USTP)

### Receiver (client side)
```bash
python3 ustp_file_client.py \
  --peer-ip <SERVER_PUBLIC_IP> \
  --peer-port 41001 \
  --bind-ip 0.0.0.0 \
  --bind-port 41000 \
  --dst ./received
```

### Sender (server side)
```bash
python3 ustp_file_server.py \
  --peer-ip <CLIENT_PUBLIC_IP> \
  --peer-port 0 \
  --bind-ip 0.0.0.0 \
  --bind-port 41001 \
  --src ./file_or_folder \
  --window 512 \
  --rto 0.25 \
  --loss 0
```

Notes:
- Supports single file or recursive folder transfer.
- Uses app frames: metadata, data, end-of-file.

---

## GitHub publish notes
This repo includes a `.gitignore` that ignores:
- `*.sh`
- `HoU/`
- cache/temp/log files

If needed, adjust `.gitignore` before publishing.

## Disclaimer
USTP is a PoC transport protocol for experimentation and learning. It is not production-hardened like QUIC.
