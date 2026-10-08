FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ripgrep fd-find git coreutils procps \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd && rm -rf /var/lib/apt/lists/* \
    && useradd -u 1000 -m -s /bin/sh sandbox && mkdir /work && chown 1000:1000 /work
USER 1000:1000
WORKDIR /work
CMD ["sleep", "infinity"]
