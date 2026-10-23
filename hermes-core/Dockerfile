# StaffBot customer image: official Hermes Agent + StaffBot core plugin/skills.
# One container per customer (docs/TARGET_ARCHITECTURE.md D1).
#
# Pin the upstream image. Prefer a digest for exact deployments:
#   docker build --build-arg HERMES_IMAGE=nousresearch/hermes-agent:0.22.4@sha256:<digest> \
#     -t staffbot-hermes:0.22.4-sb1 hermes-core/
ARG HERMES_IMAGE=nousresearch/hermes-agent:0.22.4
FROM ${HERMES_IMAGE}

USER root

# Core tools as a bundled plugin: root-owned inside the image, not in the
# customer's data volume. Enabled via plugins.enabled in the managed config.
COPY plugins/staffbot /opt/hermes/plugins/staffbot

# Core skills, read-only, wired in via skills.external_dirs in managed config.
COPY skills /opt/staffbot/skills

RUN chown -R root:root /opt/hermes/plugins/staffbot /opt/staffbot \
    && chmod -R a+rX,go-w /opt/hermes/plugins/staffbot /opt/staffbot

LABEL org.opencontainers.image.title="staffbot-hermes" \
      org.opencontainers.image.description="Hermes Agent for StaffBot.my managed customers"

# Managed scope (/etc/hermes/config.yaml and /etc/hermes/.env) is generated per
# customer by the control plane and bind-mounted read-only as two files, so the
# image's own /etc/hermes files stay visible. Entrypoint and CMD are upstream's;
# run with:  gateway run
