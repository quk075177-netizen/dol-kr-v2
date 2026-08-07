"""Lossless Twee/SugarCube pre-translation CST helpers."""

from .masking import mask_passage, restore_mask
from .grammar import MacroRegistry, MacroSpec, load_macro_registry
from .chunking import TranslateUnit, chunk_passage
from .model import (
    ArgNode,
    CstNode,
    Diagnostic,
    MacroNode,
    MaskArtifact,
    Passage,
    Placeholder,
    Segment,
    SourceFile,
    Span,
)
from .parser import SourceContext, parse_file, parse_passage, split_twee

__all__ = [
    "ArgNode", "CstNode", "Diagnostic", "MacroNode", "MacroRegistry", "MacroSpec",
    "MaskArtifact", "Passage", "Placeholder", "Segment", "SourceContext", "SourceFile", "Span",
    "TranslateUnit", "chunk_passage",
    "load_macro_registry", "mask_passage", "parse_file", "parse_passage", "restore_mask", "split_twee",
]
