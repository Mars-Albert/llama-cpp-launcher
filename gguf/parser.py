import struct
from pathlib import Path

from .models import GGUFInfo, GGUFHeader, GGUFTensorInfo, GGUFStats, GGUFDiagnostic
from .ggml_types import get_type_name, estimate_tensor_nbytes, is_quantized_type
from .filename import parse_gguf_filename

# Metadata value type enum
VT_UINT8 = 0
VT_INT8 = 1
VT_UINT16 = 2
VT_INT16 = 3
VT_UINT32 = 4
VT_INT32 = 5
VT_FLOAT32 = 6
VT_BOOL = 7
VT_STRING = 8
VT_ARRAY = 9
VT_UINT64 = 10
VT_INT64 = 11
VT_FLOAT64 = 12

_MAX_SUPPORTED_VERSION = 3
_MAX_TENSOR_NAME_LEN = 64


def _align_offset(offset, alignment):
    return offset + (alignment - (offset % alignment)) % alignment


def _read_string(f):
    raw_len = f.read(8)
    if len(raw_len) < 8:
        raise ValueError("Unexpected EOF reading string length")
    slen = struct.unpack("<Q", raw_len)[0]
    data = f.read(slen)
    if len(data) < slen:
        raise ValueError(f"Unexpected EOF reading string of length {slen}")
    return data.decode("utf-8", errors="replace")


def _read_metadata_value(f, vtype):
    if vtype == VT_UINT8:
        data = f.read(1)
        return struct.unpack("<B", data)[0]
    elif vtype == VT_INT8:
        data = f.read(1)
        return struct.unpack("<b", data)[0]
    elif vtype == VT_UINT16:
        data = f.read(2)
        return struct.unpack("<H", data)[0]
    elif vtype == VT_INT16:
        data = f.read(2)
        return struct.unpack("<h", data)[0]
    elif vtype == VT_UINT32:
        data = f.read(4)
        return struct.unpack("<I", data)[0]
    elif vtype == VT_INT32:
        data = f.read(4)
        return struct.unpack("<i", data)[0]
    elif vtype == VT_FLOAT32:
        data = f.read(4)
        return struct.unpack("<f", data)[0]
    elif vtype == VT_BOOL:
        data = f.read(1)
        return struct.unpack("<B", data)[0] != 0
    elif vtype == VT_STRING:
        return _read_string(f)
    elif vtype == VT_ARRAY:
        arr_type = struct.unpack("<I", f.read(4))[0]
        arr_len = struct.unpack("<Q", f.read(8))[0]
        if arr_len > 10_000_000:
            raise ValueError(f"Array length {arr_len} exceeds sanity limit")
        result = []
        for _ in range(arr_len):
            result.append(_read_metadata_value(f, arr_type))
        return result
    elif vtype == VT_UINT64:
        data = f.read(8)
        return struct.unpack("<Q", data)[0]
    elif vtype == VT_INT64:
        data = f.read(8)
        return struct.unpack("<q", data)[0]
    elif vtype == VT_FLOAT64:
        data = f.read(8)
        return struct.unpack("<d", data)[0]
    else:
        raise ValueError(f"Unknown metadata value type: {vtype}")


def _read_metadata_kv(f):
    key = _read_string(f)
    vtype_data = f.read(4)
    if len(vtype_data) < 4:
        raise ValueError("Unexpected EOF reading metadata value type")
    vtype = struct.unpack("<I", vtype_data)[0]
    value = _read_metadata_value(f, vtype)
    return key, value, vtype


def _classify_tensor(name):
    """Extract layer number and module name from tensor name."""
    layer = None
    module = None
    parts = name.split(".")
    if len(parts) >= 2 and parts[0] == "blk":
        try:
            layer = int(parts[1])
        except ValueError:
            pass
        module = parts[2] if len(parts) > 2 else None
    else:
        # Top-level tensors (longer names first to avoid prefix conflicts)
        known_modules = [
            "token_embd", "pos_embd", "output_norm", "output",
            "attn_q", "attn_k", "attn_v", "attn_qkv", "attn_output",
            "attn_norm", "attn_norm_2",
            "ffn_gate_inp", "ffn_gate_exp", "ffn_down_exp", "ffn_up_exp",
            "ffn_norm", "ffn_up", "ffn_gate", "ffn_down",
            "ssm_in", "ssm_conv1d", "ssm_x", "ssm_a", "ssm_d", "ssm_dt", "ssm_out",
        ]
        for m in known_modules:
            if name.startswith(m):
                module = m
                break
    return layer, module


