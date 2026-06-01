# USTP (UDP Speedy Transmission Protocol)

USTP is a Python proof-of-concept reliable transport over UDP.

## Scope (current repo)
This repository focuses on the **Python transport/runtime** only:
- USTP packet format
- Selective retransmission (ACK + retransmit request)
- Out-of-order receive handling
- Stream mode (FFmpeg MPEG-TS over USTP)
- File transfer mode over USTP

## Current transport model
USTP currently uses **one connection per flow/resource**.

Examples:
- One stream = one USTP connection
- One file transfer task = one USTP connection

Planned future architecture may use multiple USTP connections for **different resources** (for example stream + chat + file task), not striping multiple connections for a single stream.

## Protocol behavior
USTP allows physical packet arrival out of order and selective recovery.

Example arrival:
`1 2 3 5 6` (packet `4` missing)

Receiver behavior:
1. Accepts `5` and `6` immediately at transport level.
2. Tracks missing `4`.
3. Sends `RETRANSMIT_REQUEST` for `4`.
4. Reconstructs logical order when needed by output mode.

## Files
- `packet.py`: packet structure and serialization
- `ustp.py`: sender/receiver core logic
- `server.py`: FFmpeg input -> USTP sender
- `client.py`: USTP receiver -> TCP or UDP local output
- `ustp_file_server.py`: file sender
- `ustp_file_client.py`: file receiver

## Requirements
- Python 3
- FFmpeg (stream mode)
- UDP reachability between peers

## Stream mode

### Server
```bash
python3 server.py \
  --peer-ip <CLIENT_IP_OR_PUBLIC_IP> \
  --peer-port 0 \
  --bind-ip 0.0.0.0 \
  --bind-port 40001 \
  --video "<HLS_URL_OR_FILE>" \
  --window 512 \
  --rto 0.25 \
  --loss 0
```

Notes:
- `--peer-port 0` enables endpoint learning from client control packets (NAT-friendly behavior).
- `--loss` simulates outbound packet loss on server side.

### Optional Congestion Control
Congestion control is **disabled by default**.

To enable it, add:
```bash
--congestion-control
```

Example:
```bash
python3 server.py \
  --peer-ip <CLIENT_IP_OR_PUBLIC_IP> \
  --peer-port 0 \
  --bind-ip 0.0.0.0 \
  --bind-port 40001 \
  --video "<HLS_URL_OR_FILE>" \
  --window 512 \
  --rto 0.25 \
  --loss 0 \
  --congestion-control
```

### Client (TCP output for VLC)
```bash
python3 client.py \
  --peer-ip <SERVER_IP> \
  --peer-port 40001 \
  --bind-ip 0.0.0.0 \
  --bind-port 40000 \
  --output-mode tcp \
  --tcp-host 127.0.0.1 \
  --tcp-port 1238
```

VLC URL:
```text
tcp://127.0.0.1:1238
```

### Client (UDP output)
```bash
python3 client.py \
  --peer-ip <SERVER_IP> \
  --peer-port 40001 \
  --bind-ip 0.0.0.0 \
  --bind-port 40000 \
  --output-mode udp \
  --udp-ip 127.0.0.1 \
  --udp-port 1238 \
  --reorder-buffer-ms 80
```

## File transfer mode

### Receiver
```bash
python3 ustp_file_client.py \
  --peer-ip <SERVER_IP> \
  --peer-port 41001 \
  --bind-ip 0.0.0.0 \
  --bind-port 41000 \
  --dst ./received
```

### Sender
```bash
python3 ustp_file_server.py \
  --peer-ip <CLIENT_IP> \
  --peer-port 0 \
  --bind-ip 0.0.0.0 \
  --bind-port 41001 \
  --src ./file_or_folder \
  --window 512 \
  --rto 0.25 \
  --loss 0
```

## Limitations
- Experimental PoC, not production-hardened.
- Generic media players may require ordered output behavior to avoid corruption.
- Behavior under high loss/high RTT is still under active tuning.

## USTP vs USTPS
- **USTP**: reliable UDP transport logic (Selective Retransmit), no built-in TLS encryption.
- **USTPS (USTP-Secure)**: USTP traffic tunneled through TLS 1.3 using modern AEAD cipher suites (AES-GCM / ChaCha20-Poly1305).
- USTP-Secure repository: https://github.com/x1colegal/USTP-Secure

## GitHub notes
Current `.gitignore` intentionally ignores:
- `*.sh`
- cache/temp/log files

If you want to version helper scripts, add them with `git add -f`.
