import sys

from .sandboxes.docker import build_image


def main():
    if sys.argv[1:] == ["build-sandbox"]:
        sys.exit(build_image())
    if sys.argv[1:2] in (["run"], ["seed"]):
        from .server import main as server_main  # `simp-server run|seed ...`

        return server_main()
    from .fake import main as fake_main  # `simp-server fake ...`

    fake_main()


if __name__ == "__main__":
    main()
