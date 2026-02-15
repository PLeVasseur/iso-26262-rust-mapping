from __future__ import annotations

from typing import Any

from sphinx.domains import Domain


class TraceDomain(Domain):
    name = "trace"
    label = "Traceability"
    roles: dict[str, Any] = {}
    directives: dict[str, Any] = {}
    initial_data = {
        "objects": {},
    }

    def clear_doc(self, docname: str) -> None:
        stale = [
            key
            for key, value in self.data.get("objects", {}).items()
            if value[0] == docname
        ]
        for key in stale:
            del self.data["objects"][key]

    def merge_domaindata(self, docnames: list[str], otherdata: dict[str, Any]) -> None:
        self.data.setdefault("objects", {}).update(otherdata.get("objects", {}))

    def get_objects(self) -> list[tuple[str, str, str, str, str, int]]:
        objects = []
        for name, value in self.data.get("objects", {}).items():
            docname, anchor = value
            objects.append((name, name, "statement", docname, anchor, 1))
        return objects
