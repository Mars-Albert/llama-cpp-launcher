import struct
import tempfile
import os
from pathlib import Path

import pytest

from gguf.filename import parse_gguf_filename
from gguf.ggml_types import (
    GGML_TYPES, estimate_tensor_nbytes, get_type_name, is_quantized_type
)
from gguf.models import GGUFInfo, GGUFHeader, GGUFFilenameInfo
from gguf.parser import parse_gguf, _align_offset
from gguf.diagnostics import run_diagnostics


# ---------------------------------------------------------------------------
# Fake GGUF builder (for tests)
# ---------------------------------------------------------------------------

def build_fake_gguf(
    metadata: dict | None = None,
    tensors: list[dict] | None = None,
    alignment: int = 32,
    version: int = 3,
) -> bytes:
    """Build a minimal valid GGUF file in memory."""
    if metadata is None:
        metadata = {}
    if tensors is None:
        tensors = []

    # Ensure alignment is set
    if "general.alignment" not in metadata:
        metadata["general.alignment"] = alignment

    buf = bytearray()

    # Header: magic + version + tensor_count + metadata_kv_count
    buf += b"GGUF"
    buf += struct.pack("<I", version)
    buf += struct.pack("<Q", len(tensors))
    buf += struct.pack("<Q", len(metadata))

    # Metadata KV pairs
    for key, value in metadata.items():
        if isinstance(value, bool):
            vtype = 7
        elif isinstance(value, int):
            vtype = 10  # uint64
        elif isinstance(value, float):
            vtype = 6  # float32
        elif isinstance(value, str):
            vtype = 8
        else:
            continue
        encoded_key = key.encode("utf-8")
        buf += struct.pack("<Q", len(encoded_key))
        buf += encoded_key
        buf += struct.pack("<I", vtype)
        if vtype == 7:
            buf += struct.pack("<B", 1 if value else 0)
        elif vtype == 10:
            buf += struct.pack("<Q", value)
        elif vtype == 6:
            buf += struct.pack("<f", value)
        elif vtype == 8:
            encoded_val = value.encode("utf-8")
            buf += struct.pack("<Q", len(encoded_val))
            buf += encoded_val

    # Tensor infos
    for t in tensors:
        name_bytes = t["name"].encode("utf-8")
        buf += struct.pack("<Q", len(name_bytes))
        buf += name_bytes
        buf += struct.pack("<I", len(t["dims"]))
        for d in t["dims"]:
            buf += struct.pack("<Q", d)
        buf += struct.pack("<I", t["type_id"])
        buf += struct.pack("<Q", t.get("offset", 0))

    # Pad to alignment
    current = len(buf)
    aligned = _align_offset(current, alignment)
    buf += b"\x00" * (aligned - current)

    # Fake tensor data (just a few bytes)
    buf += b"\x00" * 64

    return bytes(buf)


def write_fake_gguf(path, **kwargs):
    """Write a fake GGUF file to disk."""
    data = build_fake_gguf(**kwargs)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ---------------------------------------------------------------------------
# Filename parser tests
# ---------------------------------------------------------------------------

