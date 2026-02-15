from __future__ import annotations

from docutils import nodes
from docutils.parsers.rst import Directive, directives

from .nodes import a_node, dp_node, rel_node, ts_node


class TraceMetaDirective(Directive):
    has_content = False
    required_arguments = 0
    option_spec = {
        "dp": directives.unchanged_required,
        "ts": directives.unchanged_required,
        "a": directives.unchanged,
        "rel": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        paragraph = nodes.paragraph()
        paragraph += dp_node(self.options["dp"], self.options["dp"])
        paragraph += nodes.Text(" ")
        paragraph += ts_node(self.options["ts"], self.options["ts"])
        anchors_raw = self.options.get("a", "")
        for anchor in [
            value.strip() for value in anchors_raw.split(",") if value.strip()
        ]:
            paragraph += nodes.Text(" ")
            paragraph += a_node(anchor, anchor)
        relation = self.options.get("rel", "").strip()
        if relation:
            paragraph += nodes.Text(" ")
            paragraph += rel_node(relation, relation)
        return [paragraph]