def parse_gguf(path, progress_callback=None):
    """Parse a GGUF file and return GGUFInfo.

    Args:
        path: Path to the .gguf file
        progress_callback: Optional callable(str) for progress updates

    Returns:
        GGUFInfo with all parsed data

    Raises:
        ValueError on invalid GGUF
        FileNotFoundError if file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    file_size = path.stat().st_size
    filename_info = parse_gguf_filename(path.name)
    diags: list[GGUFDiagnostic] = []

    def _prog(msg):
        if progress_callback:
            progress_callback(msg)

    _prog("Reading header...")

    with open(path, "rb") as f:
        # Read header: magic(4) + version(4) + tensor_count(8) + metadata_kv_count(8)
        header_data = f.read(24)
        if len(header_data) < 24:
            raise ValueError("File too small to contain a valid GGUF header")

        magic_raw = header_data[0:4]
        if magic_raw != b"GGUF":
            raise ValueError(
                f"Invalid GGUF magic: expected b'GGUF', got {magic_raw!r}"
            )

        version = struct.unpack("<I", header_data[4:8])[0]
        tensor_count = struct.unpack("<Q", header_data[8:16])[0]
        metadata_kv_count = struct.unpack("<Q", header_data[16:24])[0]

        if version > _MAX_SUPPORTED_VERSION:
            diags.append(GGUFDiagnostic(
                "warning",
                "Unsupported GGUF version",
                f"Version {version} is newer than supported version {_MAX_SUPPORTED_VERSION}. "
                "Some features may not parse correctly."
            ))

        header = GGUFHeader(
            magic="GGUF",
            version=version,
            tensor_count=tensor_count,
            metadata_kv_count=metadata_kv_count,
        )

        # Read metadata KV pairs
        _prog("Reading metadata...")
        metadata = {}
        for i in range(metadata_kv_count):
            key, value, vtype = _read_metadata_kv(f)
            metadata[key] = value

        # Read tensor infos
        _prog("Reading tensor infos...")
        tensors = []
        for i in range(tensor_count):
            name = _read_string(f)
            n_dims = struct.unpack("<I", f.read(4))[0]
            dims = []
            for _ in range(n_dims):
                dims.append(struct.unpack("<Q", f.read(8))[0])
            type_id = struct.unpack("<I", f.read(4))[0]
            offset = struct.unpack("<Q", f.read(8))[0]

            type_name = get_type_name(type_id)
            n_params = 1
            for d in dims:
                n_params *= d
            est_nbytes = estimate_tensor_nbytes(type_id, dims)

            layer, module = _classify_tensor(name)

            tensors.append(GGUFTensorInfo(
                name=name,
                dims=dims,
                type_id=type_id,
                type_name=type_name,
                offset=offset,
                absolute_offset=0,  # computed after alignment
                n_params=n_params,
                estimated_nbytes=est_nbytes,
                layer=layer,
                module=module,
            ))

        # Compute alignment and tensor_data_offset
        alignment = metadata.get("general.alignment", 32)
        if not isinstance(alignment, int) or alignment <= 0:
            alignment = 32

        if alignment % 8 != 0:
            diags.append(GGUFDiagnostic(
                "warning",
                "Alignment not multiple of 8",
                f"general.alignment = {alignment} is not a multiple of 8. "
                "This may cause loading issues."
            ))

        current_pos = f.tell()
        tensor_data_offset = _align_offset(current_pos, alignment)

        # Compute absolute offsets for each tensor
        for t in tensors:
            t.absolute_offset = tensor_data_offset + t.offset

        # Run diagnostics
        _prog("Running diagnostics...")
        _run_parse_diagnostics(
            path, file_size, header, metadata, tensors,
            alignment, tensor_data_offset, filename_info, diags
        )

    # Compute stats
    stats = _compute_stats(tensors)

    return GGUFInfo(
        path=str(path),
        file_size=file_size,
        header=header,
        metadata=metadata,
        tensors=tensors,
        filename_info=filename_info,
        stats=stats,
        diagnostics=diags,
        tensor_data_offset=tensor_data_offset,
        alignment=alignment,
    )


def _run_parse_diagnostics(path, file_size, header, metadata, tensors,
                           alignment, tensor_data_offset, filename_info, diags):
    """Run post-parse diagnostics."""
    # Check for missing architecture
    if "general.architecture" not in metadata:
        diags.append(GGUFDiagnostic(
            "warning",
            "Missing architecture",
            "general.architecture is not set in metadata."
        ))

    # Check alignment default
    if "general.alignment" not in metadata:
        diags.append(GGUFDiagnostic(
            "info",
            "Default alignment",
            "general.alignment not specified, using default 32."
        ))

    # Check quantization_version
    has_quant = any(is_quantized_type(t.type_id) for t in tensors)
    if has_quant and "general.quantization_version" not in metadata:
        diags.append(GGUFDiagnostic(
            "warning",
            "Missing quantization version",
            "File contains quantized tensors but general.quantization_version is not set."
        ))

    # Check tensor offsets
    for t in tensors:
        if t.absolute_offset >= file_size:
            diags.append(GGUFDiagnostic(
                "error",
                "Tensor offset out of bounds",
                f"Tensor '{t.name}' absolute offset {t.absolute_offset} "
                f"exceeds file size {file_size}."
            ))
        elif t.absolute_offset % alignment != 0:
            diags.append(GGUFDiagnostic(
                "warning",
                "Tensor offset not aligned",
                f"Tensor '{t.name}' absolute offset {t.absolute_offset} "
                f"is not a multiple of alignment {alignment}."
            ))

    # Check tensor name lengths
    for t in tensors:
        if len(t.name.encode("utf-8")) > _MAX_TENSOR_NAME_LEN:
            diags.append(GGUFDiagnostic(
                "warning",
                "Tensor name too long",
                f"Tensor name '{t.name}' exceeds {_MAX_TENSOR_NAME_LEN} bytes."
            ))

    # Filename diagnostics
    if filename_info and not filename_info.parse_ok:
        diags.append(GGUFDiagnostic(
            "warning",
            "Filename does not match naming convention",
            "The filename does not follow the recommended GGUF naming convention."
        ))

    # Sidecar mismatch checks
    if filename_info and filename_info.sidecar == "mmproj":
        arch = metadata.get("general.architecture", "")
        if arch and arch not in ("llava", "clip", "whisper", "vision"):
            diags.append(GGUFDiagnostic(
                "info",
                "Sidecar type hint",
                "File has mmproj sidecar but architecture is not vision-related."
            ))

    # Note: info-level diagnostics (chat_template, hf_tokenizer, rope, moe, shard)
    # are now in gguf.diagnostics.run_diagnostics()


def _compute_stats(tensors):
    """Compute aggregate stats from tensor list."""
    total_params = 0
    total_bytes = 0
    type_counts: dict[int, int] = {}
    type_sizes: dict[int, int] = {}
    dominant_type = ""
    max_count = 0

    for t in tensors:
        total_params += t.n_params
        type_counts[t.type_id] = type_counts.get(t.type_id, 0) + 1
        if t.estimated_nbytes is not None:
            total_bytes += t.estimated_nbytes
            type_sizes[t.type_id] = type_sizes.get(t.type_id, 0) + t.estimated_nbytes

    for tid, count in type_counts.items():
        if count > max_count:
            max_count = count
            dominant_type = get_type_name(tid)

    return GGUFStats(
        total_params=total_params,
        total_estimated_bytes=total_bytes,
        tensor_type_counts=type_counts,
        tensor_type_sizes=type_sizes,
        dominant_type_name=dominant_type,
    )
