# A distinct signing runtime; this does not build or replace the chain binary.
FROM luxartium-local:0.1.0 AS chain
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
COPY --from=chain /usr/local/bin/luxartiumd /usr/local/bin/luxartiumd
RUN echo '9e6525c54904c72f688b4c3d827ddda8fb7b1b0bdc938bd0ac395c1d5dcb6512  /usr/local/bin/luxartiumd' | sha256sum -c - \
    && useradd --uid 10001 --create-home signer && mkdir /state && chown signer:signer /state
WORKDIR /app
COPY hosted_signer.py gateway.py trace_protocol.py localnet.py admin_auth.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/signer
USER 10001:10001
ENTRYPOINT ["python", "/app/hosted_signer.py"]