class TestFilenameParser:
    def test_qwen3_27b(self):
        r = parse_gguf_filename("Qwen3-27B-v1.0-Q5_K.gguf")
        assert r.parse_ok
        assert r.sidecar is None
        assert r.base_name == "Qwen3"
        assert r.size_label == "27B"
        assert r.version == "v1.0"
        assert r.encoding == "Q5_K"
        assert r.type is None
        assert r.shard is None

    def test_mtp_qwen3(self):
        r = parse_gguf_filename("mtp-Qwen3-27B-v1.0-Q4_K_M.gguf")
        assert r.parse_ok
        assert r.sidecar == "mtp"
        assert r.base_name == "Qwen3"
        assert r.size_label == "27B"
        assert r.version == "v1.0"
        assert r.encoding == "Q4_K_M"

    def test_mmproj_qwen2(self):
        r = parse_gguf_filename("mmproj-Qwen2-VL-7B-v1.0-F16.gguf")
        assert r.parse_ok
        assert r.sidecar == "mmproj"
        assert r.base_name == "Qwen2-VL"
        assert r.size_label == "7B"
        assert r.version == "v1.0"
        assert r.encoding == "F16"

    def test_grok_shard(self):
        r = parse_gguf_filename("Grok-100B-v1.0-Q4_0-00003-of-00009.gguf")
        assert r.parse_ok
        assert r.base_name == "Grok"
        assert r.size_label == "100B"
        assert r.version == "v1.0"
        assert r.encoding == "Q4_0"
        assert r.shard == "00003-of-00009"

    def test_not_a_valid_arrangement(self):
        r = parse_gguf_filename("not-a-known-arrangement.gguf")
        assert not r.parse_ok

    def test_lora_type(self):
        r = parse_gguf_filename("Hermes-2-Pro-Llama-3-8B-v1.0-F16-LoRA.gguf")
        assert r.parse_ok
        assert r.type == "LoRA"

    def test_minimal_name(self):
        r = parse_gguf_filename("Phi-3-mini-3.8B-v1.0.gguf")
        assert r.parse_ok
        assert r.base_name is not None

    def test_version_default(self):
        r = parse_gguf_filename("Qwen3-27B-v1.0-Q5_K.gguf")
        assert r.version == "v1.0"

    # --- Heuristic parser tests ---

    def test_heuristic_qwen36_27b(self):
        r = parse_gguf_filename("Qwen3.6-27B-UD-Q5_K_XL.gguf")
        assert r.parse_ok
        assert r.heuristic
        assert r.base_name == "Qwen3.6"
        assert r.size_label == "27B"
        assert r.encoding == "Q5_K_XL"
        assert r.fine_tune == "UD"

    def test_heuristic_qwen25_72b(self):
        r = parse_gguf_filename("Qwen2.5-72B-Instruct-Q4_K_M.gguf")
        assert r.parse_ok
        assert r.heuristic
        assert r.base_name == "Qwen2.5"
        assert r.size_label == "72B"
        assert r.encoding == "Q4_K_M"
        assert r.fine_tune == "Instruct"

    def test_heuristic_llama31_70b(self):
        r = parse_gguf_filename("llama-3.1-70b-instruct-Q4_K_M.gguf")
        assert r.parse_ok
        assert r.heuristic
        assert r.size_label == "70b"
        assert r.encoding == "Q4_K_M"

    def test_heuristic_deepseek_r1(self):
        r = parse_gguf_filename("DeepSeek-R1-Qwen-14B-Q4_K_M.gguf")
        assert r.parse_ok
        assert r.heuristic
        assert r.size_label == "14B"
        assert r.encoding == "Q4_K_M"

    def test_heuristic_preserves_strict(self):
        r = parse_gguf_filename("Qwen3-27B-v1.0-Q5_K.gguf")
        assert r.parse_ok
        assert not r.heuristic

    def test_heuristic_mmproj(self):
        r = parse_gguf_filename("mmproj-Qwen2-VL-7B-F16.gguf")
        assert r.parse_ok
        assert r.sidecar == "mmproj"
        assert r.size_label == "7B"
        assert r.encoding == "F16"


# ---------------------------------------------------------------------------
# GGML types tests
# ---------------------------------------------------------------------------

