# ADR-048: Separate Artogrium's public home, explorer and private administration

**Status:** Accepted and implemented, 2026-09-13.
**Authorization:** The product owner proposed a website for all things Artogrium and
separating the explorer from the roadmap/processes workspace, then explicitly requested
the upgrade to that structure.

## Decision

Provide three linked surfaces within the independent local network boundary of ADR-047:

| Surface | Local origin | Purpose |
|---|---|---|
| Public Artogrium home | `http://127.0.0.1:4172` | Vision, current functionality, network information, node participation, public roadmap and documentation |
| Public explorer | `http://127.0.0.1:4173` | Read-only blocks, transactions and available account balances |
| Private operator workspace | `http://admin.artogrium.localhost:4174` | Authenticated owner access to internal roadmap, processes and workspace access events |

These are distinct audiences and HTTP origins, with separate static-asset allowlists.
The public site has a high-level roadmap. Detailed operating procedures and implementation
plans move into admin. Former explorer roadmap/processes bookmarks redirect to the
protected admin route; the explorer no longer serves their JavaScript.

The local `sites` command starts all three loopback listeners in one Python process,
with no new packages or Foundry dependency. This is a local development convenience;
separate production deployment units and domains remain future hosting work. Retain the
standalone `explorer` command. No website offers chain signing or Docker administration.
Public copy distinguishes proposed creative economics from currently working capabilities.

## Local authentication boundary

Use one random 256-bit owner access key stored outside Git at
`~/.artogrium/admin/access.key`. Only the explicit `admin-key` CLI command prints it.
Provisioning protects the credential directory and file with an owner-only Windows DACL
or POSIX 0700/0600 modes, refuses links/reparse points, and preserves existing credentials.
Windows DACL replacement is atomic and protected from inherited access. The running
server retains the access-key hash, session-token hashes and session state in memory.

Admin uses its own `.localhost` hostname because cookies are not isolated by port. The
cookie is host-only with the `__Host-` prefix, Secure, HttpOnly and SameSite=Strict, so
public `127.0.0.1` sites do not receive it. Current Chromium resolves this hostname to
loopback and accepts the local Secure cookie; this has been verified in the in-app browser.
Admin rejects alternate Host values and foreign Origin values. Session-changing requests
require the exact same Origin, bounded JSON, and an additional CSRF token for sign-out.

Five failed logins within a minute trigger throttling. Sessions expire after 30 minutes
without a workspace request or eight hours total; sign-out revokes the session and server
restart revokes all sessions. Private HTML, JavaScript and API responses are guarded on
the server and use `no-store`. Client expiration and page-history handling clear displayed
private content. Access events are bounded to 100 in memory and are not a durable audit log.

This protects the local workspace from unauthenticated browser requests. A process or
person controlling the owner's OS account remains trusted and can retrieve the key. It
does not provide multi-user identity, MFA, durable auditing, remote access, key custody or
privileged chain permissions. Public hosting requires a separately reviewed HTTPS and
managed-identity deployment; do not expose these local Python listeners remotely.

## Verification and scope

This is Lane C because it adds admin authentication. Focused unit and HTTP tests cover
session lifecycle, throttling, exact origin/host enforcement, CSRF, input bounds, private
asset isolation and credential-file permissions. Browser checks cover sign-in, private
navigation, sign-out/history, restart invalidation, public navigation and mobile layout.
Live read-only chain checks preserve existing explorer behavior. Include a handoff and
independent review.

The Foundry API, discovery, creative loop, publication, database, auth and deployment
infrastructure are unchanged. Its cold-agent and deploy gates do not apply to this isolated
local release. No blockchain code, genesis, balances, keys or container lifecycle changes
are part of this website upgrade. Economic policy and public node distribution remain
deferred under ADR-047.

References: [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[browser cookie semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie),
[Windows SetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow).
