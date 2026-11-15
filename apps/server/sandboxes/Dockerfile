FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ripgrep fd-find git coreutils procps zstd s3fs \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd && rm -rf /var/lib/apt/lists/* \
    && useradd -u 1000 -m -d /home/user -s /bin/sh user && mkdir /work /home/user/repos \
    && chown 1000:1000 /work /home/user/repos
# s3fs: [sandbox] mount = "fuse" mounts the user's bucket prefix at /work (as root, then every command runs as 1000)
# /home/user is a per-user named volume (simp-home-<user_id>): docker seeds it from this dir on first use
ENV HOME=/home/user
USER 1000:1000
WORKDIR /work
CMD ["sleep", "infinity"]
