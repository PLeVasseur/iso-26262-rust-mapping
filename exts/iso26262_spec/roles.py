from __future__ import annotations

from docutils import nodes
from sphinx.roles import SphinxRole

from .nodes import a_node, dp_node, p_node, rel_node, ts_node


class _BaseTraceRole(SphinxRole):
    node_class: type[nodes.Node]

    def run(self) -> tuple[list[nodes.Node], list[nodes.system_message]]:
        text = self.text.strip()
        node = self.node_class(text, text)
        return [node], []


class DpRole(_BaseTraceRole):
    node_class = dp_node


class TsRole(_BaseTraceRole):
    node_class = ts_node


class ARole(_BaseTraceRole):
    node_class = a_node


class RelRole(_BaseTraceRole):
    node_class = rel_node


class PRole(_BaseTraceRole):
    node_class = p_node
