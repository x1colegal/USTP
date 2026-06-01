# HoU (HTTP/1.1 over USTP)

HoU runs a local HTTP proxy on the client and transports each request over USTP to the server.
The server fetches upstream using HTTPS and returns normalized HTTP/1.1 responses.

## Server
```bash
python3 hou_server.py --bind-ip 0.0.0.0 --bind-port 50001 --follow-redirects
```

## Client
```bash
python3 hou_client.py \
  --bind-ip 127.0.0.1 \
  --bind-port 8080 \
  --ustp-bind-ip 0.0.0.0 \
  --ustp-bind-port 50000 \
  --server-ip <SERVER_IP_OR_DOMAIN> \
  --server-port 50001
```

## Browser usage
Set HTTP proxy to:
- Host: `127.0.0.1`
- Port: `8080`

## cURL examples
```bash
curl -i -x http://127.0.0.1:8080 https://www.google.com/
curl -i -x http://127.0.0.1:8080 https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8
```

Compatibility path style (still supported):
```bash
curl -i http://127.0.0.1:8080/google.com
```

## Notes
- Upstream is forced to HTTPS.
- Redirect handling can be resolved server-side (`--follow-redirects`).
- This remains a PoC proxy and is not production-hardened.
