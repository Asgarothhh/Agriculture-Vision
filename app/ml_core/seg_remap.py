"""Align SegFormer checkpoint keys across transformers versions."""

from __future__ import annotations

import re
from typing import Any

# HuggingFace SegFormer renamed encoder.block → stages.blocks (q/k/v/o_proj).
_ENCODER_TO_STAGES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.patch_embeddings\.(\d+)\."),
        r"\1segformer.stages.\2.patch_embeddings.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.layer_norm_1\."),
        r"\1segformer.stages.\2.blocks.\3.layernorm_before.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.layer_norm_2\."),
        r"\1segformer.stages.\2.blocks.\3.layernorm_after.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.attention\.self\.query\."),
        r"\1segformer.stages.\2.blocks.\3.attention.q_proj.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.attention\.self\.key\."),
        r"\1segformer.stages.\2.blocks.\3.attention.k_proj.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.attention\.self\.value\."),
        r"\1segformer.stages.\2.blocks.\3.attention.v_proj.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.attention\.output\.dense\."),
        r"\1segformer.stages.\2.blocks.\3.attention.o_proj.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.attention\.self\.sr\."),
        r"\1segformer.stages.\2.blocks.\3.attention.sequence_reduction.sequence_reduction.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.attention\.self\.layer_norm\."),
        r"\1segformer.stages.\2.blocks.\3.attention.sequence_reduction.layer_norm.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.mlp\.dense1\."),
        r"\1segformer.stages.\2.blocks.\3.mlp.fc1.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.mlp\.fc1\."),
        r"\1segformer.stages.\2.blocks.\3.mlp.fc1.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.mlp\.dense2\."),
        r"\1segformer.stages.\2.blocks.\3.mlp.fc2.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.mlp\.fc2\."),
        r"\1segformer.stages.\2.blocks.\3.mlp.fc2.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.block\.(\d+)\.(\d+)\.mlp\.dwconv\."),
        r"\1segformer.stages.\2.blocks.\3.mlp.dwconv.",
    ),
    (
        re.compile(r"^((?:model\.)?)segformer\.encoder\.layer_norm\.(\d+)\."),
        r"\1segformer.stages.\2.layer_norm.",
    ),
    (
        re.compile(r"^((?:model\.)?)decode_head\.linear_c\.(\d+)\."),
        r"\1decode_head.linear_projections.\2.",
    ),
)


def _apply_key_rules(key: str, rules: tuple[tuple[re.Pattern[str], str], ...]) -> str:
    for pattern, repl in rules:
        updated = pattern.sub(repl, key, count=1)
        if updated != key:
            key = updated
    return key


def remap_segformer_state_dict(
    state: dict[str, Any],
    target_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Align checkpoint keys with the installed transformers SegFormer API."""
    if not state:
        return state
    keys = list(state)
    sample = " ".join(keys[:8])
    needs_forward = "segformer.encoder." in sample or any(".encoder." in k for k in keys)

    remapped = dict(state)
    if needs_forward and (target_keys is None or any("stages" in k for k in target_keys)):
        remapped = {_apply_key_rules(k, _ENCODER_TO_STAGES): v for k, v in remapped.items()}
    if target_keys is not None:
        overlap = len(set(remapped) & target_keys)
        raw_overlap = len(set(state) & target_keys)
        if raw_overlap > overlap:
            remapped = dict(state)
    if target_keys:
        remapped = {k: v for k, v in remapped.items() if k in target_keys}
    return remapped
