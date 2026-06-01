# USTP (UDP Speedy Transmission Protocol)

USTP is a Python proof-of-concept reliable transport over UDP.

## Scope (current repo)
This repository focuses on the **Python transport/runtime** only:
- USTP packet format
- Selective retransmission (ACK + retransmit request)
- Out-of-order receive handling
- Parallel USTP connections (striping) for better throughput/loss resilience
- Stream mode (FFmpeg MPEG-TS over USTP)
- File transfer mode over USTP

No first-party native player/app is part of the supported scope in this repo.

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
  --connections 4 \
  --stripe-burst 0 \
  --window 512 \
  --rto 0.25 \
  --loss 0
```

Notes:
- `--peer-port 0` enables endpoint learning from client control packets (NAT-friendly behavior).
- `--loss` simulates outbound packet loss on server side.
- `--connections` enables parallel USTP links. Allowed range is `1..10`.
- Hard cap is enforced in code: values above 10 are clamped to 10.
- `--stripe-burst` controls how many packets are sent on one connection before switching to the next (`0 = auto`).
- `--auto-change-connections` enables dynamic weighted distribution (better links get more packets, weaker links get fewer).
- Start with `--connections 2` or `--connections 4`. Very high values can increase jitter/reorder pressure.
- For `--connections 10`, use a higher reorder delay and burst striping (example: `--stripe-burst 12` and client `--reorder-buffer-ms 180` to `260`).
- For `--connections 10`, recommended:
  - server: `--stripe-burst 0 --auto-change-connections --congestion-control`
  - client: `--reorder-buffer-ms 180` to `260`

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
  --connections 4 \
  --stripe-burst 0 \
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
  --connections 4 \
  --stripe-burst 0 \
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

## GitHub notes
Current `.gitignore` intentionally ignores:
- `*.sh`
- `HoU/`
- cache/temp/log files

If you want to version helper scripts, add them with `git add -f`.
