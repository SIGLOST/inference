import abc
from collections import defaultdict
from queue import Queue
from typing import Dict, List, Optional, Set, Union

import networkx as nx
from networkx import DiGraph

# from inference.core.workflows.constants import (
#     EXECUTION_BRANCHES_STACK_PROPERTY,
#     STEP_NODE_KIND,
# )
from inference.core.workflows.entities.base import Batch
from inference.core.workflows.entities.types import FlowControl
from inference.core.workflows.errors import InvalidBlockBehaviourError
from inference.core.workflows.execution_engine.compiler.entities import NodeCategory
from inference.core.workflows.execution_engine.compiler.graph_constructor import (
    assign_max_distances_from_start,
    group_nodes_by_sorted_key_value,
)
from inference.core.workflows.execution_engine.compiler.utils import (
    get_nodes_of_specific_category,
)
from inference.core.workflows.execution_engine.executor.new_execution_cache import (
    ExecutionBranchesManager,
)


class StepExecutionCoordinator(metaclass=abc.ABCMeta):

    @classmethod
    @abc.abstractmethod
    def init(cls, execution_graph: nx.DiGraph) -> "StepExecutionCoordinator":
        pass

    @abc.abstractmethod
    def get_steps_to_execute_next(
        self, steps_to_discard: Set[str]
    ) -> Optional[List[str]]:
        pass


class ParallelStepExecutionCoordinator(StepExecutionCoordinator):

    @classmethod
    def init(cls, execution_graph: nx.DiGraph) -> "StepExecutionCoordinator":
        return cls(execution_graph=execution_graph)

    def __init__(self, execution_graph: nx.DiGraph):
        self._execution_graph = execution_graph.copy()
        self._discarded_steps: Set[str] = set()
        self.__execution_order: Optional[List[List[str]]] = None
        self.__execution_pointer = 0

    def get_steps_to_execute_next(
        self, steps_to_discard: Set[str]
    ) -> Optional[List[str]]:
        if self.__execution_order is None:
            self.__execution_order = establish_execution_order(
                execution_graph=self._execution_graph
            )
            self.__execution_pointer = 0
        self._discarded_steps.update(steps_to_discard)
        next_step = None
        while self.__execution_pointer < len(self.__execution_order):
            candidate_steps = [
                e
                for e in self.__execution_order[self.__execution_pointer]
                if e not in self._discarded_steps
            ]
            self.__execution_pointer += 1
            if len(candidate_steps) == 0:
                continue
            return candidate_steps
        return next_step


def establish_execution_order(
    execution_graph: nx.DiGraph,
) -> List[List[str]]:
    super_start_node = "<start>"
    steps_flow_graph = construct_steps_flow_graph(
        execution_graph=execution_graph,
        super_start_node=super_start_node,
    )
    distance_key = "distance"
    steps_flow_graph = assign_max_distances_from_start(
        graph=steps_flow_graph,
        start_node=super_start_node,
        distance_key=distance_key,
    )
    return group_nodes_by_sorted_key_value(
        graph=steps_flow_graph,
        excluded_nodes={super_start_node},
        key=distance_key,
    )


def construct_steps_flow_graph(
    execution_graph: nx.DiGraph,
    super_start_node: str,
) -> nx.DiGraph:
    steps_flow_graph = nx.DiGraph()
    steps_flow_graph.add_node(super_start_node)
    step_nodes = get_nodes_of_specific_category(
        execution_graph=execution_graph,
        category=NodeCategory.STEP_NODE,
    )
    for step_node in step_nodes:
        has_predecessors = False
        for predecessor in execution_graph.predecessors(step_node):
            start_node = predecessor if predecessor in step_nodes else super_start_node
            steps_flow_graph.add_edge(start_node, step_node)
            has_predecessors = True
        if not has_predecessors:
            steps_flow_graph.add_edge(super_start_node, step_node)
        for successor in execution_graph.successors(step_node):
            if successor in step_nodes:
                steps_flow_graph.add_edge(step_node, successor)
    return steps_flow_graph
