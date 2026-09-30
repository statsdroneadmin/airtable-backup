# Security

## Reporting a vulnerability

Open a private security advisory on this repository (Security → Report a vulnerability),
or open an issue with no sensitive detail and ask for a private channel.

## What this plugin handles

- An **Airtable Personal Access Token**, stored encrypted by NousViz (declared
  `type: password`, `secret: true`). It is sent only in the `Authorization` header to
  `api.airtable.com`, never in a URL, and Airtable error messages are parsed without echoing
  the request, so the token does not reach logs or toasts.
- **Read-only toward Airtable.** The plugin only calls read endpoints (list bases, base
  schema, list records, list comments). It never creates, edits or deletes anything in
  Airtable. Grant the token read scopes only: `data.records:read`, `schema.bases:read`,
  and optionally `data.recordComments:read`.
- **Attachment files** are downloaded from Airtable's signed, expiring URLs without the
  token and stored in the plugin's own Postgres table. Signed URLs are stripped before
  records are stored, so no working download links are persisted.
- **The backup contains your Airtable data.** Every route requires an authenticated
  NousViz user, and there is no per-user filtering inside the plugin: anyone with access
  to this NousViz instance can browse and export every backed-up base. Install it only
  where that is acceptable.

## Scope

This plugin runs inside NousViz and trusts its authentication. Findings about NousViz core
belong to the NousViz project, not here.