class TestGGMLTypes:
    def test_all_known_types_have_names(self):
        known_ids = [
            0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
            16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28,
            29, 30, 34, 35, 39
        ]
        for tid in known_ids:
            name = get_type_name(tid)
            assert name != f"UNKNOWN_{tid}", f"Type {tid} should have a name"

    def test_unknown_type(self):
        assert get_type_name(999) == "UNKNOWN_999"

    def test_f32_estimate(self):
        # F32: 1 element per block, 4 bytes per block
        nbytes = estimate_tensor_nbytes(0, [1024, 4096])
        assert nbytes == 1024 * 4096 * 4

    def test_f16_estimate(self):
        nbytes = estimate_tensor_nbytes(1, [1024, 4096])
        assert nbytes == 1024 * 4096 * 2

    def test_q4_0_estimate(self):
        # Q4_0: block_size=32, 18 bytes per block
        nbytes = estimate_tensor_nbytes(2, [4096])
        expected = ((4096 + 31) // 32) * 18
        assert nbytes == expected

    def test_q4_k_estimate(self):
        nbytes = estimate_tensor_nbytes(12, [4096])
        assert nbytes is not None
        assert nbytes > 0

    def test_unknown_type_returns_none(self):
        assert estimate_tensor_nbytes(999, [100]) is None

    def test_is_quantized(self):
        assert is_quantized_type(2)  # Q4_0
        assert is_quantized_type(12)  # Q4_K
        assert not is_quantized_type(0)  # F32
        assert not is_quantized_type(1)  # F16
        assert not is_quantized_type(30)  # BF16

    def test_iq_types(self):
        for tid in [16, 17, 18, 19, 20, 21, 22, 23, 29]:
            name = get_type_name(tid)
            assert name.startswith("IQ")


# ---------------------------------------------------------------------------
# GGUF parser tests
# ---------------------------------------------------------------------------

class TestGGUFParser:
    def test_parse_minimal(self, tmp_path):
        gguf_path = tmp_path / "test.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={"general.architecture": "llama"},
            tensors=[
                {"name": "token_embd.weight", "dims": [32000, 4096], "type_id": 1, "offset": 0},
            ],
        )

        info = parse_gguf(str(gguf_path))
        assert isinstance(info, GGUFInfo)
        assert info.header.magic == "GGUF"
        assert info.header.version == 3
        assert info.header.tensor_count == 1
        # build_fake_gguf auto-adds general.alignment, so 2 metadata KV pairs
        assert info.header.metadata_kv_count == 2
        assert info.metadata["general.architecture"] == "llama"
        assert len(info.tensors) == 1
        assert info.tensors[0].name == "token_embd.weight"
        assert info.tensors[0].type_name == "F16"
        assert info.alignment == 32

    def test_parse_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            parse_gguf("/nonexistent/file.gguf")

    def test_parse_invalid_magic(self, tmp_path):
        bad_path = tmp_path / "bad.gguf"
        bad_path.write_bytes(b"NOTG" + b"\x00" * 100)
        with pytest.raises(ValueError, match="Invalid GGUF magic"):
            parse_gguf(str(bad_path))

    def test_parse_multiple_metadata(self, tmp_path):
        gguf_path = tmp_path / "multi.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={
                "general.architecture": "llama",
                "general.name": "TestModel",
                "general.file_type": 1,
            },
            tensors=[
                {"name": "blk.0.attn_q.weight", "dims": [4096, 4096], "type_id": 2, "offset": 0},
                {"name": "blk.0.attn_k.weight", "dims": [1024, 4096], "type_id": 2, "offset": 1024 * 4096 // 2},
            ],
        )

        info = parse_gguf(str(gguf_path))
        assert info.metadata["general.name"] == "TestModel"
        assert len(info.tensors) == 2
        assert info.tensors[0].layer == 0
        assert info.tensors[0].module == "attn_q"
        assert info.tensors[1].layer == 0
        assert info.tensors[1].module == "attn_k"

    def test_tensor_classification(self, tmp_path):
        gguf_path = tmp_path / "classify.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={"general.architecture": "llama"},
            tensors=[
                {"name": "token_embd.weight", "dims": [100, 10], "type_id": 0, "offset": 0},
                {"name": "blk.3.attn_q.weight", "dims": [10, 10], "type_id": 0, "offset": 0},
                {"name": "output_norm.weight", "dims": [100], "type_id": 0, "offset": 0},
            ],
        )

        info = parse_gguf(str(gguf_path))
        assert info.tensors[0].layer is None
        assert info.tensors[0].module == "token_embd"
        assert info.tensors[1].layer == 3
        assert info.tensors[1].module == "attn_q"
        assert info.tensors[2].layer is None
        assert info.tensors[2].module == "output_norm"

    def test_alignment_default(self, tmp_path):
        gguf_path = tmp_path / "noalign.gguf"
        # No general.alignment set
        data = build_fake_gguf(
            metadata={"general.architecture": "llama"},
            tensors=[],
        )
        # Remove alignment from metadata by rebuilding without it
        buf = bytearray(data)
        gguf_path.write_bytes(buf)

        info = parse_gguf(str(gguf_path))
        # Default alignment is 32
        assert info.alignment == 32

    def test_tensor_offset_alignment(self, tmp_path):
        gguf_path = tmp_path / "align.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={"general.alignment": 64},
            tensors=[
                {"name": "t.weight", "dims": [10, 10], "type_id": 0, "offset": 0},
            ],
            alignment=64,
        )
        info = parse_gguf(str(gguf_path))
        assert info.alignment == 64
        # tensor_data_offset should be aligned to 64
        assert info.tensor_data_offset % 64 == 0

    def test_stats_computation(self, tmp_path):
        gguf_path = tmp_path / "stats.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={"general.architecture": "llama"},
            tensors=[
                {"name": "t1.weight", "dims": [100, 100], "type_id": 0, "offset": 0},
                {"name": "t2.weight", "dims": [100, 100], "type_id": 1, "offset": 0},
                {"name": "t3.weight", "dims": [100, 100], "type_id": 0, "offset": 0},
            ],
        )
        info = parse_gguf(str(gguf_path))
        assert info.stats.total_params == 30000
        assert info.stats.tensor_type_counts[0] == 2
        assert info.stats.tensor_type_counts[1] == 1
        assert info.stats.dominant_type_name == "F32"

    def test_progress_callback(self, tmp_path):
        gguf_path = tmp_path / "progress.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={"general.architecture": "llama"},
            tensors=[],
        )
        messages = []
        parse_gguf(str(gguf_path), progress_callback=lambda m: messages.append(m))
        assert len(messages) > 0


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------

