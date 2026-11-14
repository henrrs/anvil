from catalog import CATALOG
from resolver import resolve
from store import load_state, save_state


def install(manifest, root, catalog=CATALOG, fail_after=None):
    raise NotImplementedError("safe staged installation is part of the task")
