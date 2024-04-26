import itertools
from collections import OrderedDict, defaultdict
from dataclasses import replace
from typing import Dict, Optional, Type

from inference.enterprise.workflows.entities.types import (
    KIND_KEY,
    REFERENCE_KEY,
    SELECTED_ELEMENT_KEY,
    Kind,
)
from inference.enterprise.workflows.execution_engine.introspection.entities import (
    BlockManifestMetadata,
    PrimitiveTypeDefinition,
    ReferenceDefinition,
    SelectorDefinition,
)
from inference.enterprise.workflows.prototypes.block import WorkflowBlockManifest

EXCLUDED_PROPERTIES = {"type"}

TYPE_MAPPING = {
    "number": "float",
    "integer": "int",
    "boolean": "bool",
    "string": "str",
    "null": "None",
}


def parse_block_manifest(
    manifest_type: Type[WorkflowBlockManifest],
) -> BlockManifestMetadata:
    schema = manifest_type.model_json_schema()
    return parse_block_manifest_schema(schema=schema)


def parse_block_manifest_schema(schema: dict) -> BlockManifestMetadata:
    primitive_types = retrieve_primitives_from_schema(
        schema=schema,
    )
    selectors = retrieve_selectors_from_schema(schema=schema)
    return BlockManifestMetadata(
        primitive_types=primitive_types,
        selectors=selectors,
    )


def retrieve_primitives_from_schema(schema: dict) -> Dict[str, PrimitiveTypeDefinition]:
    result = []
    for property_name, property_definition in schema["properties"].items():
        if property_name in EXCLUDED_PROPERTIES:
            continue
        property_description = property_definition.get("description", "not available")
        primitive_metadata = retrieve_primitive_type_from_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=property_definition,
        )
        if primitive_metadata is not None:
            result.append(primitive_metadata)
    return OrderedDict((r.property_name, r) for r in result)


def retrieve_primitive_type_from_property(
    property_name: str,
    property_description: str,
    property_definition: dict,
) -> Optional[PrimitiveTypeDefinition]:
    if REFERENCE_KEY in property_definition:
        return None
    if "items" in property_definition:
        result = retrieve_primitive_type_from_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=property_definition["items"],
        )
        if result is None:
            return None
        high_level_type = (
            "Set" if property_definition.get("uniqueItems", False) is True else "List"
        )
        return replace(
            result, type_annotation=f"{high_level_type}[{result.type_annotation}]"
        )
    if property_definition.get("type") in TYPE_MAPPING:
        type_name = TYPE_MAPPING[property_definition["type"]]
        return PrimitiveTypeDefinition(
            property_name=property_name,
            property_description=property_description,
            type_annotation=type_name,
        )
    if "$ref" in property_definition:
        return PrimitiveTypeDefinition(
            property_name=property_name,
            property_description=property_description,
            type_annotation=property_definition["$ref"].split("/")[-1],
        )
    if property_defines_union(property_definition=property_definition):
        return retrieve_primitive_type_from_union_property(
            property_name=property_name,
            property_description=property_description,
            union_definition=property_definition,
        )
    if property_definition.get("type") == "object":
        return retrieve_primitive_type_from_dict_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=property_definition,
        )
    return PrimitiveTypeDefinition(
        property_name=property_name,
        property_description=property_description,
        type_annotation="Any",
    )


def retrieve_primitive_type_from_union_property(
    property_name: str,
    property_description: str,
    union_definition: dict,
) -> Optional[PrimitiveTypeDefinition]:
    union_types = (
        union_definition.get("anyOf", [])
        + union_definition.get("oneOf", [])
        + union_definition.get("allOf", [])
    )
    primitive_union_types = [e for e in union_types if REFERENCE_KEY not in e]
    union_types_metadata = []
    for union_type in primitive_union_types:
        union_type_metadata = retrieve_primitive_type_from_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=union_type,
        )
        if union_type_metadata is None:
            continue
        union_types_metadata.append(union_type_metadata)
    if len(union_types_metadata) == 0:
        return None
    type_names = {m.type_annotation for m in union_types_metadata}
    if "None" in type_names:
        high_level_type = "Optional"
        type_names.remove("None")
    else:
        high_level_type = "Union"
    final_type_name = ", ".join(list(sorted(type_names)))
    if len(type_names) > 1:
        final_type_name = f"{high_level_type}[{final_type_name}]"
    return PrimitiveTypeDefinition(
        property_name=property_name,
        property_description=property_description,
        type_annotation=final_type_name,
    )


