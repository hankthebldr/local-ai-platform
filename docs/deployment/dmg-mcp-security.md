# DMG MCP security posture

**Status:** v1 (1.3.0). Phase 7.3 of the MCP & Skills instrumentation plan.

Documents what stdio MCP subprocesses get when they're spawned from the
Enclave .app bundle on macOS, why we ship the entitlements we do, and the
recipe for a stricter (sandboxed) build if you're distributing through
the App Store.

## What MCP subprocesses inherit

Every stdio MCP runner spawned by `MCPRunnerPool` ([api/services/mcp_runner_pool.py](../../api/services/mcp_runner_pool.py)) inherits the .app bundle's
entitlements ([desktop/entitlements.plist](../../desktop/entitlements.plist)).
Today that surface is:

| Entitlement | Value | Why |
|---|---|---|
| `com.apple.security.app-sandbox` | `false` | User-installed MCP binaries need free filesystem access |
| `com.apple.security.cs.allow-jit` | `true` | py2app embedded Python needs JIT pages |
| `com.apple.security.cs.allow-unsigned-executable-memory` | `true` | Same as above |
| `com.apple.security.cs.disable-library-validation` | `true` | MCP binaries may load their own dylibs |
| `com.apple.security.network.client` | `true` | Outbound calls (Ollama, HTTP MCPs) |
| `com.apple.security.network.server` | `true` | Bind 127.0.0.1:8000 for the Cortex Console UI |

The user-installed binaries directory is created with `chmod 0700` on first
DMG launch (see [Phase 1.3](2026-05-19-mcp-skills-instrumentation-implementation.md)
in the implementation plan, or just look at `MCPService.binaries_dir`).

## Trust boundary

The MCP registry (`servers.json`) and binaries directory both live under
the user's home — `~/Library/Application Support/Enclave/mcp/`. Anything
that can write there can register an MCP server and have it spawned by
the next workflow that names it. Treat that directory the same way you'd
treat `~/.ssh/`.

Plugin tool Python modules (under `~/Library/Application Support/Enclave/plugins/<id>/tools/*.py`)
are loaded at PluginService scan time — they're code, not data. The Phase 1
install path checks the tarball for `..` / absolute paths but does NOT yet
verify signatures. The `trusted: bool` field stub on `plugin.yaml` exists
for the eventual signing story; v1 just documents the boundary.

## Path to a sandboxed build (App Store distribution)

If you're distributing through the Mac App Store, flip
`com.apple.security.app-sandbox` to `true` and add per-user-selected
file-scope entitlements:

```xml
<key>com.apple.security.app-sandbox</key>
<true/>
<key>com.apple.security.files.user-selected.read-write</key>
<true/>
<key>com.apple.security.files.bookmarks.app-scope</key>
<true/>
```

Caveats with sandboxed builds:
- User-installed MCP binaries must be in container-relative paths
  (typically `~/Library/Containers/com.enclave.app/Data/mcp/binaries/`).
  The `Deployment.user_storage_root` resolution would need to honor that;
  filed against the 1.4.x roadmap.
- MCP binaries that spawn child processes (e.g. a Node-based MCP that
  shells out) need their own entitlements. Document per-MCP overrides
  via an optional `desktop/entitlements.mcp-<id>.plist`.

## Verifying what's actually applied

After building the DMG, check the codesign output:

```
codesign -d --entitlements - /path/to/Enclave.app
```

The set above should be present. If `com.apple.security.app-sandbox` is
missing entirely, the runtime defaults to unsandboxed — same as if
explicitly set to `false`, but explicit is clearer.

## Related

- Container security defaults: [docker-compose.yml](../../docker-compose.yml) +
  the "Phase 7.2" comment block on the `api` service.
- Phase 1.3 storage paths: [implementation plan](../plans/2026-05-19-mcp-skills-instrumentation-implementation.md#mac-linux-form-factor-resolution-confirmed).
