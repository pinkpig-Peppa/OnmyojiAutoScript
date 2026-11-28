"""Safe, pickle-free binary serialization for bounded numpy ndarrays over RPC."""
from __future__ import annotations

import math
import struct
import numpy as np

MAGIC = b'OASND1'
MAX_NDARRAY_BYTES = 64 * 1024 * 1024
MAX_DIMENSION = 16384

_CODE_TO_DTYPE: dict[int, np.dtype] = {
    1: np.dtype('uint8'),
    2: np.dtype('int8'),
    3: np.dtype('<u2'),
    4: np.dtype('<i2'),
    5: np.dtype('<u4'),
    6: np.dtype('<i4'),
    7: np.dtype('<f4'),
    8: np.dtype('<f8'),
    9: np.dtype('bool'),
}

_KIND_SIZE_TO_CODE: dict[tuple[str, int], int] = {
    (dt.kind, dt.itemsize): code for code, dt in _CODE_TO_DTYPE.items()
}


def encode_ndarray(array: np.ndarray, *, max_bytes: int = MAX_NDARRAY_BYTES) -> bytes:
    """Serialize a numeric numpy ndarray without pickle."""
    if not isinstance(array, np.ndarray):
        raise TypeError(f'Expected numpy.ndarray, got {type(array).__name__}')
    ndim = array.ndim
    if ndim < 1 or ndim > 4:
        raise ValueError(f'Unsupported ndarray ndim={ndim}; expected 1..4')
    code = _KIND_SIZE_TO_CODE.get((array.dtype.kind, array.dtype.itemsize))
    if code is None:
        raise ValueError(f'Unsupported ndarray dtype={array.dtype}')
    target_dtype = _CODE_TO_DTYPE[code]
    for dim in array.shape:
        if dim < 0 or dim > MAX_DIMENSION:
            raise ValueError(f'Invalid ndarray dimension={dim} in shape={array.shape}')
    contiguous = np.ascontiguousarray(array, dtype=target_dtype)
    if contiguous.nbytes > max_bytes:
        raise ValueError(f'ndarray payload {contiguous.nbytes} bytes exceeds limit {max_bytes}')
    header = struct.pack(f'>6sBB{ndim}I', MAGIC, code, ndim, *contiguous.shape)
    return header + contiguous.tobytes()


def decode_ndarray(payload: bytes, *, max_bytes: int = MAX_NDARRAY_BYTES) -> np.ndarray:
    """Deserialize a numeric numpy ndarray produced by encode_ndarray; rejects pickle."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError(f'Expected bytes-like payload, got {type(payload).__name__}')
    raw = memoryview(payload)
    if len(raw) < 8:
        raise ValueError('Truncated ndarray payload header')
    if bytes(raw[:6]) != MAGIC:
        raise ValueError('Invalid ndarray payload header (pickle and untrusted formats are rejected)')
    code = int(raw[6])
    ndim = int(raw[7])
    dtype = _CODE_TO_DTYPE.get(code)
    if dtype is None:
        raise ValueError(f'Unsupported ndarray dtype code={code}')
    if ndim < 1 or ndim > 4:
        raise ValueError(f'Unsupported ndarray ndim={ndim}')
    header_size = 8 + 4 * ndim
    if len(raw) < header_size:
        raise ValueError('Truncated ndarray shape header')
    shape = struct.unpack(f'>{ndim}I', raw[8:header_size])
    for dim in shape:
        if dim > MAX_DIMENSION:
            raise ValueError(f'Invalid ndarray dimension={dim}')
    element_count = math.prod(shape)
    expected_bytes = element_count * dtype.itemsize
    if expected_bytes > max_bytes:
        raise ValueError(f'Decoded ndarray size {expected_bytes} exceeds limit {max_bytes}')
    if len(raw) - header_size != expected_bytes:
        raise ValueError(
            f'ndarray byte length mismatch: got {len(raw) - header_size}, expected {expected_bytes}'
        )
    return np.frombuffer(raw[header_size:], dtype=dtype).reshape(shape).copy()