def retrieve_primitive_type_from_dict_property(
    property_name: str,
    property_description: str,
    property_definition: dict,
) -> Optional[PrimitiveTypeDefinition]:
    if "additionalProperties" in property_definition:
        dict_value_type = retrieve_primitive_type_from_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=property_definition["additionalProperties"],
        )
        if dict_value_type is None:
            return None
        return PrimitiveTypeDefinition(
            property_name=property_name,
            property_description=property_description,
            type_annotation=f"Dict[str, {dict_value_type.type_annotation}]",
        )
    return PrimitiveTypeDefinition(
        property_name=property_name,
        property_description=property_description,
        type_annotation=f"Dict[Any, Any]",
    )


def retrieve_selectors_from_schema(schema: dict) -> Dict[str, SelectorDefinition]:
    result = []
    for property_name, property_definition in schema["properties"].items():
        if property_name in EXCLUDED_PROPERTIES:
            continue
        property_description = property_definition.get("description", "not available")
        if "items" in property_definition:
            selector = retrieve_selectors_from_simple_property(
                property_name=property_name,
                property_description=property_description,
                property_definition=property_definition["items"],
                is_list_element=True,
            )
        else:
            selector = retrieve_selectors_from_simple_property(
                property_name=property_name,
                property_description=property_description,
                property_definition=property_definition,
            )
        if selector is not None:
            result.append(selector)
    return OrderedDict((r.property_name, r) for r in result)


def retrieve_selectors_from_simple_property(
    property_name: str,
    property_description: str,
    property_definition: dict,
    is_list_element: bool = False,
) -> Optional[SelectorDefinition]:
    if REFERENCE_KEY in property_definition:
        allowed_references = [
            ReferenceDefinition(
                selected_element=property_definition[SELECTED_ELEMENT_KEY],
                kind=[
                    Kind.model_validate(k)
                    for k in property_definition.get(KIND_KEY, [])
                ],
            )
        ]
        return SelectorDefinition(
            property_name=property_name,
            property_description=property_description,
            allowed_references=allowed_references,
            is_list_element=is_list_element,
        )
    if "items" in property_definition:
        if is_list_element:
            # ignoring nested references above first level of depth
            return None
        return retrieve_selectors_from_simple_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=property_definition["items"],
            is_list_element=True,
        )
    if property_defines_union(property_definition=property_definition):
        return retrieve_selectors_from_union_definition(
            property_name=property_name,
            property_description=property_description,
            union_definition=property_definition,
            is_list_element=is_list_element,
        )
    return None


def property_defines_union(property_definition: dict) -> bool:
    return (
        "anyOf" in property_definition
        or "oneOf" in property_definition
        or "allOf" in property_definition
    )


def retrieve_selectors_from_union_definition(
    property_name: str,
    property_description: str,
    union_definition: dict,
    is_list_element: bool,
) -> Optional[SelectorDefinition]:
    union_types = (
        union_definition.get("anyOf", [])
        + union_definition.get("oneOf", [])
        + union_definition.get("allOf", [])
    )
    results = []
    for type_definition in union_types:
        result = retrieve_selectors_from_simple_property(
            property_name=property_name,
            property_description=property_description,
            property_definition=type_definition,
            is_list_element=is_list_element,
        )
        if result is None:
            continue
        results.append(result)
    results_references = list(
        itertools.chain.from_iterable(r.allowed_references for r in results)
    )
    results_references_by_selected_element = defaultdict(set)
    for reference in results_references:
        results_references_by_selected_element[reference.selected_element].update(
            reference.kind
        )
    merged_references = []
    for (
        reference_selected_element,
        kind,
    ) in results_references_by_selected_element.items():
        merged_references.append(
            ReferenceDefinition(
                selected_element=reference_selected_element,
                kind=list(kind),
            )
        )
    if len(merged_references) == 0:
        return None
    return SelectorDefinition(
        property_name=property_name,
        property_description=property_description,
        allowed_references=merged_references,
        is_list_element=is_list_element,
    )
