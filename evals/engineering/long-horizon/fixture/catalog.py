CATALOG = {
    "core": {
        "1.0.0": {"dependencies": {}},
        "1.2.0": {"dependencies": {}},
        "2.0.0": {"dependencies": {}},
    },
    "store": {
        "1.0.0": {"dependencies": {"core": ">=1.0.0,<2.0.0"}},
    },
    "api": {
        "2.0.0": {"dependencies": {"core": ">=1.0.0,<2.0.0", "store": "==1.0.0"}},
    },
    "worker": {
        "1.0.0": {"dependencies": {"api": ">=2.0.0,<3.0.0"}},
    },
    "legacy-client": {
        "1.0.0": {"dependencies": {"core": "<2.0.0"}},
    },
    "modern-client": {
        "1.0.0": {"dependencies": {"core": ">=2.0.0"}},
    },
}
