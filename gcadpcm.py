#!/usr/bin/env python3
"""
GC / DSP ADPCM decoder (Nintendo 4-bit ADPCM), ported from
VGAudio's Codecs/GcAdpcm/GcAdpcmDecoder.cs (https://github.com/thealexbarney/vgaudio)

Frame layout (8 bytes = 14 samples):
    byte 0   : high nibble = predictor index (0..7), low nibble = scale bits
    byte 1-7 : 14 4-bit samples (high nibble first)
"""
import struct

import numpy as np

try:
    from numba import njit
    _HAS_NUMBA = True
except Exception:
    _HAS_NUMBA = False


def _clamp16(x):
    if x > 32767:
        return 32767
    if x < -32768:
        return -32768
    return x


def _sign_extend_nibble(n):
    n &= 0xF
    return n - 16 if n >= 8 else n


def nibble_count_to_sample_count(nibble_count):
    frames = nibble_count // 16
    extra = nibble_count % 16
    extra_samples = 0 if extra < 2 else extra - 2
    return 14 * frames + extra_samples


def sample_count_to_nibble_count(sample_count):
    frames = sample_count // 14
    extra = sample_count % 14
    extra_nibbles = extra + 2
    return 16 * frames + extra_nibbles


def sample_count_to_byte_count(sample_count):
    return (sample_count_to_nibble_count(sample_count) + 1) // 2


def decode(adpcm, coefs, sample_count=None, history1=0, history2=0):
    """Decode an ADPCM byte stream to a list of int16 samples.

    adpcm  : bytes (raw ADPCM frames)
    coefs  : 16 signed shorts
    """
    if sample_count is None:
        sample_count = nibble_count_to_sample_count(len(adpcm) * 2)

    if _HAS_NUMBA:
        a = np.frombuffer(adpcm, dtype=np.uint8) if isinstance(adpcm, (bytes, bytearray)) else np.ascontiguousarray(adpcm, dtype=np.uint8)
        c = np.ascontiguousarray(coefs, dtype=np.int16)
        return _decode_jit(a, c, int(sample_count), int(history1), int(history2))

    pcm = [0] * sample_count
    h1 = history1
    h2 = history2
    out_idx = 0
    in_idx = 0
    n = len(adpcm)
    frame_count = (sample_count + 13) // 14

    for _ in range(frame_count):
        if in_idx >= n:
            break
        ps = adpcm[in_idx]
        in_idx += 1
        scale = (1 << (ps & 0x0F)) * 2048
        predictor = (ps >> 4) & 0x0F
        c1 = coefs[predictor * 2]
        c2 = coefs[predictor * 2 + 1]

        samples_to_read = min(14, sample_count - out_idx)
        for s in range(samples_to_read):
            if s % 2 == 0:
                if in_idx >= n:
                    break
                a = _sign_extend_nibble(adpcm[in_idx] >> 4)
            else:
                if in_idx >= n:
                    break
                a = _sign_extend_nibble(adpcm[in_idx])
                in_idx += 1
            distance = scale * a
            predicted = c1 * h1 + c2 * h2
            corrected = predicted + distance
            scaled = (corrected + 1024) >> 11
            h2 = h1
            h1 = _clamp16(scaled)
            if out_idx < sample_count:
                pcm[out_idx] = h1
            out_idx += 1
    return pcm


def to_wav16(channels, sample_rate, path):
    """channels: list of int16 sequences (list or ndarray). Writes 16-bit PCM WAV."""
    nch = len(channels)
    ns = max(len(c) for c in channels)
    data = np.empty((ns, nch), dtype=np.int16)
    for i, c in enumerate(channels):
        a = np.asarray(c, dtype=np.int16)
        data[:len(a), i] = a
    data = data.tobytes()
    dsz = len(data)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + dsz))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, nch, sample_rate,
                            sample_rate * nch * 2, nch * 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", dsz))
        f.write(data)
    return path


if _HAS_NUMBA:

    @njit(cache=True)
    def _decode_jit(adpcm, coefs, sample_count, history1, history2):
        pcm = np.zeros(sample_count, dtype=np.int16)
        h1 = np.int64(history1)
        h2 = np.int64(history2)
        out_idx = np.int64(0)
        in_idx = np.int64(0)
        n = adpcm.shape[0]
        frame_count = (sample_count + 13) // 14
        for _ in range(frame_count):
            if in_idx >= n:
                break
            ps = adpcm[in_idx]
            in_idx += 1
            scale = np.int64(1 << int(ps & 0x0F)) * 2048
            predictor = np.int64((ps >> 4) & 0x0F)
            c1 = np.int64(coefs[predictor * 2])
            c2 = np.int64(coefs[predictor * 2 + 1])
            samples_to_read = min(14, sample_count - out_idx)
            for s in range(samples_to_read):
                if s % 2 == 0:
                    if in_idx >= n:
                        break
                    a = np.int64(adpcm[in_idx] >> 4)
                else:
                    if in_idx >= n:
                        break
                    a = np.int64(adpcm[in_idx] & 0x0F)
                    in_idx += 1
                if a >= 8:
                    a -= 16
                corrected = c1 * h1 + c2 * h2 + scale * a
                scaled = np.int64((corrected + 1024) >> 11)
                h2 = h1
                if scaled > 32767:
                    h1 = np.int64(32767)
                elif scaled < -32768:
                    h1 = np.int64(-32768)
                else:
                    h1 = scaled
                if out_idx < sample_count:
                    pcm[out_idx] = h1
                out_idx += 1
        return pcm