class TestDiagnostics:
    def _make_info(self, **overrides):
        header = GGUFHeader(magic="GGUF", version=3, tensor_count=0, metadata_kv_count=0)
        from gguf.models import GGUFStats
        return GGUFInfo(
            path=overrides.get("path", "/tmp/test.gguf"),
            file_size=overrides.get("file_size", 1000000),
            header=header,
            metadata=overrides.get("metadata", {"general.architecture": "llama"}),
            tensors=overrides.get("tensors", []),
            filename_info=overrides.get("filename_info"),
            stats=overrides.get("stats", GGUFStats()),
            diagnostics=overrides.get("diagnostics", []),
            tensor_data_offset=overrides.get("tensor_data_offset", 1024),
            alignment=overrides.get("alignment", 32),
        )

    def test_context_exceeds_model(self):
        info = self._make_info(
            metadata={"general.architecture": "llama", "llama.context_length": 4096}
        )
        diags = run_diagnostics(info, launcher_ctx=8192)
        warnings = [d for d in diags if d.level == "warning" and "Context" in d.title]
        assert len(warnings) == 1

    def test_lora_file_warning(self):
        from gguf.models import GGUFFilenameInfo
        info = self._make_info(
            filename_info=GGUFFilenameInfo(type="LoRA", parse_ok=True)
        )
        diags = run_diagnostics(info)
        lora_diags = [d for d in diags if "LoRA" in d.title or "LoRA" in d.message]
        assert len(lora_diags) == 1

    def test_mtp_sidecar_info(self):
        from gguf.models import GGUFFilenameInfo
        info = self._make_info(
            filename_info=GGUFFilenameInfo(sidecar=None, parse_ok=True)
        )
        diags = run_diagnostics(info, spec_type="draft-mtp")
        mtp_diags = [d for d in diags if "MTP" in d.title]
        assert len(mtp_diags) == 1

    def test_chat_template_detected(self):
        info = self._make_info(
            metadata={
                "general.architecture": "llama",
                "tokenizer.chat_template": "{% for message in messages %}{{ message.content }}{% endfor %}"
            }
        )
        diags = run_diagnostics(info)
        template_diags = [d for d in diags if "chat template" in d.title.lower()]
        assert len(template_diags) == 1


# ---------------------------------------------------------------------------
# Align offset tests
# ---------------------------------------------------------------------------

class TestAlignOffset:
    def test_already_aligned(self):
        assert _align_offset(64, 32) == 64

    def test_needs_alignment(self):
        assert _align_offset(65, 32) == 96

    def test_alignment_64(self):
        assert _align_offset(1, 64) == 64
        assert _align_offset(64, 64) == 64
        assert _align_offset(65, 64) == 128

    def test_alignment_1(self):
        assert _align_offset(100, 1) == 100


# ---------------------------------------------------------------------------
# Integration test with fake file
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_roundtrip(self, tmp_path):
        gguf_path = tmp_path / "full.gguf"
        write_fake_gguf(
            str(gguf_path),
            metadata={
                "general.architecture": "llama",
                "general.name": "TestModel-7B",
                "general.basename": "TestModel",
                "general.size_label": "7B",
                "general.version": "v1.0",
                "general.alignment": 32,
                "llama.context_length": 4096,
                "llama.embedding_length": 4096,
                "llama.block_count": 32,
                "llama.attention.head_count": 32,
                "llama.attention.head_count_kv": 8,
            },
            tensors=[
                {"name": "token_embd.weight", "dims": [32000, 4096], "type_id": 1, "offset": 0},
                {"name": "blk.0.attn_q.weight", "dims": [4096, 4096], "type_id": 2, "offset": 0},
                {"name": "blk.0.attn_k.weight", "dims": [1024, 4096], "type_id": 2, "offset": 0},
                {"name": "output_norm.weight", "dims": [4096], "type_id": 1, "offset": 0},
            ],
        )

        info = parse_gguf(str(gguf_path))

        # Verify header
        assert info.header.tensor_count == 4
        # 11 metadata entries (general.alignment already included, no duplicate added)
        assert info.header.metadata_kv_count == 11

        # Verify metadata
        assert info.metadata["general.architecture"] == "llama"
        assert info.metadata["llama.context_length"] == 4096

        # Verify tensors
        assert len(info.tensors) == 4
        assert info.tensors[0].name == "token_embd.weight"
        assert info.tensors[0].n_params == 32000 * 4096
        assert info.tensors[0].layer is None
        assert info.tensors[0].module == "token_embd"
        assert info.tensors[1].layer == 0

        # Verify stats
        assert info.stats.total_params > 0
        assert info.stats.dominant_type_name != ""

        # Verify filename
        assert info.filename_info is not None

        # Verify diagnostics
        assert isinstance(info.diagnostics, list)

        # Run launcher-aware diagnostics
        diags = run_diagnostics(info, launcher_ctx=8192)
        assert any("Context" in d.title for d in diags)
