from contracts import LoadContract


def from_environment(values):
    return LoadContract(values["SOURCE"], values["DATASET"], values["KEY"], values.get("MODE", "append"))
