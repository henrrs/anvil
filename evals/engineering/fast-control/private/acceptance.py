import sys
from limit import choose_limit


def all_cases():
    assert choose_limit(None, default=7, maximum=7) == 7
    assert choose_limit("0007", default=1, maximum=7) == 7
    for value in (True, False, 1.0, "1.0", " 1", "1 ", "", 0, -1, 8):
        try:
            choose_limit(value, default=1, maximum=7)
        except ValueError:
            continue
        raise AssertionError(f"invalid limit accepted: {type(value).__name__}")
    for args in ((None, 0, 7), (None, 1, 0), (None, 8, 7), (None, True, 7), (None, 1, True)):
        try:
            choose_limit(*args)
        except ValueError:
            continue
        raise AssertionError("invalid default/maximum accepted")


if __name__ == "__main__":
    if sys.argv[1:] != ["all"]:
        raise SystemExit(2)
    all_cases()
