from typing import Dict, List, Set, Union

from inference.core.workflows.execution_engine.executor.execution_data_manager.dynamic_batches_manager import (
    DynamicBatchIndex,
)


class BranchingManager:

    @classmethod
    def init(cls) -> "BranchingManager":
        return cls(masks={})

    def __init__(self, masks: Dict[str, Union[Set[DynamicBatchIndex], bool]]):
        self._masks = masks
        self._batch_compatibility = {
            branch_name: not isinstance(mask, bool)
            for branch_name, mask in masks.items()
        }

    def register_batch_oriented_mask(
        self,
        execution_branch: str,
        mask: set[DynamicBatchIndex],
    ) -> None:
        if execution_branch in self._masks:
            raise ValueError(
                f"Attempted to re-register maks for execution branch: {execution_branch}"
            )
        self._batch_compatibility[execution_branch] = True
        self._masks[execution_branch] = mask

    def register_non_batch_mask(self, execution_branch: str, mask: bool) -> None:
        if execution_branch in self._masks:
            raise ValueError(
                f"Attempted to re-register maks for execution branch: {execution_branch}"
            )
        self._batch_compatibility[execution_branch] = False
        self._masks[execution_branch] = mask

    def get_mask(self, execution_branch: str) -> Union[Set[DynamicBatchIndex], bool]:
        if execution_branch not in self._masks:
            raise ValueError(
                f"Attempted to get mask for not registered execution branch: {execution_branch}"
            )
        return self._masks[execution_branch]

    def is_execution_branch_batch_oriented(self, execution_branch: str) -> bool:
        if execution_branch not in self._batch_compatibility:
            raise ValueError(
                f"Attempted to get information about not registered execution branch: {execution_branch}"
            )
        return self._batch_compatibility[execution_branch]

    def is_execution_branch_registered(self, execution_branch: str) -> bool:
        return execution_branch in self._masks
