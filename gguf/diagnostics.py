from core.i18n import t
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
                t("上下文超过模型上限"),
                t("启动器上下文（{launcher_ctx}）超过模型 {ctx_key}（{model_ctx}）。",
                  launcher_ctx=launcher_ctx, ctx_key=ctx_key, model_ctx=int(model_ctx)),
            ))

    # mmproj match check
    if mmproj_path:
        from pathlib import Path
        mmproj_name = Path(mmproj_path).name if mmproj_path else ""
        base_name = info.filename_info.base_name if info.filename_info else ""
        if base_name and base_name.lower() not in mmproj_name.lower():
            diags.append(GGUFDiagnostic(
                "info",
                t("mmproj 名称不匹配"),
                t("mmproj 文件名 '{mmproj_name}' 不包含模型基础名称 '{base_name}'。",
                  mmproj_name=mmproj_name, base_name=base_name),
            ))

    # MTP sidecar check
    if spec_type == "draft-mtp":
        if not info.filename_info or info.filename_info.sidecar != "mtp":
            diags.append(GGUFDiagnostic(
                "info",
                t("draft-mtp 缺少 MTP 伴随文件"),
                t("投机类型为 draft-mtp，但文件不是 mtp 伴随文件。"),
            ))

    # LoRA / vocab check
    if info.filename_info and info.filename_info.type in ("LoRA", "vocab"):
        diags.append(GGUFDiagnostic(
            "warning",
            t("特殊文件类型"),
            t("该文件是 {f_type} 文件，不能作为独立模型进行推理。",
              f_type=info.filename_info.type),
        ))

    # Info-level checks
    if "tokenizer.chat_template" in info.metadata:
        diags.append(GGUFDiagnostic(
            "info",
            t("检测到聊天模板"),
            t("元数据中存在 tokenizer.chat_template。"),
        ))

    if "tokenizer.huggingface.json" in info.metadata:
        diags.append(GGUFDiagnostic(
            "info",
            t("检测到 HF 分词器"),
            t("元数据中存在 tokenizer.huggingface.json。"),
        ))

    if arch:
        rope_key = f"{arch}.rope.scaling.type"
        if rope_key in info.metadata:
            diags.append(GGUFDiagnostic(
                "info",
                t("RoPE 缩放"),
                t("{key} = {value}", key=rope_key, value=info.metadata[rope_key]),
            ))

        expert_count_key = f"{arch}.expert_count"
        if expert_count_key in info.metadata:
            diags.append(GGUFDiagnostic(
                "info",
                t("检测到 MoE 模型"),
                t("{key} = {value}", key=expert_count_key,
                  value=info.metadata[expert_count_key]),
            ))

    if info.filename_info and info.filename_info.shard:
        diags.append(GGUFDiagnostic(
            "info",
            t("检测到分片"),
            t("文件属于分片模型：{shard}", shard=info.filename_info.shard),
        ))

    return diags
