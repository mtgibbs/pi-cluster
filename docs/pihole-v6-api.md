# Pi-hole v6 REST API Reference

Reference documentation for Pi-hole v6 REST API used in this cluster.

Source: https://docs.pi-hole.net/api/

## Overview

Pi-hole v6 has a built-in REST API in FTL (no PHP/lighttpd required). All endpoints
are under `/api/`.

## Authentication

### Getting a Session ID

```bash
curl -X POST http://localhost/api/auth \
  -H "Content-Type: application/json" \
  -d '{"password":"your-password"}'
```

**Response:**
```json
{
  "session": {
    "valid": true,
    "sid": "vFA+EP4MQ5JJvJg+3Q2Jnw=",
    "csrf": "abc123...",
    "validity": 1800
  }
}
```

### Using the SID

Four methods (pick one):
1. **URL parameter**: `?sid=vFA+EP4MQ5JJvJg+3Q2Jnw=`
2. **JSON payload**: Include `"sid"` in request body
3. **Header**: `X-FTL-SID: vFA+EP4MQ5JJvJg+3Q2Jnw=`
4. **Cookie**: `sid=vFA+EP4MQ5JJvJg+3Q2Jnw=` (requires `X-FTL-CSRF` header)

## Lists Management

### GET /api/lists

Retrieve all adlists (blocklists and allowlists).

```bash
curl -X GET "http://localhost/api/lists?sid=${SID}"
```

**Query Parameters:**
- `type` (optional): `"allow"` or `"block"` to filter
- `list` (optional): Specific list address

**Response:**
```json
{
  "lists": [
    {
      "id": 1,
      "address": "https://raw.githubusercontent.com/.../hosts.txt",
      "type": "block",
      "enabled": true,
      "comment": "StevenBlack hosts",
      "groups": [0],
      "date_added": 1703001234,
      "date_modified": 1703001234,
      "date_updated": 1703012345,
      "number": 88504,
      "invalid_domains": 0,
      "status": 1
    }
  ],
  "took": 0.001
}
```

**Status Codes:**
- `1` = Successful download
- `2` = Unchanged upstream (local copy used)
- `3` = Unavailable (local copy used)
- `4` = Unavailable (no local backup exists)

### POST /api/lists

Create new adlist(s).

```bash
curl -X POST "http://localhost/api/lists?type=block&sid=${SID}" \
  -H "Content-Type: application/json" \
  -d '{
    "address": "https://example.com/blocklist.txt",
    "comment": "My blocklist",
    "groups": [0],
    "enabled": true
  }'
```

**Adding multiple lists at once:**
```bash
curl -X POST "http://localhost/api/lists?type=block&sid=${SID}" \
  -H "Content-Type: application/json" \
  -d '{
    "address": [
      "https://example.com/list1.txt",
      "https://example.com/list2.txt"
    ],
    "comment": "Batch import",
    "groups": [0],
    "enabled": true
  }'
```

**Response (201 Created):**
```json
{
  "lists": [
    {
      "id": 2,
      "address": "https://example.com/blocklist.txt",
      "type": "block",
      "enabled": true,
      "comment": "My blocklist",
      "groups": [0],
      "date_added": 1703001234,
      "date_modified": 1703001234
    }
  ],
  "took": 0.002
}
```

**Errors:**
- `400 Bad Request`: Duplicate entry or invalid payload
- `401 Unauthorized`: Missing/invalid SID

### PUT /api/lists/{address}

Update an existing list.

```bash
curl -X PUT "http://localhost/api/lists/https%3A%2F%2Fexample.com%2Flist.txt?type=block&sid=${SID}" \
  -H "Content-Type: application/json" \
  -d '{
    "comment": "Updated comment",
    "type": "block",
    "groups": [0],
    "enabled": true
  }'
```

**Note:** The list address must be URL-encoded in the path.

### DELETE /api/lists/{address}

Remove a list.

```bash
curl -X DELETE "http://localhost/api/lists/https%3A%2F%2Fexample.com%2Flist.txt?type=block&sid=${SID}"
```

**Response:** `204 No Content`

### POST /api/lists/batchDelete

Remove multiple lists at once.

```bash
curl -X POST "http://localhost/api/lists/batchDelete?sid=${SID}" \
  -H "Content-Type: application/json" \
  -d '[
    {"item": "https://example.com/list1.txt", "type": "block"},
    {"item": "https://example.com/list2.txt", "type": "block"}
  ]'
```

## Gravity Update

### POST /api/action/gravity

Run `pihole -g` to update gravity database (fetch all adlists).

```bash
curl -X POST "http://localhost/api/action/gravity?sid=${SID}"
```

**Query Parameters:**
- `color` (optional, boolean): Enable ANSI color codes in output

**Response:** Streamed text output showing gravity update progress.

## Other Useful Endpoints

### POST /api/action/restartdns

Restart pihole-FTL service.

```bash
curl -X POST "http://localhost/api/action/restartdns?sid=${SID}"
```

### POST /api/action/flush/logs

Clear DNS query logs.

```bash
curl -X POST "http://localhost/api/action/flush/logs?sid=${SID}"
```

## Database Schema (adlist table)

For reference, the underlying SQLite table structure:

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique identifier |
| `address` | text | URL of the blocklist |
| `enabled` | boolean | 0=disabled, 1=enabled |
| `date_added` | integer | UNIX timestamp |
| `date_modified` | integer | UNIX timestamp |
| `comment` | text | User notes (nullable) |
| `date_updated` | integer | Last successful sync |
| `number` | integer | Domain count from source |
| `invalid_domains` | integer | Malformed entry count |
| `status` | integer | Sync status code |

## Configuration

### PATCH /api/config

Update Pi-hole configuration settings.

```bash
curl -X PATCH "http://localhost/api/config?sid=${SID}" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "dns": {
        "upstreams": ["10.43.102.209#5335"]
      }
    }
  }'
```

**Common config paths:**
- `dns.upstreams` - Array of upstream DNS servers (format: `IP#port`)
- `dns.dnssec` - Enable/disable DNSSEC validation
- `dns.bogusPriv` - Never forward reverse lookups for private ranges

**Note:** Pi-hole v6 ignores the `PIHOLE_DNS_` environment variable. You must configure upstreams via the API.

## Example: Complete Adlist Setup Script

```bash
#!/bin/bash
# Authenticate and get SID
AUTH_RESPONSE=$(curl -s -X POST http://localhost/api/auth \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"${WEBPASSWORD}\"}")

SID=$(echo "$AUTH_RESPONSE" | jq -r '.session.sid')

if [ -z "$SID" ] || [ "$SID" = "null" ]; then
  echo "Authentication failed"
  exit 1
fi

# Add adlists (array format for batch add)
LISTS='[
  "https://adaway.org/hosts.txt",
  "https://v.firebog.net/hosts/AdguardDNS.txt"
]'

curl -s -X POST "http://localhost/api/lists?type=block&sid=${SID}" \
  -H "Content-Type: application/json" \
  -d "{\"address\":${LISTS},\"comment\":\"GitOps managed\",\"groups\":[0],\"enabled\":true}"

# Run gravity update
curl -s -X POST "http://localhost/api/action/gravity?sid=${SID}"
```
