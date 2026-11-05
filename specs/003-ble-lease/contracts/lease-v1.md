# BLE Lease Protocol v1

## Transport

- Windows named pipe: `\\.\pipe\MagpieLcdBridge.BleLease.v1`
- Authentication key: `%LOCALAPPDATA%\MagpieLcdBridge\ble-lease.key`
- One request and one response per connection
- UTF-8 JSON bytes, maximum message size 64 KiB

## Request Envelope

```json
{
  "protocol": 1,
  "op": "acquire",
  "owner": "inkmemo",
  "token": null,
  "ttl_seconds": 120
}
```

`protocol` and `op` are required. `owner`, `token`, and `ttl_seconds` are operation-specific.

## Operations

| Operation | Required fields | Success state | Error states |
| --- | --- | --- | --- |
| `status` | none | `idle` or `active` | `invalid_request`, `unsupported_protocol` |
| `acquire` | `owner`, `ttl_seconds` | `granted` | `busy`, `invalid_owner`, invalid TTL |
| `heartbeat` | `token`, `ttl_seconds` | `granted` | `expired`, `invalid_token` |
| `release` | `token` | `released` | `expired`, `invalid_token` |

## Semantics

- TTL range is 30-600 seconds; default is 120 seconds.
- `acquire` stops the LCD worker if it was running and records that state.
- `release` restarts the worker only if it was running before `acquire`.
- The controller expires stale leases and performs the same recovery as `release`.
- A second owner must receive `busy`; it must not overwrite the active lease.
- A client must stop BLE work immediately when `busy` is returned.
- A client that cannot reach the coordinator may continue standalone only if the coordinator is unavailable; it must not treat `busy` as unavailable.
