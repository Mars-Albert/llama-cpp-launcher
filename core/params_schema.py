# -*- coding: utf-8 -*-
"""C1: single source of truth for every llama-server parameter.

Each parameter the launcher can set appears exactly once in PARAMS below,
and the four layers that used to be hand-synced are all derived from it:

  * core/defaults.py      — _FALLBACK_DEFAULTS + the three --help flag maps
  * ui/command_builder.py — CLI argument emission (order = PARAMS order)
  * ui/advanced_panel.py  — the 7-tab UI, get_values() / set_values()
  * tests                 — coverage + i18n checks (tests/test_params_schema.py)

Adding a parameter is one P(...) line. The coverage tests fail if the new
key is missing from any layer.

Field reference
---------------
key           params-dict key (MainWindow.params / presets use the same names)
tab           UI tab: model | context | sampling | gpu | spec | server |
              agent | chat | advanced
row           0-based row inside the tab (None = no UI row, e.g. prio_batch)
label         Chinese label literal (i18n source, t()-ed by the panel); None
              for row-less params
wattr         AdvancedPanel attribute name (adv_*); None when there is no
              widget
widget        text | password | spin | dspin | check | combo | combo_edit |
              combo_index | file | dir | dir_text | list | checklist | mtext
default       fallback default value (see fallback_defaults())
emit          how CommandBuilder emits it:
              diff | diff_pos | diff_ge0 | diff_nonempty | diff_skip |
              diff_join | bool_pos | bool_neg | truthy | prio | index |
              ngl | ngl_draft | none | extra
fmt           value formatting when a flag is emitted: str | int | f2 | join
flag          CLI flag; a (neg, pos) tuple for emit=bool_neg
skip_values   values that suppress emission with emit=diff_skip
flags         --help aliases used when parsing `llama-server --help`
parser        --help value parser: int | float | str | prio
min / max     spin / dspin range (max also for spin)
step          dspin single step
items         combo items (Chinese-source literals, t()-ed at build time);
              a constant list (CACHE_TYPE_ITEMS, ...) is allowed
curtext       combo initial selection by text (omit -> first item)
curidx        combo initial selection by index (omit -> 0)
placeholder   QLineEdit / QPlainTextEdit placeholder (i18n source)
echo          password field (QLineEdit.Password)
tooltip       widget tooltip (i18n source)
browse        file | dir — opens a file/dir dialog
filter_str    Qt file-dialog filter (plain English literal, NOT t()-ed)
browse_title  dialog title (i18n source)
list_title    list-row caption (i18n source; LoRA / control-vector rows)
list_filter   list-row dialog filter (i18n source)
value         value-kind hint for get/set_values:
              list | join | checklist | index | ngl | ngl_edit | combo_edit |
              text
"""
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .constants import MAIN_GPU_MAX  # noqa: F401  (referenced by PARAMS)
from .i18n import t  # noqa: F401  (applied by consumers, not at import time)

# Shared combo item lists (English literals — t() passes them through)
CACHE_TYPE_ITEMS = ["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"]
SPEC_TYPE_ITEMS = ["none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash", "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache"]
LOAD_MODE_ITEMS = ["auto", "none", "mmap", "mlock", "mmap+mlock", "dio"]
DRAFT_PRIO_ITEMS = ["normal", "medium", "high", "realtime"]


@dataclass(frozen=True)
class Param:
    key: str
    tab: str
    row: Optional[int]
    label: Optional[str]
    wattr: Optional[str]
    widget: Optional[str]
    default: Any
    emit: str
    fmt: Optional[str] = None
    flag: Any = None  # str, or (neg, pos) for emit=bool_neg
    skip_values: tuple = ()
    flags: tuple = ()
    parser: str = "bool"
    min: Optional[int] = None
    max: Optional[int] = None
    step: Optional[float] = None
    items: Optional[tuple] = None
    curtext: Optional[str] = None
    curidx: Optional[int] = None
    placeholder: Optional[str] = None
    echo: bool = False
    tooltip: Optional[str] = None
    browse: Optional[str] = None
    filter_str: Optional[str] = None
    browse_title: Optional[str] = None
    list_title: Optional[str] = None
    list_filter: Optional[str] = None
    value: Optional[str] = None


P = Param

