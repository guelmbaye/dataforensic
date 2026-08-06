# The DataHub MCP bridge.
#
# Why a custom image rather than `supercorp/supergateway:uvx`:
#
# 1. glibc, not musl. `mcp-server-datahub` depends on `google-re2`, which
#    publishes manylinux wheels only — no musllinux. On an Alpine base pip
#    rejects every wheel, falls back to compiling `_re2.cc`, and dies with
#    `command 'c++' failed: No such file or directory`. The bridge then answers
#    /healthz perfectly while its child process is dead, which surfaces as an
#    empty tool list rather than as an error.
#
# 2. Installed at build time, not on first request. `uvx <pkg>@latest` resolves
#    and downloads ~20 MB the first time a client connects, inside the MCP
#    `initialize` handshake — long enough to blow DATAHUB_TIMEOUT_SECONDS on a
#    cold start, and repeated after every container restart.
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g supergateway@latest

# Pinned on purpose: the tool names this agent resolves against were verified for
# this release. Bump it deliberately, and re-check /api/v1/datahub/status after.
ARG MCP_SERVER_VERSION=0.6.0
RUN python3 -m venv /opt/mcp \
 && /opt/mcp/bin/pip install --no-cache-dir "mcp-server-datahub==${MCP_SERVER_VERSION}" \
 # Fail the build here if the console script is not where we expect it, rather
 # than at runtime inside a handshake nobody is watching.
 && test -x /opt/mcp/bin/mcp-server-datahub

ENV PATH="/opt/mcp/bin:${PATH}"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://localhost:8000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT ["supergateway"]

# --stateful is required, not cosmetic: the client negotiates an Mcp-Session-Id
# during initialize and reuses it for tools/list and tools/call.
CMD ["--stdio", "mcp-server-datahub", \
     "--outputTransport", "streamableHttp", \
     "--stateful", \
     "--streamableHttpPath", "/mcp", \
     "--healthEndpoint", "/healthz", \
     "--port", "8000"]
