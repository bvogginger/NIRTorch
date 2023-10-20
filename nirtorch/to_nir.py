from typing import Any, Callable, Optional, Sequence

import nir
import numpy as np
import torch.nn as nn

from .graph import extract_torch_graph


def extract_nir_graph(
    model: nn.Module,
    model_map: Callable[[nn.Module], nir.NIRNode],
    sample_data: Any,
    model_name: Optional[str] = "model",
    ignore_submodules_of: Optional[Sequence[nn.Module]] = None,
    ignore_dims: Optional[Sequence[int]] = None,
) -> nir.NIRNode:
    """Given a `model`, generate an NIR representation using the specified `model_map`.

    Args:
        model (nn.Module): The model of interest
        model_map (Callable[[nn.Module], nir.NIRNode]): A method that converts a given
            module type to an NIRNode type
        sample_data (Any): Sample input data to be used for model extraction
        model_name (Optional[str], optional): The name of the top level module.
            Defaults to "model".
        ignore_submodules_of (Optional[Sequence[nn.Module]]): If specified,
            the corresponding module's children will not be traversed for graph.
        ignore_dims (Optional[Sequence[int]]): Dimensions of data to be ignored for
            type/shape inference. Typically the dimensions that you will want to ignore
            are for batch and time.
    Returns:
        nir.NIR: Returns the generated NIR graph representation.
    """

    if len(list(model.children())):
        # If the model has submodules, ignore the top level module
        model_name = None

    # Extract a torch graph given the model
    torch_graph = extract_torch_graph(
        model, sample_data=sample_data, model_name=model_name
    ).ignore_tensors()

    if ignore_submodules_of is not None:
        torch_graph = torch_graph.ignore_submodules_of(ignore_submodules_of)

    # Get the root node
    root_nodes = torch_graph.get_root()
    if len(root_nodes) != 1:
        raise ValueError(
            f"Currently, only one input is supported, but {len(root_nodes)} was given"
        )

    # Convert the nodes and get indices
    nir_edges = []
    input_shape = np.array(sample_data.shape)
    if ignore_dims:
        nir_nodes = {"input": nir.Input(np.delete(input_shape, ignore_dims))}
    else:
        nir_nodes = {"input": nir.Input(input_shape)}
    nir_edges = []

    # Get all the NIR nodes
    for indx, node in enumerate(torch_graph.node_list):
        # Convert the node type to NIR subgraph
        mapped_node = model_map(node.elem)

        if isinstance(mapped_node, nir.NIRGraph):
            for k, v in mapped_node.nodes.items():
                # For now, we add nodes in subgraphs to the top-level node list
                # TODO: Parse graphs recursively
                if isinstance(v, nir.NIRNode):
                    nir_nodes[f"{node.name}.{k}"] = v
                else:
                    nir_nodes[v.name] = v
            # Add edges from graph
            for x, y in mapped_node.edges:
                nir_edges.append((f"{node.name}.{x}", f"{node.name}.{y}"))
        else:
            nir_nodes[node.name] = mapped_node

        # Add edges from input, if first element
        # TODO: Replace with mapping to input(s)/output(s) of subgraph
        if indx == 0:  # TODO:
            keys = list(nir_nodes.keys())
            for k1, k2 in zip(keys[:-1], keys[1:]):
                nir_edges.append((k1, k2))

    # Get all the edges
    for node in torch_graph.node_list:
        for destination, shape in node.outgoing_nodes.items():
            nir_edges.append((node.name, destination.name))

        if len(node.outgoing_nodes) == 0:
            out_name = "output"
            # Try to find shape of input to the Output node
            if ignore_dims:
                out_shape = np.delete(
                    torch_graph.module_output_types[node.elem], ignore_dims
                )
            else:
                out_shape = torch_graph.module_output_types[node.elem]
            output_node = nir.Output(out_shape)
            nir_nodes[out_name] = output_node
            nir_edges.append((node.name, out_name))

    # Remove duplicate edges
    nir_edges = list(set(nir_edges))

    return nir.NIRGraph(nir_nodes, nir_edges)
