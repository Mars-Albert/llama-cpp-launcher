# ggml_type enum values and names, from gguf.md
GGML_TYPES: dict[int, str] = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    6: "Q5_0",
    7: "Q5_1",
    8: "Q8_0",
    9: "Q8_1",
    10: "Q2_K",
    11: "Q3_K",
    12: "Q4_K",
    13: "Q5_K",
    14: "Q6_K",
    15: "Q8_K",
    16: "IQ2_XXS",
    17: "IQ2_XS",
    18: "IQ3_XXS",
    19: "IQ1_S",
    20: "IQ4_NL",
    21: "IQ3_S",
    22: "IQ2_S",
    23: "IQ4_XS",
    24: "I8",
    25: "I16",
    26: "I32",
    27: "I64",
    28: "F64",
    29: "IQ1_M",
    30: "BF16",
    34: "TQ1_0",
    35: "TQ2_0",
    39: "MXFP4",
}

# Block sizes for types where we can compute exact byte sizes.
# Q-type block sizes from ggml source (block_size, type_size).
# These give the bytes per block; actual tensor size = ceil(n / block_size) * type_size.
_Q_TYPE_INFO: dict[int, tuple[int, int]] = {
    # type_id: (block_size, bytes_per_block)
    0: (1, 4),       # F32: 1 element, 4 bytes
    1: (1, 2),       # F16: 1 element, 2 bytes
    2: (32, 18),     # Q4_0: 32 elements, 2+16=18 bytes (2 header + 16 data)
    3: (32, 20),     # Q4_1: 32 elements, 2+16+2=20 bytes
    6: (32, 22),     # Q5_0: 32 elements, 2+16+4=22 bytes
    7: (32, 24),     # Q5_1: 32 elements, 2+16+4+2=24 bytes
    8: (32, 34),     # Q8_0: 32 elements, 2+32=34 bytes
    9: (32, 40),     # Q8_1: 32 elements, 2+32+4+2=40 bytes
    10: (256, 84),   # Q2_K: 256 elements, 84 bytes
    11: (256, 110),  # Q3_K: 256 elements, 110 bytes
    12: (256, 144),  # Q4_K: 256 elements, 144 bytes
    13: (256, 176),  # Q5_K: 256 elements, 176 bytes
    14: (256, 210),  # Q6_K: 256 elements, 210 bytes
    15: (256, 256),  # Q8_K: 256 elements, 256 bytes
    16: (256, 84),   # IQ2_XXS: same block as Q2_K approximation
    17: (256, 96),   # IQ2_XS
    18: (256, 112),  # IQ3_XXS
    19: (256, 56),   # IQ1_S
    20: (32, 18),    # IQ4_NL
    21: (256, 120),  # IQ3_S
    22: (256, 80),   # IQ2_S
    23: (32, 18),    # IQ4_XS (approximate)
    24: (1, 1),      # I8
    25: (1, 2),      # I16
    26: (1, 4),      # I32
    27: (1, 8),      # I64
    28: (1, 8),      # F64
    29: (256, 56),   # IQ1_M
    30: (1, 2),      # BF16
    34: (256, 56),   # TQ1_0 (approximate)
    35: (256, 84),   # TQ2_0 (approximate)
    39: (32, 18),    # MXFP4 (approximate, same as Q4_0 block)
}


def estimate_tensor_nbytes(type_id: int, dims: list[int]) -> int | None:
    """Estimate tensor byte size from type_id and dimensions.

    Returns None if the type is unknown or block size info is unavailable.
    """
    total_elements = 1
    for d in dims:
        total_elements *= d

    info = _Q_TYPE_INFO.get(type_id)
    if info is None:
        return None

    block_size, bytes_per_block = info
    n_blocks = (total_elements + block_size - 1) // block_size
    return n_blocks * bytes_per_block


def get_type_name(type_id: int) -> str:
    """Return human-readable name for a ggml_type id, or 'UNKNOWN_<id>'."""
    return GGML_TYPES.get(type_id, f"UNKNOWN_{type_id}")


def is_quantized_type(type_id: int) -> bool:
    """Check if a type is a quantized (non-plain) type."""
    plain_types = {0, 1, 24, 25, 26, 27, 28, 30}  # F32, F16, I8, I16, I32, I64, F64, BF16
    return type_id not in plain_types and type_id in GGML_TYPES
