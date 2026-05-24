import re

from .models import GGUFFilenameInfo

# Strict regex from gguf.md naming convention
_FILENAME_RE = re.compile(
    r"^(?:(?P<Sidecar>mmproj|mtp)-)?"
    r"(?P<BaseName>[A-Za-z0-9\s]*(?:(?:-(?:(?:[A-Za-z\s][A-Za-z0-9\s]*)|(?:[0-9\s]*)))*))"
    r"-(?:(?P<SizeLabel>(?:\d+x)?(?:\d+\.)?\d+[A-Za-z](?:-[A-Za-z]+(\d+\.)?\d+[A-Za-z]+)?)"
    r"(?:-(?P<FineTune>[A-Za-z0-9\s-]+))?)?"
    r"-(?:(?P<Version>v\d+(?:\.\d+)*))"
    r"(?:-(?P<Encoding>(?!LoRA|vocab)[\w_]+))?"
    r"(?:-(?P<Type>LoRA|vocab))?"
    r"(?:-(?P<Shard>\d{5}-of-\d{5}))?\.gguf$"
)

# Heuristic patterns
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)[TtBbMmKk]")
_VERSION_RE = re.compile(r"v(\d+(?:\.\d+)*)")
_SHARD_RE = re.compile(r"(\d{5}-of-\d{5})")
_LORA_RE = re.compile(r"[-_]LoRA[-_]|[-_]lora[-_]", re.IGNORECASE)
_VOCAB_RE = re.compile(r"[-_]vocab[-_]", re.IGNORECASE)

# Known quant encoding patterns
_QUANT_PATTERNS = [
    re.compile(r"Q[2-8]_[01K][A-Za-z0-9_]*"),  # Q4_0, Q5_K_M, Q8_0, etc.
    re.compile(r"F16|F32"),
    re.compile(r"BF16"),
    re.compile(r"IQ\d+[_A-Za-z0-9]*"),  # IQ2_XXS, IQ4_NL, etc.
    re.compile(r"TQ\d+[_A-Za-z0-9]*"),  # TQ1_0, TQ2_0
    re.compile(r"MXFP4"),
]

# Known fine-tune descriptors
_FINETUNE_KEYWORDS = [
    "Instruct", "Chat", "Base", "UD", "RAW", "GGML",
    "imatrix", "IMATRIX",
]


def parse_gguf_filename(filename: str) -> GGUFFilenameInfo:
    """Parse a GGUF filename according to the naming convention.

    First tries the strict regex from gguf.md. If that fails, falls back
    to a heuristic parser that extracts what it can from common patterns.
    """
    match = _FILENAME_RE.match(filename)
    if match:
        groups = match.groupdict()
        return GGUFFilenameInfo(
            sidecar=groups.get("Sidecar"),
            base_name=groups.get("BaseName"),
            size_label=groups.get("SizeLabel"),
            fine_tune=groups.get("FineTune"),
            version=groups.get("Version") or "v1.0",
            encoding=groups.get("Encoding"),
            type=groups.get("Type"),
            shard=groups.get("Shard"),
            parse_ok=True,
            heuristic=False,
        )

    return _heuristic_parse(filename)


def _heuristic_parse(filename: str) -> GGUFFilenameInfo:
    """Heuristic fallback parser for non-conforming GGUF filenames."""
    # Strip .gguf suffix
    if filename.endswith(".gguf"):
        name = filename[:-5]
    else:
        name = filename

    parts = name.split("-")
    sidecar = None
    encoding = None
    shard = None
    size_label = None
    version = None
    fine_tune = None
    file_type = None

    # Check sidecar prefix
    if parts and parts[0].lower() in ("mmproj", "mtp"):
        sidecar = parts[0].lower()
        parts = parts[1:]

    # Check shard at end
    shard_m = _SHARD_RE.search(name)
    if shard_m:
        shard = shard_m.group(1)

    # Check type (LoRA / vocab)
    if _LORA_RE.search(name):
        file_type = "LoRA"
    elif _VOCAB_RE.search(name):
        file_type = "vocab"

    # Find encoding (quant pattern)
    for pat in _QUANT_PATTERNS:
        m = pat.search(name)
        if m:
            encoding = m.group(0)
            break

    # Find version
    vm = _VERSION_RE.search(name)
    if vm:
        version = "v" + vm.group(1)

    # Find size label
    # Look for patterns like 27B, 72B, 3.8B, 100B, 8x7B
    size_candidates = []
    for i, part in enumerate(parts):
        # Match NxB (MoE) or Nx.B (decimal)
        m = re.match(r"^(\d+x)?(\d+(?:\.\d+)?)[TtBbMmKk]$", part)
        if m:
            size_candidates.append((i, part))
    if size_candidates:
        # Take the last size-like token (more specific)
        idx, size_label = size_candidates[-1]

    # Build base name and fine tune from remaining parts
    # Heuristic: BaseName is everything before size_label (or before version/encoding)
    if size_label is not None:
        size_idx = parts.index(size_label) if size_label in parts else 0
        base_parts = parts[:size_idx]
    elif version:
        # Find version position
        for i, part in enumerate(parts):
            if _VERSION_RE.match(part):
                base_parts = parts[:i]
                break
        else:
            base_parts = parts
    elif encoding:
        # Find encoding position
        enc_lower = encoding.lower()
        for i, part in enumerate(parts):
            if part.lower() == enc_lower:
                base_parts = parts[:i]
                break
        else:
            base_parts = parts
    else:
        base_parts = parts

    base_name = "-".join(base_parts) if base_parts else None

    # FineTune: parts between size_label and version/encoding
    if size_label and base_name:
        start = parts.index(size_label) + 1 if size_label in parts else 0
        end = len(parts)
        if version:
            for i, part in enumerate(parts):
                if _VERSION_RE.match(part):
                    end = i
                    break
        elif encoding:
            enc_lower = encoding.lower()
            for i, part in enumerate(parts):
                if part.lower() == enc_lower:
                    end = i
                    break
        ft_parts = parts[start:end]
        # Filter out encoding/version/shard from fine_tune
        ft_filtered = []
        for p in ft_parts:
            if _VERSION_RE.match(p):
                continue
            if p.lower() == (encoding or "").lower():
                continue
            if _SHARD_RE.match(p):
                continue
            if file_type and p.lower() == file_type.lower():
                continue
            ft_filtered.append(p)
        if ft_filtered:
            fine_tune = "-".join(ft_filtered)

    # Clean up base_name - remove trailing empty parts
    if base_name:
        base_name = base_name.strip("-")
        if not base_name:
            base_name = None

    has_any = any([sidecar, base_name, size_label, encoding, version])
    if not has_any:
        return GGUFFilenameInfo(parse_ok=False, heuristic=False)

    # Require at least size_label or encoding for a useful heuristic match
    if not size_label and not encoding:
        return GGUFFilenameInfo(parse_ok=False, heuristic=False)

    return GGUFFilenameInfo(
        sidecar=sidecar,
        base_name=base_name,
        size_label=size_label,
        fine_tune=fine_tune,
        version=version or "v1.0",
        encoding=encoding,
        type=file_type,
        shard=shard,
        parse_ok=True,
        heuristic=True,
    )
