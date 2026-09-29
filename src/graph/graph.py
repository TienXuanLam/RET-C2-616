"""AgentCore Platform v1.0"""

# Cat 2 — Multi-step domain workflow (job-to-be-done)
# Supplier data receipt -> multi-dimensional KPI scoring -> Subcontract Act
# compliance flags -> scorecard report generation. The proposal describes 4
# logical blocks (PreProcess / KPIScoring / DocGeneration / Output) but
# AgentBaseGraph exposes exactly 3 fixed domain slots — KPIScoringNode
# (step-helper, src/nodes/kpi_scoring_node.py) and DocGenerationNode's
# narrative logic both run inside MainNode.execute(), registered in the
# "main" slot. See docs/02_design.md "Node mapping note" for the rationale.

from framework.graph.agent_base_graph import AgentBaseGraph

from src.nodes.pre_process_node import PreProcessNode
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.kpi_scoring_node import load_kpi_thresholds, load_subcontract_rules
from src.schemas.state import State


class RetailSupplierQualitySLAScorecardAgent(AgentBaseGraph):
    """Scores supplier SLA KPIs, flags Subcontract Act Article 4
    prohibited-act conditions, and generates a compliance scorecard."""

    @property
    def name(self) -> str:
        return "RetailSupplierQualitySLAScorecardAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        llm = self.config["llm"]
        kpi_thresholds = self.config.get("kpi_thresholds") or load_kpi_thresholds("config/kpi_thresholds.yaml")
        subcontract_rules = self.config.get("subcontract_rules") or load_subcontract_rules(
            "config/subcontract_rules.yaml"
        )

        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode(
            llm=llm,
            kpi_thresholds=kpi_thresholds,
            subcontract_rules=subcontract_rules,
        )
        self._nodes["post_process"] = PostProcessNode()
