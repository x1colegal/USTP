# HoU (HTTP/1.1 over USTP)

HoU exposes a local HTTP endpoint on the client and tunnels the request over USTP to the server.

Server behavior:
- Receives target path from client (example: `google.com`)
- Always fetches upstream using HTTPS
- Returns raw HTTP response bytes to client

## Start server
```bash
python3 hou_server.py --bind-ip 0.0.0.0 --bind-port 50001
```

## Start client
```bash
python3 hou_client.py \
  --bind-ip 127.0.0.1 \
  --bind-port 8080 \
  --ustp-bind-ip 0.0.0.0 \
  --ustp-bind-port 50000 \
  --server-ip <SERVER_IP_OR_DOMAIN> \
  --server-port 50001
```

## Use
Examples:
```bash
curl -i http://127.0.0.1:8080/google.com
curl -i "http://127.0.0.1:8080/https://example.com/?q=test"
```

Notes:
- Upstream fetch is always HTTPS.
- This is a PoC and not a hardened secure proxy.
