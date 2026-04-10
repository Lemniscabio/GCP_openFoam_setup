FROM microfluidica/openfoam:12

USER root

# Utilities plus Python for case-specific helper scripts.
RUN apt-get update && apt-get install -y \
    curl \
    gnupg2 \
    ca-certificates \
    lsb-release \
    htop \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Google Cloud CLI (includes gcloud storage).
RUN curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
      | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
      > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && apt-get install -y google-cloud-cli \
    && rm -rf /var/lib/apt/lists/*

# OpenFOAM env for non-interactive shells.
ENV BASH_ENV=/opt/openfoam12/etc/bashrc

# Batch entrypoint script that downloads the case, runs it, and uploads results.
COPY scripts/admin/run_case_in_batch.sh /opt/openfoam-batch/run_case_in_batch.sh
RUN chmod +x /opt/openfoam-batch/run_case_in_batch.sh

WORKDIR /root
ENTRYPOINT ["/bin/bash", "-c"]
