import sys

from .sandboxes.docker import build_image


def main():
    if sys.argv[1:] == ["build-sandbox"]:
        sys.exit(build_image())
    sys.exit("usage: simp-server build-sandbox")


if __name__ == "__main__":
    main()
