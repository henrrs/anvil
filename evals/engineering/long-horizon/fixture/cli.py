import argparse


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "install"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root")
    parser.parse_args(argv)
    raise NotImplementedError("CLI integration is part of the task")


if __name__ == "__main__":
    raise SystemExit(main())
