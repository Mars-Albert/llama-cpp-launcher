from .models import GGUFInfo, GGUFDiagnostic


def run_diagnostics(info: GGUFInfo, launcher_ctx: int = 0,
                    mmproj_path: str = "", spec_type: str = "",
                    draft_tokens: int = 0, flash_attn: bool = False) -> list[GGUFDiagnostic]:
    """Run additional diagnostics beyond what the parser produces.

    Args:
        info: Parsed GGUF info
        launcher_ctx: Current launcher context size setting
        mmproj_path: Currently selected mmproj path
        spec_type: Current speculative decoding type
        draft_tokens: Current draft token count
        flash_attn: Whether flash attention is enabled

    Returns:
        List of diagnostic items (appended to existing)
    """
    diags = list(info.diagnostics)
    arch = info.metadata.get("general.architecture", "")
    ctx_key = f"{arch}.context_length" if arch else ""

    # Context size check
    if launcher_ctx > 0 and ctx_key and ctx_key in info.metadata:
        model_ctx = info.metadata[ctx_key]
        if isinstance(model_ctx, (int, float)) and launcher_ctx > model_ctx:
            diags.append(GGUFDiagnostic(
                "warning",
                "Context exceeds model limit",
                f"Launcher context ({launcher_ctx}) exceeds model "
                f"{ctx_key} ({int(model_ctx)})."
            ))

    # mmproj match check
    if mmproj_path:
        from pathlib import Path
        mmproj_name = Path(mmproj_path).name if mmproj_path else ""
        base_name = info.filename_info.base_name if info.filename_info else ""
        if base_name and base_name.lower() not in mmproj_name.lower():
            diags.append(GGUFDiagnostic(
                "info",
                "mmproj name mismatch",
                f"mmproj filename '{mmproj_name}' does not contain "
                f"model base name '{base_name}'."
            ))

    # MTP sidecar check
    if spec_type == "draft-mtp":
        if not info.filename_info or info.filename_info.sidecar != "mtp":
            diags.append(GGUFDiagnostic(
                "info",
                "MTP spec type without MTP sidecar",
                "Speculative type is draft-mtp but file is not an mtp sidecar."
            ))

    # LoRA / vocab check
    if info.filename_info and info.filename_info.type in ("LoRA", "vocab"):
        diags.append(GGUFDiagnostic(
            "warning",
            "Special file type",
            f"This file is a {info.filename_info.type} file and cannot be used "
            "as a standalone model for inference."
        ))

    # Info-level checks
    if "tokenizer.chat_template" in info.metadata:
        diags.append(GGUFDiagnostic(
            "info",
            "Chat template detected",
            "tokenizer.chat_template is present in metadata."
        ))

    if "tokenizer.huggingface.json" in info.metadata:
        diags.append(GGUFDiagnostic(
            "info",
            "HF tokenizer detected",
            "tokenizer.huggingface.json is present in metadata."
        ))

    if arch:
        rope_key = f"{arch}.rope.scaling.type"
        if rope_key in info.metadata:
            diags.append(GGUFDiagnostic(
                "info",
                "RoPE scaling",
                f"{rope_key} = {info.metadata[rope_key]}"
            ))

        expert_count_key = f"{arch}.expert_count"
        if expert_count_key in info.metadata:
            diags.append(GGUFDiagnostic(
                "info",
                "MoE model detected",
                f"{expert_count_key} = {info.metadata[expert_count_key]}"
            ))

    if info.filename_info and info.filename_info.shard:
        diags.append(GGUFDiagnostic(
            "info",
            "Shard detected",
            f"File is part of a sharded model: {info.filename_info.shard}"
        ))

    return diags
