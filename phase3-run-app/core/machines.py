from core.config import MACHINE_CATALOG

class MachineCatalog:
    def __init__(self) -> None:
        self._by_name = {m["name"]: m for m in MACHINE_CATALOG}

    def all(self) -> list[dict]:
        return list(MACHINE_CATALOG)

    def get(self, name: str) -> dict:
        return self._by_name[name]  # raises KeyError if unknown

class Recommender:
    """v1 stub. Until Agent O emits cells/size/volume metadata, suggest the largest
    machine used by prior runs of this case; None if no history."""
    def __init__(self) -> None:
        self._cat = MachineCatalog()

    def suggest(self, prior_runs: list[dict]) -> str | None:
        machines = [r["machine_type"] for r in prior_runs if r.get("machine_type") in self._cat._by_name]
        if not machines:
            return None
        return max(machines, key=lambda n: self._cat.get(n)["vcpus"])
