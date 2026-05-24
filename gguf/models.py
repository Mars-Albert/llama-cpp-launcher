from dataclasses import dataclass, field
from typing import Any


@dataclass
class GGUFHeader:
    magic: str
    version: int
    tensor_count: int
    metadata_kv_count: int


@dataclass
class GGUFTensorInfo:
    name: str
    dims: list[int]
    type_id: int
    type_name: str
    offset: int
    absolute_offset: int
    n_params: int
    estimated_nbytes: int | None
    layer: int | None = None
    module: str | None = None


@dataclass
class GGUFFilenameInfo:
    sidecar: str | None = None
    base_name: str | None = None
    size_label: str | None = None
    fine_tune: str | None = None
    version: str | None = None
    encoding: str | None = None
    type: str | None = None
    shard: str | None = None
    parse_ok: bool = False
    heuristic: bool = False


@dataclass
class GGUFDiagnostic:
    level: str  # "error", "warning", "info"
    title: str
    message: str


@dataclass
class GGUFStats:
    total_params: int = 0
    total_estimated_bytes: int = 0
    tensor_type_counts: dict[int, int] = field(default_factory=dict)
    tensor_type_sizes: dict[int, int] = field(default_factory=dict)
    dominant_type_name: str = ""


@dataclass
class GGUFInfo:
    path: str
    file_size: int
    header: GGUFHeader
    metadata: dict[str, Any]
    tensors: list[GGUFTensorInfo]
    filename_info: GGUFFilenameInfo | None
    stats: GGUFStats
    diagnostics: list[GGUFDiagnostic]
    tensor_data_offset: int
    alignment: int = 32
