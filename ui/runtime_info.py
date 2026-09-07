"""HTML rendering of parsed runtime info (no Qt dependency).

Extracted from ui/main_window.py (optimization-plan C2): info dict -> HTML.
"""
import html as html_mod

from core.i18n import t


def empty_info_html():
    """Placeholder shown before the server starts."""

    return f"""
    <div style="color: #6c7086; font-size: 13px; padding: 30px; text-align: center;">
        <p style="font-size: 18px; margin-bottom: 12px;">🚀 {t("运行信息")}</p>
        <p>{t("启动服务后，此处将自动解析并显示：")}</p>
        <p style="margin-top: 8px;">{t("GPU 设备 · 模型详情 · 参数量 · 显存占用 · KV Cache · 视觉编码器 等关键信息")}</p>
    </div>
    """



def build_info_html(info):
    """Render the runtime info dict as an HTML table."""
    categories = []

    items = []
    # Support multiple GPUs (new format) or single GPU (old format)
    gpu_indices = sorted(set(k[3:k.index('_')] for k in info if k.startswith('gpu') and k[3:4].isdigit() and '_' in k))
    if gpu_indices:
        for idx in gpu_indices:
            name = info.get(f"gpu{idx}_name", "")
            vram = info.get(f"gpu{idx}_vram", "")
            free = info.get(f"gpu{idx}_free", "")
            label = t("🖥️ GPU {idx} 设备", idx=idx)
            val = name
            if vram:
                val += f" ({vram}"
                if free:
                    val += t(", 空闲 {free}", free=free)
                val += ")"
            items.append((label, val))
    elif info.get("gpu_name"):
        items.append((t("🖥️ GPU 设备"), info.get("gpu_name")))
    # E8: single-line summary of what this run actually used (devices + offload)
    if gpu_indices:
        parts = []
        for idx in gpu_indices:
            name = info.get(f"gpu{idx}_name", "")
            vram = info.get(f"gpu{idx}_vram", "")
            parts.append(f"{name} ({vram})" if vram else name)
        parts = [p for p in parts if p]
        if parts:
            summary = " + ".join(parts)
            if info.get("gpu_offload"):
                summary += f" · {info['gpu_offload']}"
            items.insert(0, (t("🖥️ GPU（本次运行）"), summary))
    if info.get("gpu_compute_cap"):
        items.append((t("🔧 计算能力（CUDA 架构版本）"), info.get("gpu_compute_cap")))
    if not gpu_indices and info.get("gpu_vram"):
        items.append((t("📊 显卡显存（总可用显存）"), info.get("gpu_vram")))
    if info.get("cpu_name"):
        items.append((t("💻 CPU 设备"), info.get("cpu_name")))
    if info.get("cpu_ram"):
        items.append((t("📊 系统内存"), info.get("cpu_ram")))
    if items:
        categories.append((t("硬件信息"), items))

    items = []
    if info.get("address"):
        items.append((t("🌐 服务地址"), info.get("address")))
    if info.get("model_file"):
        items.append((t("📦 模型文件"), info.get("model_file")))
    if info.get("model_name"):
        items.append((t("🏷️ 模型名称"), info.get("model_name")))
    if info.get("quant_type"):
        items.append((t("📐 量化类型（量化格式）"), info.get("quant_type")))
    if info.get("file_size"):
        items.append((t("💾 文件大小（磁盘占用）"), info.get("file_size")))
    if info.get("gguf_version"):
        items.append((t("📄 GGUF 版本"), info.get("gguf_version")))
    if items:
        categories.append((t("模型信息"), items))

    items = []
    if info.get("model_params"):
        items.append((t("🔢 参数量（模型总参数）"), info.get("model_params")))
    if info.get("arch"):
        items.append((t("🏗️ 模型架构"), info.get("arch")))
    if info.get("n_layers"):
        items.append((t("📚 网络层数（Transformer 层数）"), info.get("n_layers")))
    if info.get("embed_dim"):
        items.append((t("📊 嵌入维度（向量维度大小）"), info.get("embed_dim")))
    if info.get("n_ff"):
        items.append((t("🔢 FFN 维度（前馈网络宽度）"), info.get("n_ff")))
    if info.get("vocab_size"):
        items.append((t("📚 词表大小（Token 数量）"), info.get("vocab_size")))
    if info.get("vocab_type"):
        items.append((t("🔤 词表类型（分词方式）"), info.get("vocab_type")))
    if info.get("tensor_types"):
        tensor_lines = []
        for qtype, qcount in sorted(info["tensor_types"].items()):
            tensor_lines.append(f"{qtype}: {qcount}")
        items.append((t("🎨 精度分布（各精度张量数量）"), " / ".join(tensor_lines)))
    if items:
        categories.append((t("模型架构"), items))

    items = []
    if info.get("train_ctx"):
        items.append((t("📏 训练上下文（模型最大支持长度）"), info.get("train_ctx")))
    if info.get("ctx_size_seq"):
        items.append((t("📐 运行上下文（实际使用长度）"), info.get("ctx_size_seq")))
    elif info.get("ctx_size"):
        items.append((t("📐 运行上下文（配置长度）"), info.get("ctx_size")))
    if info.get("n_batch"):
        items.append((t("📦 批处理大小（每次处理 Token 数）"), info.get("n_batch")))
    if info.get("n_ubatch"):
        items.append((t("📦 物理批处理（硬件实际批次）"), info.get("n_ubatch")))
    if info.get("sliding_window"):
        items.append((t("🪟 滑动窗口（SWA 窗口大小）"), info.get("sliding_window")))
    if info.get("freq_base"):
        items.append((t("📡 RoPE 频率（位置编码基频）"), info.get("freq_base")))
    if info.get("freq_base_runtime"):
        items.append((t("📡 运行 RoPE（实际使用基频）"), info.get("freq_base_runtime")))
    if info.get("n_slots"):
        items.append((t("🎰 槽位数（并发请求数）"), info.get("n_slots")))
    if info.get("thinking_mode"):
        items.append((t("🧠 推理模式（思维链/深度思考）"), t(info.get("thinking_mode"))))
    if items:
        categories.append((t("运行参数"), items))

    items = []
    if info.get("gpu_offload"):
        items.append((t("🖥️ GPU 卸载（加载到 GPU 的层数）"), info.get("gpu_offload")))
    if info.get("model_vram"):
        items.append((t("📦 模型显存（模型权重占用）"), info.get("model_vram")))
    if info.get("cpu_buffer"):
        items.append((t("💻 CPU 缓冲（CPU 侧模型缓冲）"), info.get("cpu_buffer")))
    if info.get("projected_vram"):
        items.append((t("📊 预计显存（预估显存用量）"), info.get("projected_vram")))
    kv_total = info.get("kv_cache_total")
    if kv_total:
        if isinstance(kv_total, (int, float)):
            items.append((t("💾 KV Cache（键值缓存总量）"), f"{kv_total:.2f} MiB"))
        else:
            items.append((t("💾 KV Cache（键值缓存总量）"), kv_total))
    if info.get("compute_buffer"):
        items.append((t("🔲 计算缓冲（GPU 计算临时缓冲）"), info.get("compute_buffer")))
    if info.get("prompt_cache"):
        items.append((t("💬 Prompt 缓存（系统提示词缓存上限）"), t(info.get("prompt_cache"))))
    if items:
        categories.append((t("显存占用"), items))

    items = []
    if info.get("flash_attn"):
        items.append((t("⚡ Flash Attention（高效注意力机制）"), t(info.get("flash_attn"))))
    if info.get("kv_unified"):
        items.append((t("🔗 KV 统一（统一 KV 缓存）"), t(info.get("kv_unified"))))
    if info.get("graph_nodes"):
        items.append((t("🔗 图节点数（计算图节点数量）"), info.get("graph_nodes")))
    if info.get("graph_splits"):
        items.append((t("✂️ 图分割数（CPU/GPU 切换次数）"), info.get("graph_splits")))
    if items:
        categories.append((t("性能优化"), items))

    items = []
    if info.get("n_threads") or info.get("n_threads_batch"):
        threads_str = t("推理={n} / 批处理={nb} / 总计={total}", n=info.get('n_threads', '?'), nb=info.get('n_threads_batch', '?'), total=info.get('total_threads', '?'))
        items.append((t("🔧 线程配置（CPU 线程数）"), threads_str))
    if info.get("threads_http"):
        items.append((t("🌐 HTTP 线程数"), info.get("threads_http")))
    if info.get("openmp"):
        items.append((t("🔗 OpenMP（并行计算加速）"), t(info.get("openmp"))))
    if info.get("repack"):
        items.append((t("📦 Repack（权重重打包优化）"), t(info.get("repack"))))
    if info.get("speculative_decoding"):
        items.append((t("🚀 投机解码（Speculative Decoding）"), t(info.get("speculative_decoding"))))
    if items:
        categories.append((t("系统配置"), items))

    if info.get("has_vision") or info.get("vision_min_tokens"):
        items = []
        if info.get("has_vision"):
            items.append((t("👁️ 视觉编码器（多模态图像理解）"), t("已加载")))
        if info.get("mmproj_file"):
            items.append((t("📦 投影文件（视觉投影模型）"), info.get("mmproj_file")))
        if info.get("vision_model_size"):
            items.append((t("📊 视觉模型大小"), info.get("vision_model_size")))
        if info.get("vision_image_size"):
            items.append((t("🖼️ 图像尺寸（输入图像分辨率）"), info.get("vision_image_size")))
        if info.get("vision_min_tokens"):
            items.append((t("🔢 最小图像 Token 数"), info.get("vision_min_tokens")))
        if items:
            categories.append((t("视觉编码器"), items))

    def make_rows(items):
        rows = []
        for label, value in items:
            safe_value = html_mod.escape(str(value))
            safe_label = html_mod.escape(str(label))
            color = "#a6e3a1" if "✅" in str(value) else ("#7aa2f7" if value != "—" else "#6c7086")
            rows.append(f'<tr><td style="color: #7aa2f7; font-weight: bold; padding: 3px 12px 3px 0; white-space: nowrap; vertical-align: top; width: 1%;">{safe_label}</td><td style="color: {color}; padding: 3px 0; word-break: break-all;">{safe_value}</td></tr>')
        return ''.join(rows)

    def make_section_html(title, items):
        section = f'<tr><td colspan="2" style="color: #c9cbcf; font-weight: bold; font-size: 13px; padding: 8px 0 4px 0; border-bottom: 1px solid #45475a;">{html_mod.escape(title)}</td></tr>'
        section += make_rows(items)
        return section

    all_sections = []
    for title, items in categories:
        all_sections.append(make_section_html(title, items))

    html = f"""
    <table style="border-collapse: collapse; width: 100%; font-family: Consolas, 'Courier New', monospace; font-size: 12px;">
        {''.join(all_sections)}
    </table>
    """
    return html
