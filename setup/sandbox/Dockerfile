# Tier-2 execution image for the Enclave code-exec sandbox.
# Python only — no Node, no agent runtime. Runs as non-root. Packages are
# pre-installed at build time (no dynamic pip at runtime, per the sandbox
# supply-chain guardrail). Built manually:
#   podman build -t enclave-sandbox:latest -f setup/sandbox/Dockerfile .
FROM python:3.12-slim
COPY setup/sandbox/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm -rf /root/.cache/pip
USER 65534:65534
WORKDIR /work
# No ENTRYPOINT — the backend passes `python -I /work/__entry__.py` explicitly.
