# Auth Proxy

This service acts as a proxy for an authentication provider (Authentik), caching user data locally and exposing it through a simplified API for devices on the local network.

It periodically fetches user information, including their card IDs and membership status, and provides endpoints to query this data.

## Configuration

Authentik token provided via `AUTHENTIK_TOKEN` or `AUTHENTIK_TOKEN_FILE` environment variable.

## Background Sync

The service automatically synchronizes user data from the Authentik service every 5 minutes. It fetches users with an active membership.

## API Reference

### Get User Stats

Returns statistics about the user data synchronization process.

**Endpoint:** `GET /users/-/stats`

**Success Response (200 OK):**

```json
{
  "last_success_run": "2025-10-08T12:00:00Z",
  "last_failed_run": null,
  "last_failed_reason": null,
  "users": {
    "count": 150
  },
  "cards": {
    "count": 350
  }
}
```

### Get User by Card ID

Retrieves a user by their associated card ID. The service handles multiple card ID formats automatically.

**Endpoint:** `GET /users/-/by-card/{card_id}`

**Path Parameters:**

*   `card_id` (string, required): The card ID to look up.

**Success Response (200 OK):**

```json
{
  "uid": "someuser",
  "mifare_card_ids": ["112233"],
  "unique_card_ids": ["aabbccdd"],
  "membership_expiration": 1765432109
}
```

**Error Response (404 Not Found):**

```json
{
  "detail": "Item not found"
}
```

### WebSocket API

For real-time communication, a WebSocket endpoint is available.

**Endpoint:** `WS /ws`

**Description:**

After establishing a connection, the client can send JSON messages to request user information.

**Request Message:**

Send a message with the following structure to look up a user by their card ID:

```json
{
  "action": "get",
  "object": "user",
  "card_id": "aabbccdd"
}
```

**Success Response:**

The server will respond with the user object if the card is found:

```json
{
  "status": "ok",
  "object": {
    "uid": "someuser",
    "mifare_card_ids": ["112233"],
    "unique_card_ids": ["aabbccdd"],
    "membership_expiration": 1765432109
  }
}
```

**Error Response:**

If the user is not found, the server will respond with an error message:

```json
{
  "status": "error",
  "error": "user not found"
}
```
