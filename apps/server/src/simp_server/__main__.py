import sys

from .sandboxes.docker import build_image


def main():
    if sys.argv[1:] == ["build-sandbox"]:
        sys.exit(build_image())
    from .fake import main as fake_main  # `simp-server fake ...`

    fake_main()


if __name__ == "__main__":
    main()