# ---------------------------------------------------------------------------
# Parameter table (emit order = CommandBuilder argument order; UI order
# comes from tab + row).
# ---------------------------------------------------------------------------
PARAMS = (
    # ---------- model (tab=model) ----------
    P(key='model', tab='model', row=0, label='模型 (--model)', wattr='adv_model', widget='file', default='', emit='truthy', fmt='str', flag='-m', parser='bool', placeholder="选择或输入模型文件路径", browse='file', filter_str='GGUF Files (*.gguf)', browse_title="选择模型"),
    P(key='alias', tab='model', row=1, label='别名 (--alias)', wattr='adv_alias', widget='text', default='', emit='truthy', fmt='str', flag='--alias', flags=('-a', '--alias'), parser='str', placeholder="模型的自定义名称"),
    P(key='tags', tab='model', row=2, label='标签 (--tags)', wattr='adv_tags', widget='text', default='', emit='truthy', fmt='str', flag='--tags', flags=('--tags',), parser='str', placeholder="逗号分隔的标签列表"),
    P(key='hf_repo', tab='model', row=3, label='HF仓库 (--hf-repo):', wattr='adv_hf_repo', widget='text', default='', emit='truthy', fmt='str', flag='--hf-repo', flags=('-hf', '-hfr', '--hf-repo'), parser='str', placeholder="ggml-org/GLM-4.7-Flash-GGUF:Q4_K_M"),
    P(key='hf_file', tab='model', row=4, label='HF文件 (--hf-file):', wattr='adv_hf_file', widget='text', default='', emit='truthy', fmt='str', flag='--hf-file', flags=('-hff', '--hf-file'), parser='str'),
    P(key='hf_token', tab='model', row=5, label='HF令牌 (--hf-token):', wattr='adv_hf_token', widget='password', default='', emit='truthy', fmt='str', flag='--hf-token', flags=('-hft', '--hf-token'), parser='str', echo=True),
    P(key='model_url', tab='model', row=6, label='模型URL (--model-url):', wattr='adv_model_url', widget='text', default='', emit='truthy', fmt='str', flag='--model-url', flags=('-mu', '--model-url'), parser='str'),
    P(key='docker_repo', tab='model', row=7, label='Docker仓库 (--docker-repo):', wattr='adv_docker_repo', widget='text', default='', emit='truthy', fmt='str', flag='--docker-repo', flags=('-dr', '--docker-repo'), parser='str', placeholder="ai/<model>[:quant]"),
    P(key='lora', tab='model', row=8, label='LoRA 适配器 (--lora)', wattr='adv_lora_list', widget='list', default=[], emit='truthy', fmt='join', flag='--lora', parser='bool', list_title="LoRA 适配器", list_filter="选择LoRA文件", value='list'),
    P(key='lora_scaled', tab='model', row=9, label='LoRA 缩放 (--lora-scaled)', wattr='adv_lora_scaled', widget='text', default=[], emit='truthy', fmt='join', flag='--lora-scaled', flags=('--lora-scaled',), parser='str', placeholder="1.0, 0.5, ...", value='join'),
    P(key='lora_init_without_apply', tab='model', row=10, label='LoRA延迟应用 (--lora-init-without-apply):', wattr='adv_lora_init_without_apply', widget='check', default=False, emit='bool_pos', flag='--lora-init-without-apply', flags=('--lora-init-without-apply',), parser='bool'),
    P(key='control_vector', tab='model', row=11, label='控制向量 (--control-vector)', wattr='adv_cv_list', widget='list', default=[], emit='truthy', fmt='join', flag='--control-vector', parser='bool', list_title="控制向量", list_filter="选择控制向量文件", value='list'),
    P(key='control_vector_scaled', tab='model', row=12, label='控制向量缩放 (--control-vector-scaled)', wattr='adv_cv_scaled', widget='text', default=[], emit='truthy', fmt='join', flag='--control-vector-scaled', flags=('--control-vector-scaled',), parser='str', placeholder="path:scale, ...", value='join'),
    P(key='control_vector_layer_range', tab='model', row=13, label='控制向量层范围 (--control-vector-layer-range)', wattr='adv_cv_layer_range', widget='text', default='', emit='truthy', fmt='str', flag='--control-vector-layer-range', flags=('--control-vector-layer-range',), parser='str', placeholder="START END"),
    P(key='mmproj', tab='model', row=14, label='视觉投影 (--mmproj)', wattr='adv_mmproj', widget='file', default='', emit='truthy', fmt='str', flag='--mmproj', parser='bool', placeholder="选择或输入视觉投影模型路径", browse='file', filter_str='GGUF Files (*.gguf)', browse_title="选择MMProj"),
    P(key='mmproj_url', tab='model', row=15, label='MMProj URL (--mmproj-url):', wattr='adv_mmproj_url', widget='text', default='', emit='truthy', fmt='str', flag='--mmproj-url', flags=('-mmu', '--mmproj-url'), parser='str'),
    P(key='mmproj_auto', tab='model', row=16, label='自动MMProj (--mmproj-auto):', wattr='adv_mmproj_auto', widget='check', default=True, emit='bool_neg', flag=['--mmproj-auto', '--no-mmproj-auto'], flags=('--no-mmproj', '--no-mmproj-auto'), parser='bool'),
    P(key='mmproj_offload', tab='model', row=17, label='MMProj GPU卸载 (--mmproj-offload):', wattr='adv_mmproj_offload', widget='check', default=True, emit='bool_neg', flag=['--mmproj-offload', '--no-mmproj-offload'], flags=('--no-mmproj-offload',), parser='bool'),
    P(key='image_min_tokens', tab='model', row=18, label='图像最小Token (--image-min-tokens):', wattr='adv_image_min_tokens', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--image-min-tokens', flags=('--image-min-tokens',), parser='int', min=0, max=999999, tooltip="0=使用模型默认"),
    P(key='image_max_tokens', tab='model', row=19, label='图像最大Token (--image-max-tokens):', wattr='adv_image_max_tokens', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--image-max-tokens', flags=('--image-max-tokens',), parser='int', min=0, max=999999, tooltip="0=使用模型默认"),
    P(key='mtmd_batch_max_tokens', tab='model', row=20, label='MTMD批Token (--mtmd-batch-max-tokens):', wattr='adv_mtmd_batch_tokens', widget='spin', default=1024, emit='diff', fmt='int', flag='--mtmd-batch-max-tokens', flags=('--mtmd-batch-max-tokens',), parser='int', min=0, max=99999),
    # ---------- context (tab=context) ----------
    P(key='ctx_size', tab='context', row=0, label='上下文大小 (--ctx-size):', wattr='adv_ctx_size', widget='spin', default=0, emit='diff_pos', fmt='int', flag='-c', flags=('-c', '--ctx-size'), parser='int', min=0, max=999999, tooltip="0=使用模型默认"),
    P(key='n_predict', tab='context', row=1, label='预测Token数 (--n-predict):', wattr='adv_n_predict', widget='spin', default=-1, emit='diff', fmt='int', flag='-n', flags=('-n', '--predict', '--n-predict'), parser='int', min=-1, max=999999),
    P(key='keep', tab='context', row=2, label='保留历史 (--keep):', wattr='adv_keep', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--keep', flags=('--keep',), parser='int', min=0, max=999999),
    P(key='batch_size', tab='context', row=3, label='批处理大小 (--batch-size):', wattr='adv_batch_size', widget='spin', default=2048, emit='diff_pos', fmt='int', flag='-b', flags=('-b', '--batch-size'), parser='int', min=64, max=16384),
    P(key='ubatch_size', tab='context', row=4, label='物理批处理 (--ubatch-size):', wattr='adv_ubatch_size', widget='spin', default=512, emit='diff_pos', fmt='int', flag='-ub', flags=('-ub', '--ubatch-size'), parser='int', min=32, max=4096),
    P(key='cache_prompt', tab='context', row=5, label='提示词缓存 (--cache-prompt):', wattr='adv_cache_prompt', widget='check', default=True, emit='bool_neg', flag=['--cache-prompt', '--no-cache-prompt'], flags=('--no-cache-prompt',), parser='bool'),
    P(key='cache_reuse', tab='context', row=6, label='缓存复用 (--cache-reuse):', wattr='adv_cache_reuse', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--cache-reuse', flags=('--cache-reuse',), parser='int', min=0, max=999999),
    P(key='cache_ram', tab='context', row=7, label='缓存RAM (--cache-ram):', wattr='adv_cache_ram', widget='spin', default=8192, emit='diff', fmt='int', flag='--cache-ram', flags=('-cram', '--cache-ram'), parser='int', min=-1, max=999999),
    P(key='cache_idle_slots', tab='context', row=8, label='空闲槽位缓存 (--cache-idle-slots):', wattr='adv_cache_idle_slots', widget='check', default=True, emit='bool_neg', flag=['--cache-idle-slots', '--no-cache-idle-slots'], flags=('--no-cache-idle-slots',), parser='bool'),
    P(key='context_shift', tab='context', row=9, label='上下文偏移 (--context-shift):', wattr='adv_context_shift', widget='check', default=False, emit='bool_pos', flag='--context-shift', flags=('--context-shift',), parser='bool'),
    P(key='defrag_thold', tab='context', row=10, label='KV整理阈值 (--defrag-thold):', wattr='adv_defrag_thold', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--defrag-thold', flags=('-dt', '--defrag-thold'), parser='float', min=0, max=999999, tooltip="(DEPRECATED) KV cache defragmentation threshold"),
    P(key='ctx_checkpoints', tab='context', row=11, label='上下文检查点 (--ctx-checkpoints):', wattr='adv_ctx_checkpoints', widget='spin', default=32, emit='diff', fmt='int', flag='-ctxcp', flags=('-ctxcp', '--ctx-checkpoints', '--swa-checkpoints'), parser='int', min=1, max=256),
    P(key='checkpoint_min_step', tab='context', row=12, label='每N Token检查点 (--checkpoint-min-step):', wattr='adv_checkpoint_min_step', widget='spin', default=8192, emit='diff', fmt='int', flag='-cms', flags=('-cms', '--checkpoint-min-step'), parser='int', min=-1, max=999999),
    P(key='kv_offload', tab='context', row=13, label='KV卸载 (--kv-offload):', wattr='adv_kv_offload', widget='check', default=True, emit='bool_neg', flag=['--kv-offload', '--no-kv-offload'], flags=('-nkvo', '--no-kv-offload'), parser='bool'),
    P(key='kv_unified', tab='context', row=14, label='统一KV (--kv-unified):', wattr='adv_kv_unified', widget='check', default=True, emit='bool_neg', flag=['--kv-unified', '--no-kv-unified'], flags=('-no-kvu', '--no-kv-unified'), parser='bool'),
    P(key='cache_type_k', tab='context', row=15, label='KV Cache K类型 (--cache-type-k):', wattr='adv_cache_type_k', widget='combo', default='f16', emit='diff', fmt='str', flag='-ctk', flags=('-ctk', '--cache-type-k'), parser='str', items=CACHE_TYPE_ITEMS, curtext="f16"),
    P(key='cache_type_v', tab='context', row=16, label='KV Cache V类型 (--cache-type-v):', wattr='adv_cache_type_v', widget='combo', default='f16', emit='diff', fmt='str', flag='-ctv', flags=('-ctv', '--cache-type-v'), parser='str', items=CACHE_TYPE_ITEMS, curtext="f16"),
    P(key='swa_full', tab='context', row=17, label='SWA完整模式 (--swa-full):', wattr='adv_swa_full', widget='check', default=False, emit='bool_pos', flag='--swa-full', flags=('--swa-full',), parser='bool'),
    P(key='rope_scaling', tab='context', row=18, label='RoPE缩放 (--rope-scaling):', wattr='adv_rope_scaling', widget='combo', default='linear', emit='diff_skip', fmt='str', flag='--rope-scaling', skip_values=('none',), flags=('--rope-scaling',), parser='str', items=["none", "linear", "yarn"]),
    P(key='rope_scale', tab='context', row=19, label='RoPE缩放因子 (--rope-scale):', wattr='adv_rope_scale', widget='dspin', default=0, emit='diff_pos', fmt='str', flag='--rope-scale', flags=('--rope-scale',), parser='float', min=0, max=100, step=0.1),
    P(key='rope_freq_base', tab='context', row=20, label='RoPE频率基 (--rope-freq-base):', wattr='adv_rope_freq_base', widget='dspin', default=0, emit='diff_pos', fmt='str', flag='--rope-freq-base', flags=('--rope-freq-base',), parser='float', min=0, max=999999),
    P(key='rope_freq_scale', tab='context', row=21, label='RoPE频率缩放 (--rope-freq-scale):', wattr='adv_rope_freq_scale', widget='dspin', default=0, emit='diff_pos', fmt='str', flag='--rope-freq-scale', flags=('--rope-freq-scale',), parser='float', min=0, max=10, step=0.1),
    P(key='yarn_orig_ctx', tab='context', row=22, label='YaRN原始上下文 (--yarn-orig-ctx):', wattr='adv_yarn_orig_ctx', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--yarn-orig-ctx', flags=('--yarn-orig-ctx',), parser='int', min=0, max=999999),
    P(key='yarn_ext_factor', tab='context', row=23, label='YaRN扩展因子 (--yarn-ext-factor):', wattr='adv_yarn_ext', widget='dspin', default=-1.0, emit='diff', fmt='f2', flag='--yarn-ext-factor', flags=('--yarn-ext-factor',), parser='float', min=-1.0, max=1.0, step=0.1),
    P(key='yarn_attn_factor', tab='context', row=24, label='YaRN注意力因子 (--yarn-attn-factor):', wattr='adv_yarn_attn', widget='dspin', default=-1.0, emit='diff', fmt='f2', flag='--yarn-attn-factor', flags=('--yarn-attn-factor',), parser='float', min=-1.0, max=2.0, step=0.1),
    P(key='yarn_beta_slow', tab='context', row=25, label='YaRN Beta慢 (--yarn-beta-slow):', wattr='adv_yarn_beta_slow', widget='dspin', default=-1.0, emit='diff', fmt='f2', flag='--yarn-beta-slow', flags=('--yarn-beta-slow',), parser='float', min=-1.0, max=2.0, step=0.1),
    P(key='yarn_beta_fast', tab='context', row=26, label='YaRN Beta快 (--yarn-beta-fast):', wattr='adv_yarn_beta_fast', widget='dspin', default=-1.0, emit='diff', fmt='f2', flag='--yarn-beta-fast', flags=('--yarn-beta-fast',), parser='float', min=-1.0, max=2.0, step=0.1),
    # ---------- sampling (tab=sampling) ----------
    P(key='temp', tab='sampling', row=0, label='温度 (--temp):', wattr='adv_temp', widget='dspin', default=0.8, emit='diff', fmt='f2', flag='--temp', flags=('--temp', '--temperature'), parser='float', min=0, max=2.0, step=0.05),
    P(key='top_k', tab='sampling', row=1, label='Top-K (--top-k):', wattr='adv_top_k', widget='spin', default=40, emit='diff', fmt='int', flag='--top-k', flags=('--top-k',), parser='int', min=0, max=200),
    P(key='top_p', tab='sampling', row=2, label='Top-P (--top-p):', wattr='adv_top_p', widget='dspin', default=0.95, emit='diff', fmt='f2', flag='--top-p', flags=('--top-p',), parser='float', min=0, max=1.0, step=0.05),
    P(key='min_p', tab='sampling', row=3, label='Min-P (--min-p):', wattr='adv_min_p', widget='dspin', default=0.05, emit='diff', fmt='f2', flag='--min-p', flags=('--min-p',), parser='float', min=0, max=1.0, step=0.05),
    P(key='typical_p', tab='sampling', row=4, label='Typical-P (--typical-p):', wattr='adv_typical_p', widget='dspin', default=1.0, emit='diff', fmt='f2', flag='--typical-p', flags=('--typical', '--typical-p'), parser='float', min=0, max=1.0, step=0.05),
    P(key='top_n_sigma', tab='sampling', row=5, label='Top-N-Sigma (--top-n-sigma):', wattr='adv_top_n_sigma', widget='dspin', default=-1.0, emit='diff', fmt='f2', flag='--top-n-sigma', flags=('--top-nsigma', '--top-n-sigma'), parser='float', min=-1.0, max=3.0, step=0.1),
    P(key='xtc_probability', tab='sampling', row=6, label='XTC概率 (--xtc-probability):', wattr='adv_xtc_prob', widget='dspin', default=0.0, emit='diff', fmt='f2', flag='--xtc-probability', flags=('--xtc-probability',), parser='float', min=0, max=1.0, step=0.05),
    P(key='xtc_threshold', tab='sampling', row=7, label='XTC阈值 (--xtc-threshold):', wattr='adv_xtc_thresh', widget='dspin', default=0.1, emit='diff', fmt='f2', flag='--xtc-threshold', flags=('--xtc-threshold',), parser='float', min=0, max=1.0, step=0.05),
    P(key='repeat_penalty', tab='sampling', row=8, label='重复惩罚 (--repeat-penalty):', wattr='adv_repeat_penalty', widget='dspin', default=1.0, emit='diff', fmt='f2', flag='--repeat-penalty', flags=('--repeat-penalty',), parser='float', min=0, max=2.0, step=0.05),
    P(key='presence_penalty', tab='sampling', row=9, label='存在惩罚 (--presence-penalty):', wattr='adv_presence_penalty', widget='dspin', default=0.0, emit='diff', fmt='f2', flag='--presence-penalty', flags=('--presence-penalty',), parser='float', min=-2.0, max=2.0, step=0.1),
    P(key='frequency_penalty', tab='sampling', row=10, label='频率惩罚 (--frequency-penalty):', wattr='adv_freq_penalty', widget='dspin', default=0.0, emit='diff', fmt='f2', flag='--frequency-penalty', flags=('--frequency-penalty',), parser='float', min=-2.0, max=2.0, step=0.1),
    P(key='dry_multiplier', tab='sampling', row=11, label='DRY乘数 (--dry-multiplier):', wattr='adv_dry_mult', widget='dspin', default=0.0, emit='diff', fmt='f2', flag='--dry-multiplier', flags=('--dry-multiplier',), parser='float', min=0, max=2.0, step=0.05),
    P(key='dry_base', tab='sampling', row=12, label='DRY基数 (--dry-base):', wattr='adv_dry_base', widget='dspin', default=1.75, emit='diff', fmt='f2', flag='--dry-base', flags=('--dry-base',), parser='float', min=1.0, max=3.0, step=0.05),
    P(key='dry_allowed_length', tab='sampling', row=13, label='DRY允许长度 (--dry-allowed-length):', wattr='adv_dry_len', widget='spin', default=2, emit='diff', fmt='int', flag='--dry-allowed-length', flags=('--dry-allowed-length',), parser='int', min=1, max=64),
    P(key='dry_penalty_last_n', tab='sampling', row=14, label='DRY惩罚最后N (--dry-penalty-last-n):', wattr='adv_dry_penalty_last_n', widget='spin', default=64, emit='diff', fmt='int', flag='--dry-penalty-last-n', flags=('--dry-penalty-last-n',), parser='int', min=-1, max=999999),
    P(key='dry_sequence_breaker', tab='sampling', row=15, label='DRY序列分隔符 (--dry-sequence-breaker):', wattr='adv_dry_seq_breaker', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--dry-sequence-breaker', flags=('--dry-sequence-breaker',), parser='str', placeholder="\\n, :, \", *; 'none' = 不设分隔符"),
    P(key='adaptive_target', tab='sampling', row=16, label='自适应目标 (--adaptive-target):', wattr='adv_adaptive_target', widget='dspin', default=-1.0, emit='diff_ge0', fmt='f2', flag='--adaptive-target', flags=('--adaptive-target',), parser='float', min=-1.0, max=1.0, step=0.05),
    P(key='adaptive_decay', tab='sampling', row=17, label='自适应衰减 (--adaptive-decay):', wattr='adv_adaptive_decay', widget='dspin', default=0.9, emit='diff_ge0', fmt='f2', flag='--adaptive-decay', flags=('--adaptive-decay',), parser='float', min=0.0, max=0.99, step=0.05),
    P(key='repeat_last_n', tab='sampling', row=18, label='重复最后N (--repeat-last-n):', wattr='adv_repeat_last_n', widget='spin', default=64, emit='diff', fmt='int', flag='--repeat-last-n', flags=('--repeat-last-n',), parser='int', min=-1, max=999999),
    P(key='seed', tab='sampling', row=19, label='随机种子 (--seed):', wattr='adv_seed', widget='spin', default=-1, emit='diff', fmt='int', flag='-s', flags=('-s', '--seed'), parser='int', min=-1, max=999999999),
    P(key='mirostat', tab='sampling', row=20, label='Mirostat (--mirostat):', wattr='adv_mirostat', widget='combo_index', default=0, emit='index', flag='--mirostat', flags=('--mirostat',), parser='int', items=("禁用 (0)", "Mirostat (1)", "Mirostat 2.0 (2)"), value='index'),
    P(key='mirostat_lr', tab='sampling', row=21, label='Mirostat学习率 (--mirostat-lr):', wattr='adv_mirostat_lr', widget='dspin', default=0.1, emit='diff', fmt='f2', flag='--mirostat-lr', flags=('--mirostat-lr',), parser='float', min=0, max=1.0, step=0.01),
    P(key='mirostat_ent', tab='sampling', row=22, label='Mirostat熵 (--mirostat-ent):', wattr='adv_mirostat_ent', widget='dspin', default=5.0, emit='diff', fmt='f2', flag='--mirostat-ent', flags=('--mirostat-ent',), parser='float', min=0, max=10.0, step=0.1),
    P(key='dynatemp_range', tab='sampling', row=23, label='动态温度范围 (--dynatemp-range):', wattr='adv_dynatemp_range', widget='dspin', default=0.0, emit='diff', fmt='f2', flag='--dynatemp-range', flags=('--dynatemp-range',), parser='float', min=0, max=2.0, step=0.05),
    P(key='dynatemp_exp', tab='sampling', row=24, label='动态温度指数 (--dynatemp-exp):', wattr='adv_dynatemp_exp', widget='dspin', default=1.0, emit='diff', fmt='f2', flag='--dynatemp-exp', flags=('--dynatemp-exp',), parser='float', min=0.1, max=5.0, step=0.1),
    P(key='ignore_eos', tab='sampling', row=25, label='忽略EOS (--ignore-eos):', wattr='adv_ignore_eos', widget='check', default=False, emit='bool_pos', flag='--ignore-eos', flags=('--ignore-eos',), parser='bool'),
    P(key='backend_sampling', tab='sampling', row=26, label='后端采样 (--backend-sampling):', wattr='adv_backend_sampling', widget='check', default=False, emit='bool_pos', flag='--backend-sampling', flags=('-bs', '--backend-sampling'), parser='bool'),
    P(key='samplers', tab='sampling', row=27, label='采样器顺序 (--samplers):', wattr='adv_samplers', widget='text', default='penalties;dry;top_n_sigma;top_k;typ_p;top_p;min_p;xtc;temperature', emit='diff_nonempty', fmt='str', flag='--samplers', flags=('--samplers',), parser='str'),
    P(key='sampler_seq', tab='sampling', row=28, label='采样器序列 (--sampling-seq):', wattr='adv_sampler_seq', widget='text', default='edskypmxt', emit='diff_nonempty', fmt='str', flag='--sampling-seq', flags=('--sampler-seq', '--sampling-seq'), parser='str', placeholder="简化采样器序列"),
    P(key='logit_bias', tab='sampling', row=29, label='Logit偏置 (--logit-bias):', wattr='adv_logit_bias', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--logit-bias', flags=('-l', '--logit-bias'), parser='str', placeholder="TOKEN_ID(+/-)BIAS"),
    P(key='grammar', tab='sampling', row=30, label='Grammar (--grammar):', wattr='adv_grammar', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--grammar', flags=('--grammar',), parser='str', browse='file', filter_str="GBNF Files (*.gbnf)"),
    P(key='grammar_file', tab='sampling', row=31, label='Grammar文件 (--grammar-file):', wattr='adv_grammar_file', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--grammar-file', flags=('--grammar-file',), parser='str', browse='file', filter_str="All Files (*)"),
    P(key='json_schema', tab='sampling', row=32, label='JSON Schema (--json-schema):', wattr='adv_json_schema', widget='mtext', default='', emit='diff_nonempty', fmt='str', flag='--json-schema', flags=('-j', '--json-schema'), parser='str', placeholder="JSON Schema"),
    P(key='json_schema_file', tab='sampling', row=33, label='JSON Schema文件 (--json-schema-file):', wattr='adv_json_schema_file', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--json-schema-file', flags=('-jf', '--json-schema-file'), parser='str', browse='file', filter_str="JSON Files (*.json)"),
    # ---------- gpu (tab=gpu) ----------
    P(key='n_gpu_layers', tab='gpu', row=0, label='GPU层数 (--n-gpu-layers):', wattr='adv_ngl', widget='combo_edit', default='auto', emit='ngl', flag='-ngl', flags=('-ngl', '--gpu-layers', '--n-gpu-layers'), parser='str', items=["auto", "all"], value='ngl'),
    P(key='device', tab='gpu', row=1, label='设备 (--device):', wattr='adv_device', widget='text', default='', emit='diff_nonempty', fmt='str', flag='-dev', flags=('-dev', '--device'), parser='str'),
    P(key='load_mode', tab='gpu', row=2, label='加载模式 (--load-mode):', wattr='adv_load_mode', widget='combo_edit', default='auto', emit='diff_nonempty', fmt='str', flag='--load-mode', flags=('-lm', '--load-mode'), parser='str', items=LOAD_MODE_ITEMS, curtext="auto"),
    P(key='split_mode', tab='gpu', row=3, label='分割模式 (--split-mode):', wattr='adv_split_mode', widget='combo', default='layer', emit='diff_nonempty', fmt='str', flag='-sm', flags=('-sm', '--split-mode'), parser='str', items=["layer", "none", "row", "tensor"]),
    P(key='tensor_split', tab='gpu', row=4, label='张量分割 (--tensor-split):', wattr='adv_tensor_split', widget='text', default='', emit='diff_nonempty', fmt='str', flag='-ts', flags=('-ts', '--tensor-split'), parser='str'),
    P(key='main_gpu', tab='gpu', row=6, label='主GPU (--main-gpu):', wattr='adv_main_gpu', widget='spin', default=0, emit='diff', fmt='int', flag='-mg', flags=('-mg', '--main-gpu'), parser='int', min=0, max=MAIN_GPU_MAX),
    P(key='flash_attn', tab='gpu', row=7, label='Flash Attention (--flash-attn):', wattr='adv_flash_attn', widget='combo', default='auto', emit='diff', fmt='str', flag='--flash-attn', flags=('-fa', '--flash-attn'), parser='str', items=["on", "off", "auto"], curtext="auto"),
    P(key='op_offload', tab='gpu', row=8, label='算子卸载 (--op-offload):', wattr='adv_op_offload', widget='check', default=True, emit='bool_neg', flag=['--op-offload', '--no-op-offload'], flags=('--no-op-offload',), parser='bool'),
    P(key='cpu_moe', tab='gpu', row=9, label='CPU MoE (--cpu-moe):', wattr='adv_cpu_moe', widget='check', default=False, emit='bool_pos', flag='--cpu-moe', flags=('--cpu-moe',), parser='bool'),
    P(key='n_cpu_moe', tab='gpu', row=10, label='CPU MoE层数 (--n-cpu-moe):', wattr='adv_n_cpu_moe', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--n-cpu-moe', flags=('-ncmoe', '--n-cpu-moe'), parser='int', min=0, max=999),
    P(key='mmap', tab='gpu', row=11, label='内存映射 (--mmap):', wattr='adv_mmap', widget='check', default=True, emit='bool_neg', flag=['--mmap', '--no-mmap'], flags=('--no-mmap',), parser='bool'),
    P(key='mlock', tab='gpu', row=12, label='内存锁定 (--mlock):', wattr='adv_mlock', widget='check', default=False, emit='bool_pos', flag='--mlock', flags=('--mlock',), parser='bool'),
    P(key='no_host', tab='gpu', row=13, label='无主机内存 (--no-host):', wattr='adv_no_host', widget='check', default=False, emit='bool_pos', flag='--no-host', flags=('--no-host',), parser='bool'),
    P(key='repack', tab='gpu', row=14, label='重打包 (--repack):', wattr='adv_repack', widget='check', default=True, emit='bool_neg', flag=['--repack', '--no-repack'], flags=('-nr', '--no-repack'), parser='bool'),
    P(key='direct_io', tab='gpu', row=15, label='直接IO (--direct-io):', wattr='adv_direct_io', widget='check', default=False, emit='bool_pos', flag='--direct-io', flags=('--direct-io',), parser='bool'),
    P(key='fit', tab='gpu', row=16, label='适配内存 (--fit):', wattr='adv_fit', widget='combo', default='on', emit='diff', fmt='str', flag='--fit', flags=('-fit', '--fit'), parser='str', items=["on", "off"], curtext="on"),
    P(key='fit_target', tab='gpu', row=17, label='适配目标MiB (--fit-target):', wattr='adv_fit_target', widget='text', default='1024', emit='diff', fmt='int', flag='-fitt', flags=('-fitt', '--fit-target'), parser='str', placeholder="1024, 2048, ..."),
    P(key='fit_ctx', tab='gpu', row=18, label='适配最小上下文 (--fit-ctx):', wattr='adv_fit_ctx', widget='spin', default=4096, emit='diff', fmt='int', flag='--fit-ctx', flags=('-fitc', '--fit-ctx'), parser='int', min=256, max=999999),
    P(key='check_tensors', tab='gpu', row=19, label='检查张量 (--check-tensors):', wattr='adv_check_tensors', widget='check', default=False, emit='bool_pos', flag='--check-tensors', flags=('--check-tensors',), parser='bool'),
    P(key='override_tensor', tab='gpu', row=20, label='覆盖张量 (--override-tensor):', wattr='adv_override_tensor', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--override-tensor', flags=('-ot', '--override-tensor'), parser='str', placeholder="tensor_name=type,..."),
    P(key='override_kv', tab='gpu', row=21, label='覆盖KV (--override-kv):', wattr='adv_override_kv', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--override-kv', flags=('--override-kv',), parser='str', placeholder="KEY=TYPE:VALUE,..."),
    P(key='warmup', tab='gpu', row=22, label='预热 (--warmup):', wattr='adv_warmup', widget='check', default=True, emit='bool_neg', flag=['--warmup', '--no-warmup'], flags=('--no-warmup',), parser='bool'),
    P(key='rpc', tab='gpu', row=23, label='RPC服务器 (--rpc):', wattr='adv_rpc', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--rpc', flags=('--rpc',), parser='str', placeholder="host:port,host:port"),
    P(key='threads', tab='gpu', row=24, label='线程数 (--threads):', wattr='adv_threads', widget='spin', default=-1, emit='diff', fmt='int', flag='-t', flags=('-t', '--threads'), parser='int', min=-1, max=256),
    P(key='threads_batch', tab='gpu', row=25, label='批处理线程 (--threads-batch):', wattr='adv_threads_batch', widget='spin', default=-1, emit='diff', fmt='int', flag='-tb', flags=('-tb', '--threads-batch'), parser='int', min=-1, max=256),
    P(key='cpu_mask', tab='gpu', row=26, label='CPU掩码 (--cpu-mask):', wattr='adv_cpu_mask', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--cpu-mask', flags=('-C', '--cpu-mask'), parser='str'),
    P(key='cpu_range', tab='gpu', row=27, label='CPU范围 (--cpu-range):', wattr='adv_cpu_range', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--cpu-range', flags=('-Cr', '--cpu-range'), parser='str', placeholder="lo-hi"),
    P(key='cpu_strict', tab='gpu', row=28, label='严格CPU (--cpu-strict):', wattr='adv_cpu_strict', widget='spin', default=0, emit='diff', fmt='int', flag='--cpu-strict', flags=('--cpu-strict',), parser='int', min=0, max=1),
    P(key='cpu_mask_batch', tab='gpu', row=29, label='批CPU掩码 (--cpu-mask-batch):', wattr='adv_cpu_mask_batch', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--cpu-mask-batch', flags=('-Cb', '--cpu-mask-batch'), parser='str'),
    P(key='cpu_range_batch', tab='gpu', row=30, label='批CPU范围 (--cpu-range-batch):', wattr='adv_cpu_range_batch', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--cpu-range-batch', flags=('-Crb', '--cpu-range-batch'), parser='str', placeholder="lo-hi"),
    P(key='cpu_strict_batch', tab='gpu', row=31, label='批严格CPU (--cpu-strict-batch):', wattr='adv_cpu_strict_batch', widget='spin', default=0, emit='diff', fmt='int', flag='--cpu-strict-batch', flags=('--cpu-strict-batch',), parser='int', min=0, max=1),
    P(key='poll', tab='gpu', row=32, label='轮询级别 (--poll):', wattr='adv_poll', widget='spin', default=50, emit='diff', fmt='int', flag='--poll', flags=('--poll',), parser='int', min=0, max=100),
    P(key='poll_batch', tab='gpu', row=33, label='批轮询 (--poll-batch):', wattr='adv_poll_batch', widget='spin', default=50, emit='diff', fmt='int', flag='--poll-batch', flags=('--poll-batch',), parser='int', min=0, max=100),
    P(key='prio', tab='gpu', row=34, label='优先级 (--prio):', wattr='adv_prio', widget='combo', default='normal', emit='prio', flag='--prio', flags=('--prio',), parser='prio', items=["low", "normal", "medium", "high", "realtime"], curtext="normal"),
    P(key='prio_batch', tab='gpu', row=None, label=None, wattr=None, widget=None, default='normal', emit='prio', flag='--prio-batch', flags=('--prio-batch',), parser='prio'),
    P(key='numa', tab='gpu', row=35, label='NUMA (--numa):', wattr='adv_numa', widget='combo', default='disable', emit='diff_skip', fmt='str', flag='--numa', skip_values=('disable',), flags=('--numa',), parser='str', items=["disable", "distribute", "isolate", "numactl"]),
    P(key='perf', tab='gpu', row=36, label='性能统计 (--perf):', wattr='adv_perf', widget='check', default=False, emit='bool_pos', flag='--perf', flags=('--perf',), parser='bool'),
    # ---------- spec (tab=spec) ----------
    P(key='spec_type', tab='spec', row=0, label='投机类型 (--spec-type):', wattr='adv_spec_type', widget='combo', default='none', emit='diff_skip', fmt='str', flag='--spec-type', skip_values=('none',), flags=('--spec-type',), parser='str', items=SPEC_TYPE_ITEMS),
    P(key='draft_model', tab='spec', row=1, label='草稿模型 (--model-draft):', wattr='adv_draft_model', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--model-draft', flags=('-md', '--model-draft', '--spec-draft-model'), parser='str', browse='file', filter_str="GGUF Files (*.gguf)"),
    P(key='spec_draft_hf', tab='spec', row=2, label='草稿HF仓库 (--spec-draft-hf):', wattr='adv_spec_draft_hf', widget='text', default='', emit='truthy', fmt='str', flag='--spec-draft-hf', flags=('--spec-draft-hf', '-hfd', '-hfrd', '--hf-repo-draft'), parser='str', placeholder="<user>/<model>[:quant]"),
    P(key='n_gpu_layers_draft', tab='spec', row=3, label='草稿GPU层数 (--n-gpu-layers-draft):', wattr='adv_n_gpu_layers_draft', widget='combo_edit', default='auto', emit='ngl_draft', flag='--n-gpu-layers-draft', flags=('-ngld', '--gpu-layers-draft', '--n-gpu-layers-draft', '--spec-draft-ngl'), parser='str', items=["auto", "all"], value='ngl_edit'),
    P(key='device_draft', tab='spec', row=4, label='草稿设备 (--device-draft):', wattr='adv_device_draft', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--device-draft', flags=('-devd', '--device-draft', '--spec-draft-device'), parser='str'),
    P(key='cpu_moe_draft', tab='spec', row=5, label='草稿CPU MoE (--cpu-moe-draft):', wattr='adv_cpu_moe_draft', widget='check', default=False, emit='bool_pos', flag='--cpu-moe-draft', flags=('-cmoed', '--cpu-moe-draft', '--spec-draft-cpu-moe'), parser='bool'),
    P(key='n_cpu_moe_draft', tab='spec', row=6, label='草稿CPU MoE层数 (--n-cpu-moe-draft):', wattr='adv_n_cpu_moe_draft', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--n-cpu-moe-draft', flags=('-ncmoed', '--n-cpu-moe-draft', '--spec-draft-n-cpu-moe', '--spec-draft-ncmoe'), parser='int', min=0, max=999),
    P(key='cache_type_k_draft', tab='spec', row=7, label='草稿KV K类型 (--spec-draft-type-k):', wattr='adv_cache_type_k_draft', widget='combo', default='f16', emit='diff', fmt='str', flag='--cache-type-k-draft', flags=('--spec-draft-type-k', '-ctkd', '--cache-type-k-draft'), parser='str', items=CACHE_TYPE_ITEMS, curtext="f16"),
    P(key='cache_type_v_draft', tab='spec', row=8, label='草稿KV V类型 (--spec-draft-type-v):', wattr='adv_cache_type_v_draft', widget='combo', default='f16', emit='diff', fmt='str', flag='--cache-type-v-draft', flags=('--spec-draft-type-v', '-ctvd', '--cache-type-v-draft'), parser='str', items=CACHE_TYPE_ITEMS, curtext="f16"),
    P(key='override_tensor_draft', tab='spec', row=9, label='草稿张量覆盖 (--spec-draft-override-tensor):', wattr='adv_override_tensor_draft', widget='text', default='', emit='none', flags=('--spec-draft-override-tensor', '-otd'), parser='str', placeholder="tensor_name=type,..."),
    P(key='threads_draft', tab='spec', row=10, label='草稿线程 (--threads-draft):', wattr='adv_threads_draft', widget='spin', default=-1, emit='diff', fmt='int', flag='--threads-draft', flags=('-td', '--threads-draft', '--spec-draft-threads'), parser='int', min=-1, max=256),
    P(key='threads_batch_draft', tab='spec', row=11, label='草稿批处理线程 (--threads-batch-draft):', wattr='adv_threads_batch_draft', widget='spin', default=-1, emit='diff', fmt='int', flag='--threads-batch-draft', flags=('-tbd', '--threads-batch-draft', '--spec-draft-threads-batch'), parser='int', min=-1, max=256),
    P(key='spec_draft_cpu_mask', tab='spec', row=12, label='草稿CPU掩码 (--spec-draft-cpu-mask):', wattr='adv_spec_draft_cpu_mask', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--spec-draft-cpu-mask', flags=('--spec-draft-cpu-mask', '-Cd', '--cpu-mask-draft'), parser='str'),
    P(key='spec_draft_cpu_range', tab='spec', row=13, label='草稿CPU范围 (--spec-draft-cpu-range):', wattr='adv_spec_draft_cpu_range', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--spec-draft-cpu-range', flags=('--spec-draft-cpu-range', '-Crd', '--cpu-range-draft'), parser='str', placeholder="lo-hi"),
    P(key='spec_draft_cpu_strict', tab='spec', row=14, label='草稿严格CPU (--spec-draft-cpu-strict):', wattr='adv_spec_draft_cpu_strict', widget='spin', default=0, emit='diff', fmt='int', flag='--spec-draft-cpu-strict', flags=('--spec-draft-cpu-strict', '--cpu-strict-draft'), parser='int', min=0, max=1),
    P(key='spec_draft_prio', tab='spec', row=15, label='草稿优先级 (--spec-draft-prio):', wattr='adv_spec_draft_prio', widget='combo', default='normal', emit='prio', flag='--spec-draft-prio', flags=('--spec-draft-prio', '--prio-draft'), parser='prio', items=DRAFT_PRIO_ITEMS, curtext="normal"),
    P(key='spec_draft_poll', tab='spec', row=16, label='草稿轮询 (--spec-draft-poll):', wattr='adv_spec_draft_poll', widget='spin', default=50, emit='diff', fmt='int', flag='--spec-draft-poll', flags=('--spec-draft-poll', '--poll-draft'), parser='int', min=0, max=100),
    P(key='spec_draft_cpu_mask_batch', tab='spec', row=17, label='草稿批CPU掩码 (--spec-draft-cpu-mask-batch):', wattr='adv_spec_draft_cpu_mask_batch', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--spec-draft-cpu-mask-batch', flags=('--spec-draft-cpu-mask-batch', '-Cbd', '--cpu-mask-batch-draft'), parser='str'),
    P(key='spec_draft_cpu_strict_batch', tab='spec', row=18, label='草稿批严格CPU (--spec-draft-cpu-strict-batch):', wattr='adv_spec_draft_cpu_strict_batch', widget='spin', default=0, emit='diff', fmt='int', flag='--spec-draft-cpu-strict-batch', flags=('--spec-draft-cpu-strict-batch', '--cpu-strict-batch-draft'), parser='int', min=0, max=1),
    P(key='spec_draft_prio_batch', tab='spec', row=19, label='草稿批优先级 (--spec-draft-prio-batch):', wattr='adv_spec_draft_prio_batch', widget='combo', default='normal', emit='prio', flag='--spec-draft-prio-batch', flags=('--spec-draft-prio-batch', '--prio-batch-draft'), parser='prio', items=DRAFT_PRIO_ITEMS, curtext="normal"),
    P(key='spec_draft_poll_batch', tab='spec', row=20, label='草稿批轮询 (--spec-draft-poll-batch):', wattr='adv_spec_draft_poll_batch', widget='spin', default=50, emit='diff', fmt='int', flag='--spec-draft-poll-batch', flags=('--spec-draft-poll-batch', '--poll-batch-draft'), parser='int', min=0, max=100),
    P(key='draft_max', tab='spec', row=21, label='草稿Token数 (--spec-draft-n-max):', wattr='adv_draft_max', widget='spin', default=3, emit='diff', fmt='int', flag='--spec-draft-n-max', flags=('--spec-draft-n-max',), parser='int', min=1, max=256),
    P(key='draft_min', tab='spec', row=22, label='草稿最小Token (--spec-draft-n-min):', wattr='adv_draft_min', widget='spin', default=0, emit='diff_pos', fmt='int', flag='--spec-draft-n-min', flags=('--spec-draft-n-min',), parser='int', min=0, max=256),
    P(key='draft_p_min', tab='spec', row=23, label='草稿最小概率 (--spec-draft-p-min):', wattr='adv_draft_p_min', widget='dspin', default=0.0, emit='diff', fmt='f2', flag='--spec-draft-p-min', flags=('--spec-draft-p-min', '--draft-p-min'), parser='float', min=0.0, max=1.0, step=0.05),
    P(key='spec_draft_p_split', tab='spec', row=24, label='投机拆分概率 (--spec-draft-p-split):', wattr='adv_spec_draft_p_split', widget='dspin', default=0.1, emit='diff', fmt='f2', flag='--spec-draft-p-split', flags=('--spec-draft-p-split', '--draft-p-split'), parser='float', min=0.0, max=1.0, step=0.05),
    P(key='spec_draft_backend_sampling', tab='spec', row=25, label='草稿后端采样 (--spec-draft-backend-sampling):', wattr='adv_spec_draft_backend_sampling', widget='check', default=True, emit='bool_neg', flag=['--spec-draft-backend-sampling', '--no-spec-draft-backend-sampling'], flags=('--no-spec-draft-backend-sampling',), parser='bool'),
    P(key='spec_ngram_size_n', tab='spec', row=26, label='Ngram大小N (--spec-ngram-simple-size-n):', wattr='adv_spec_ngram_n', widget='spin', default=12, emit='diff', fmt='int', flag='--spec-ngram-simple-size-n', flags=('--spec-ngram-simple-size-n',), parser='int', min=1, max=128),
    P(key='spec_ngram_size_m', tab='spec', row=27, label='Ngram大小M (--spec-ngram-simple-size-m):', wattr='adv_spec_ngram_m', widget='spin', default=48, emit='diff', fmt='int', flag='--spec-ngram-simple-size-m', flags=('--spec-ngram-simple-size-m',), parser='int', min=1, max=256),
    P(key='spec_ngram_min_hits', tab='spec', row=28, label='Ngram最小命中 (--spec-ngram-simple-min-hits):', wattr='adv_spec_ngram_min_hits', widget='spin', default=1, emit='diff', fmt='int', flag='--spec-ngram-simple-min-hits', flags=('--spec-ngram-simple-min-hits',), parser='int', min=1, max=256),
    P(key='spec_ngram_mod_n_min', tab='spec', row=29, label='Ngram-mod最小N (--spec-ngram-mod-n-min):', wattr='adv_spec_ngram_mod_n_min', widget='spin', default=48, emit='diff', fmt='int', flag='--spec-ngram-mod-n-min', flags=('--spec-ngram-mod-n-min',), parser='int', min=0, max=1024),
    P(key='spec_ngram_mod_n_max', tab='spec', row=30, label='Ngram-mod最大N (--spec-ngram-mod-n-max):', wattr='adv_spec_ngram_mod_n_max', widget='spin', default=64, emit='diff', fmt='int', flag='--spec-ngram-mod-n-max', flags=('--spec-ngram-mod-n-max',), parser='int', min=0, max=1024),
    P(key='spec_ngram_mod_n_match', tab='spec', row=31, label='Ngram-mod匹配长度 (--spec-ngram-mod-n-match):', wattr='adv_spec_ngram_mod_n_match', widget='spin', default=24, emit='diff', fmt='int', flag='--spec-ngram-mod-n-match', flags=('--spec-ngram-mod-n-match',), parser='int', min=0, max=1024),
    P(key='spec_ngram_map_k_size_n', tab='spec', row=32, label='Ngram-map-k大小N (--spec-ngram-map-k-size-n):', wattr='adv_spec_ngram_mapk_n', widget='spin', default=12, emit='diff', fmt='int', flag='--spec-ngram-map-k-size-n', flags=('--spec-ngram-map-k-size-n',), parser='int', min=1, max=128),
    P(key='spec_ngram_map_k_size_m', tab='spec', row=33, label='Ngram-map-k大小M (--spec-ngram-map-k-size-m):', wattr='adv_spec_ngram_mapk_m', widget='spin', default=48, emit='diff', fmt='int', flag='--spec-ngram-map-k-size-m', flags=('--spec-ngram-map-k-size-m',), parser='int', min=1, max=256),
    P(key='spec_ngram_map_k_min_hits', tab='spec', row=34, label='Ngram-map-k最小命中 (--spec-ngram-map-k-min-hits):', wattr='adv_spec_ngram_mapk_min_hits', widget='spin', default=1, emit='diff', fmt='int', flag='--spec-ngram-map-k-min-hits', flags=('--spec-ngram-map-k-min-hits',), parser='int', min=1, max=256),
    P(key='spec_ngram_map_k4v_size_n', tab='spec', row=35, label='Ngram-map-k4v大小N (--spec-ngram-map-k4v-size-n):', wattr='adv_spec_ngram_mapk4v_n', widget='spin', default=12, emit='diff', fmt='int', flag='--spec-ngram-map-k4v-size-n', flags=('--spec-ngram-map-k4v-size-n',), parser='int', min=1, max=128),
    P(key='spec_ngram_map_k4v_size_m', tab='spec', row=36, label='Ngram-map-k4v大小M (--spec-ngram-map-k4v-size-m):', wattr='adv_spec_ngram_mapk4v_m', widget='spin', default=48, emit='diff', fmt='int', flag='--spec-ngram-map-k4v-size-m', flags=('--spec-ngram-map-k4v-size-m',), parser='int', min=1, max=256),
    P(key='spec_ngram_map_k4v_min_hits', tab='spec', row=37, label='Ngram-map-k4v最小命中 (--spec-ngram-map-k4v-min-hits):', wattr='adv_spec_ngram_mapk4v_min_hits', widget='spin', default=1, emit='diff', fmt='int', flag='--spec-ngram-map-k4v-min-hits', flags=('--spec-ngram-map-k4v-min-hits',), parser='int', min=1, max=256),
    P(key='lookup_cache_static', tab='spec', row=38, label='静态查找缓存 (--lookup-cache-static):', wattr='adv_lookup_static', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--lookup-cache-static', flags=('-lcs', '--lookup-cache-static'), parser='str', browse='file', filter_str="All Files (*)"),
    P(key='lookup_cache_dynamic', tab='spec', row=39, label='动态查找缓存 (--lookup-cache-dynamic):', wattr='adv_lookup_dynamic', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--lookup-cache-dynamic', flags=('-lcd', '--lookup-cache-dynamic'), parser='str', browse='file', filter_str="All Files (*)"),
    # ---------- server (tab=server) ----------
    P(key='host', tab='server', row=0, label='主机 (--host):', wattr='adv_host', widget='text', default='127.0.0.1', emit='diff', fmt='str', flag='--host', flags=('--host',), parser='str'),
    P(key='port', tab='server', row=1, label='端口 (--port):', wattr='adv_port', widget='spin', default=8080, emit='diff', fmt='int', flag='--port', flags=('--port',), parser='int', min=1, max=65535),
    P(key='reuse_port', tab='server', row=2, label='复用端口 (--reuse-port):', wattr='adv_reuse_port', widget='check', default=False, emit='bool_pos', flag='--reuse-port', flags=('--reuse-port',), parser='bool'),
    P(key='api_prefix', tab='server', row=3, label='API前缀 (--api-prefix):', wattr='adv_api_prefix', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--api-prefix', flags=('--api-prefix',), parser='str'),
    P(key='path', tab='server', row=4, label='API路径 (--path):', wattr='adv_path', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--path', flags=('--path',), parser='str'),
    P(key='parallel', tab='server', row=5, label='并行槽位 (--parallel):', wattr='adv_parallel', widget='spin', default=-1, emit='diff', fmt='int', flag='-np', flags=('-np', '--parallel'), parser='int', min=-1, max=64),
    P(key='cont_batching', tab='server', row=6, label='连续批处理 (--cont-batching):', wattr='adv_cont_batching', widget='check', default=True, emit='bool_neg', flag=['--cont-batching', '--no-cont-batching'], flags=('-nocb', '--no-cont-batching'), parser='bool'),
    P(key='slot_prompt_similarity', tab='server', row=7, label='槽位提示相似度 (--slot-prompt-similarity):', wattr='adv_slot_sim', widget='dspin', default=0.1, emit='diff', fmt='f2', flag='-sps', flags=('-sps', '--slot-prompt-similarity'), parser='float', min=0, max=1.0, step=0.05),
    P(key='slots', tab='server', row=8, label='槽位API (--slots):', wattr='adv_slots', widget='check', default=True, emit='bool_neg', flag=['--slots', '--no-slots'], flags=('--no-slots',), parser='bool'),
    P(key='slot_save_path', tab='server', row=9, label='槽位保存路径 (--slot-save-path):', wattr='adv_slot_save_path', widget='dir_text', default='', emit='diff_nonempty', fmt='str', flag='--slot-save-path', flags=('--slot-save-path',), parser='str', browse='dir', browse_title="选择目录", placeholder="槽位KV缓存保存路径"),
    P(key='sleep_idle_seconds', tab='server', row=10, label='空闲休眠秒 (--sleep-idle-seconds):', wattr='adv_sleep_idle', widget='spin', default=-1, emit='diff', fmt='int', flag='--sleep-idle-seconds', flags=('--sleep-idle-seconds',), parser='int', min=-1, max=99999),
    P(key='timeout', tab='server', row=11, label='超时秒数 (--timeout):', wattr='adv_timeout', widget='spin', default=3600, emit='diff', fmt='int', flag='-to', flags=('-to', '--timeout'), parser='int', min=1, max=99999),
    P(key='sse_ping_interval', tab='server', row=12, label='SSE心跳间隔 (--sse-ping-interval):', wattr='adv_sse_ping', widget='spin', default=30, emit='diff', fmt='int', flag='--sse-ping-interval', flags=('--sse-ping-interval',), parser='int', min=-1, max=99999, tooltip="-1 = 禁用"),
    P(key='threads_http', tab='server', row=13, label='HTTP线程 (--threads-http):', wattr='adv_threads_http', widget='spin', default=-1, emit='diff', fmt='int', flag='--threads-http', flags=('--threads-http',), parser='int', min=-1, max=256),
    P(key='metrics', tab='server', row=14, label='Prometheus指标 (--metrics):', wattr='adv_metrics', widget='check', default=False, emit='bool_pos', flag='--metrics', flags=('--metrics',), parser='bool'),
    P(key='props', tab='server', row=15, label='属性端点 (--props):', wattr='adv_props', widget='check', default=False, emit='bool_pos', flag='--props', flags=('--props',), parser='bool'),
    P(key='webui', tab='server', row=16, label='WebUI (--webui):', wattr='adv_webui', widget='check', default=True, emit='bool_neg', flag=['--webui', '--no-webui'], flags=('--no-webui',), parser='bool'),
    P(key='webui_config', tab='server', row=17, label='WebUI配置JSON (--webui-config):', wattr='adv_webui_config', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--webui-config', flags=('--webui-config', '--ui-config'), parser='str', placeholder="JSON格式的WebUI配置"),
    P(key='webui_config_file', tab='server', row=18, label='WebUI配置 (--webui-config-file):', wattr='adv_webui_cfg', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--webui-config-file', flags=('--webui-config-file', '--ui-config-file'), parser='str', browse='file', filter_str="JSON Files (*.json)"),
    P(key='api_key', tab='server', row=19, label='API密钥 (--api-key):', wattr='adv_api_key', widget='password', default='', emit='diff_nonempty', fmt='str', flag='--api-key', flags=('--api-key',), parser='str', echo=True),
    P(key='api_key_file', tab='server', row=20, label='API密钥文件 (--api-key-file):', wattr='adv_api_key_file', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--api-key-file', flags=('--api-key-file',), parser='str', browse='file', filter_str="All Files (*)"),
    P(key='ssl_key_file', tab='server', row=21, label='SSL密钥 (--ssl-key-file):', wattr='adv_ssl_key', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--ssl-key-file', flags=('--ssl-key-file',), parser='str', browse='file', filter_str="PEM Files (*.pem *.key)"),
    P(key='ssl_cert_file', tab='server', row=22, label='SSL证书 (--ssl-cert-file):', wattr='adv_ssl_cert', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--ssl-cert-file', flags=('--ssl-cert-file',), parser='str', browse='file', filter_str="PEM Files (*.pem *.crt)"),
    P(key='cors_origins', tab='server', row=23, label='CORS来源 (--cors-origins):', wattr='adv_cors_origins', widget='text', default='*', emit='diff_nonempty', fmt='str', flag='--cors-origins', flags=('--cors-origins',), parser='str'),
    P(key='cors_methods', tab='server', row=24, label='CORS方法 (--cors-methods):', wattr='adv_cors_methods', widget='text', default='GET, POST, DELETE, OPTIONS', emit='diff_nonempty', fmt='str', flag='--cors-methods', flags=('--cors-methods',), parser='str'),
    P(key='cors_headers', tab='server', row=25, label='CORS头 (--cors-headers):', wattr='adv_cors_headers', widget='text', default='*', emit='diff_nonempty', fmt='str', flag='--cors-headers', flags=('--cors-headers',), parser='str'),
    P(key='cors_credentials', tab='server', row=26, label='CORS凭据 (--cors-credentials):', wattr='adv_cors_credentials', widget='check', default=True, emit='bool_neg', flag=['--cors-credentials', '--no-cors-credentials'], flags=('--no-cors-credentials',), parser='bool'),
    P(key='embedding', tab='server', row=27, label='嵌入模式 (--embedding):', wattr='adv_embedding', widget='check', default=False, emit='bool_pos', flag='--embedding', flags=('--embedding',), parser='bool'),
    P(key='rerank', tab='server', row=28, label='重排模式 (--rerank):', wattr='adv_rerank', widget='check', default=False, emit='bool_pos', flag='--rerank', flags=('--rerank',), parser='bool'),
    P(key='pooling', tab='server', row=29, label='池化类型 (--pooling):', wattr='adv_pooling', widget='combo', default='none', emit='diff_skip', fmt='str', flag='--pooling', skip_values=('none',), flags=('--pooling',), parser='str', items=["none", "mean", "cls", "last", "rank"]),
    P(key='embd_normalize', tab='server', row=30, label='嵌入归一化 (--embd-normalize):', wattr='adv_embd_normalize', widget='spin', default=2, emit='diff', fmt='int', flag='--embd-normalize', flags=('--embd-normalize',), parser='int', min=-1, max=10),
    P(key='media_path', tab='server', row=31, label='媒体路径 (--media-path):', wattr='adv_media_path', widget='dir_text', default='', emit='diff_nonempty', fmt='str', flag='--media-path', flags=('--media-path',), parser='str', browse='dir', browse_title="选择目录", placeholder="本地媒体文件目录"),
    P(key='models_dir', tab='server', row=32, label='模型目录 (--models-dir):', wattr='adv_models_dir', widget='dir', default='', emit='diff_nonempty', fmt='str', flag='--models-dir', flags=('--models-dir',), parser='str', browse='dir'),
    P(key='models_preset', tab='server', row=33, label='模型预设 (--models-preset):', wattr='adv_models_preset', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--models-preset', flags=('--models-preset',), parser='str', browse='file', filter_str="INI Files (*.ini)"),
    P(key='models_max', tab='server', row=34, label='最大模型数 (--models-max):', wattr='adv_models_max', widget='spin', default=4, emit='diff', fmt='int', flag='--models-max', flags=('--models-max',), parser='int', min=0, max=64),
    P(key='models_autoload', tab='server', row=35, label='自动加载模型 (--models-autoload):', wattr='adv_models_autoload', widget='check', default=True, emit='bool_neg', flag=['--models-autoload', '--no-models-autoload'], flags=('--models-autoload',), parser='bool'),
    # ---------- agent (tab=agent) ----------
    P(key='agent', tab='agent', row=0, label='Agent模式 (--agent):', wattr='adv_agent', widget='check', default=False, emit='bool_pos', flag='--agent', flags=('-ag', '--agent'), parser='bool'),
    P(key='tools', tab='agent', row=1, label='工具 (--tools):', wattr='adv_tools_list', widget='checklist', default=[], emit='diff_join', fmt='join', flag='--tools', parser='bool', items=('read_file', 'file_glob_search', 'grep_search', 'exec_shell_command', 'write_file', 'edit_file', 'get_datetime', 'get_info'), value='checklist'),
    P(key='tools_runtime', tab='agent', row=2, label='工具运行时 (--tools-runtime):', wattr='adv_tools_runtime', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--tools-runtime', flags=('--tools-runtime',), parser='str', placeholder="docker:<image>, podman:<image>, ssh:<target>"),
    P(key='mcp_servers_config', tab='agent', row=3, label='MCP服务器配置 (--mcp-servers-config):', wattr='adv_mcp_servers_config', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--mcp-servers-config', flags=('--mcp-servers-config',), parser='str', browse='file', filter_str="JSON Files (*.json)"),
    P(key='mcp_servers_json', tab='agent', row=4, label='MCP服务器JSON (--mcp-servers-json):', wattr='adv_mcp_servers_json', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--mcp-servers-json', flags=('--mcp-servers-json',), parser='str', placeholder='{"servers": {...}}'),
    P(key='webui_mcp_proxy', tab='agent', row=5, label='WebUI MCP代理 (--webui-mcp-proxy):', wattr='adv_webui_mcp', widget='check', default=False, emit='bool_pos', flag='--webui-mcp-proxy', flags=('--webui-mcp-proxy', '--ui-mcp-proxy'), parser='bool'),
    # ---------- chat (tab=chat) ----------
    P(key='jinja', tab='chat', row=0, label='Jinja模板 (--jinja):', wattr='adv_jinja', widget='check', default=True, emit='bool_neg', flag=['--jinja', '--no-jinja'], flags=('--no-jinja',), parser='bool'),
    P(key='chat_template', tab='chat', row=1, label='聊天模板 (--chat-template):', wattr='adv_chat_template', widget='combo_edit', default='', emit='diff_nonempty', fmt='str', flag='--chat-template', flags=('--chat-template',), parser='str', value='combo_edit'),
    P(key='chat_template_file', tab='chat', row=2, label='模板文件 (--chat-template-file):', wattr='adv_chat_template_file', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--chat-template-file', flags=('--chat-template-file',), parser='str', browse='file', filter_str="Jinja Files (*.jinja *.j2)"),
    P(key='chat_template_kwargs', tab='chat', row=3, label='模板参数 (--chat-template-kwargs):', wattr='adv_chat_kwargs', widget='mtext', default='', emit='diff_nonempty', fmt='str', flag='--chat-template-kwargs', flags=('--chat-template-kwargs',), parser='str', placeholder='{"key": "value"}'),
    P(key='skip_chat_parsing', tab='chat', row=4, label='跳过聊天解析 (--skip-chat-parsing):', wattr='adv_skip_chat', widget='check', default=False, emit='bool_pos', flag='--skip-chat-parsing', flags=('--skip-chat-parsing',), parser='bool'),
    P(key='prefill_assistant', tab='chat', row=5, label='预填充助手 (--prefill-assistant):', wattr='adv_prefill', widget='check', default=True, emit='bool_neg', flag=['--prefill-assistant', '--no-prefill-assistant'], flags=('--no-prefill-assistant',), parser='bool'),
    P(key='reasoning', tab='chat', row=6, label='推理模式 (--reasoning):', wattr='adv_reasoning', widget='combo', default='auto', emit='diff', fmt='str', flag='--reasoning', flags=('-rea', '--reasoning'), parser='str', items=["on", "off", "auto"], curtext="auto"),
    P(key='reasoning_format', tab='chat', row=7, label='推理格式 (--reasoning-format):', wattr='adv_reasoning_fmt', widget='combo', default='auto', emit='diff', fmt='str', flag='--reasoning-format', flags=('--reasoning-format',), parser='str', items=["none", "deepseek", "deepseek-legacy", "auto"], curtext="auto"),
    P(key='reasoning_budget', tab='chat', row=8, label='推理预算 (--reasoning-budget):', wattr='adv_reasoning_budget', widget='spin', default=-1, emit='diff', fmt='int', flag='--reasoning-budget', flags=('--reasoning-budget',), parser='int', min=-1, max=99999),
    P(key='reasoning_budget_message', tab='chat', row=9, label='推理预算消息 (--reasoning-budget-message):', wattr='adv_reasoning_budget_msg', widget='text', default='', emit='diff_nonempty', fmt='str', flag='--reasoning-budget-message', flags=('--reasoning-budget-message',), parser='str'),
    # binary: "(default: enabled)" — must be negatable (bool_neg) so the
    # user can actually turn it OFF (--no-reasoning-preserve)
    P(key='reasoning_preserve', tab='chat', row=10, label='保留推理痕迹 (--reasoning-preserve):', wattr='adv_reasoning_preserve', widget='check', default=True, emit='bool_neg', flag=['--reasoning-preserve', '--no-reasoning-preserve'], flags=('--reasoning-preserve', '--no-reasoning-preserve'), parser='bool'),
    # ---------- advanced (tab=advanced) ----------
    P(key='special', tab='advanced', row=0, label='特殊Token (--special):', wattr='adv_special', widget='check', default=False, emit='bool_pos', flag='--special', flags=('-sp', '--special'), parser='bool'),
    P(key='reverse_prompt', tab='advanced', row=1, label='反向提示词 (--reverse-prompt):', wattr='adv_reverse_prompt', widget='text', default='', emit='diff_nonempty', fmt='str', flag='-r', flags=('-r', '--reverse-prompt'), parser='str'),
    P(key='spm_infill', tab='advanced', row=2, label='SPM填充 (--spm-infill):', wattr='adv_spm_infill', widget='check', default=False, emit='bool_pos', flag='--spm-infill', flags=('--spm-infill',), parser='bool'),
    P(key='escape', tab='advanced', row=3, label='转义处理 (--escape):', wattr='adv_escape', widget='check', default=True, emit='bool_neg', flag=['--escape', '--no-escape'], flags=('--no-escape',), parser='bool'),
    P(key='offline', tab='advanced', row=4, label='离线模式 (--offline):', wattr='adv_offline', widget='check', default=False, emit='bool_pos', flag='--offline', flags=('--offline',), parser='bool'),
    P(key='verbose', tab='advanced', row=5, label='详细输出 (--verbose):', wattr='adv_verbose', widget='check', default=False, emit='bool_pos', flag='--verbose', flags=('--verbose',), parser='bool'),
    P(key='log_verbosity', tab='advanced', row=6, label='日志详细度 (--log-verbosity):', wattr='adv_log_verbosity', widget='combo_index', default=3, emit='index', flag='--log-verbosity', flags=('-lv', '--verbosity', '--log-verbosity'), parser='int', items=["0 (generic)", "1 (error)", "2 (warning)", "3 (info)", "4 (trace)", "5 (debug)"], curidx=3, value='index'),
    P(key='log_colors', tab='advanced', row=7, label='日志颜色 (--log-colors):', wattr='adv_log_colors', widget='combo', default='auto', emit='diff', fmt='str', flag='--log-colors', flags=('--log-colors',), parser='str', items=["on", "off", "auto"], curtext="auto"),
    P(key='log_file', tab='advanced', row=8, label='日志文件 (--log-file):', wattr='adv_log_file', widget='file', default='', emit='diff_nonempty', fmt='str', flag='--log-file', flags=('--log-file',), parser='str', browse='file', filter_str="Text Files (*.txt *.log)"),
    P(key='log_disable', tab='advanced', row=9, label='禁用日志 (--log-disable):', wattr='adv_log_disable', widget='check', default=False, emit='bool_pos', flag='--log-disable', flags=('--log-disable',), parser='bool'),
    P(key='log_prompts_dir', tab='advanced', row=10, label='提示词日志目录 (--log-prompts-dir):', wattr='adv_log_prompts_dir', widget='dir', default='', emit='diff_nonempty', fmt='str', flag='--log-prompts-dir', flags=('--log-prompts-dir',), parser='str', browse='dir'),
    P(key='log_prefix', tab='advanced', row=11, label='日志前缀 (--log-prefix):', wattr='adv_log_prefix', widget='check', default=False, emit='bool_pos', flag='--log-prefix', flags=('--log-prefix',), parser='bool'),
    P(key='log_timestamps', tab='advanced', row=12, label='日志时间戳 (--log-timestamps):', wattr='adv_log_timestamps', widget='check', default=False, emit='bool_pos', flag='--log-timestamps', flags=('--log-timestamps',), parser='bool'),
    P(key='extra_args', tab='advanced', row=13, label='额外参数:', wattr='adv_extra_args', widget='mtext', default='', emit='extra', parser='bool', placeholder="额外参数，每行一个", value='text')
)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------
PARAMS_BY_KEY = {p.key: p for p in PARAMS}
UI_PARAMS = [p for p in PARAMS if p.wattr is not None]
TAB_ORDER = ("model", "context", "sampling", "gpu", "spec", "server",
             "agent", "chat", "advanced")


def tab_params(tab: str) -> list:
    """Params of one tab in UI (row) order."""
    return sorted((p for p in UI_PARAMS if p.tab == tab), key=lambda p: p.row)


def fallback_defaults() -> dict:
    """All default values (key -> value); the _FALLBACK_DEFAULTS baseline."""
    return {p.key: p.default for p in PARAMS}


def help_flag_maps():
    """Build the three --help parsing indexes used by core/defaults.py.

    Returns (value_map, flag_map, neg_map) where:
      value_map[key] = (aliases, parser_name)   # flags taking a value
      flag_map[key]  = aliases                  # positive boolean flags
      neg_map[key]   = aliases                  # --no-* alias of negatables
    parser_name is one of "int" | "float" | "str" | "prio"; core/defaults.py
    maps it to the actual parser function (avoids a circular import).
    """
    value_map, flag_map, neg_map = {}, {}, {}
    for p in PARAMS:
        if not p.flags:
            continue
        if p.parser != "bool":
            value_map[p.key] = (p.flags, p.parser)
        elif p.emit == "bool_neg":
            neg_map[p.key] = p.flags
        else:
            flag_map[p.key] = p.flags
    return value_map, flag_map, neg_map


def schema_i18n_strings():
    """Every Chinese-source string the schema carries (i18n coverage test)."""
    out = []
    for p in PARAMS:
        for s in (p.label, p.placeholder, p.tooltip, p.browse_title,
                  p.list_title, p.list_filter):
            if s:
                out.append(s)
        if p.items:
            out.extend(p.items)
    return out
