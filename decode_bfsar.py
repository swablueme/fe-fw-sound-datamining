#!/usr/bin/env python3
"""
Decoder for Nintendo Switch 2 "FWAV" (AAL BFWAV, versions 0x10100/0x10200)
GC/DSP ADPCM sound assets inside .bfsar archives.

Reference: https://nintendo-formats.com/libs/nw/bfwav.html
Codec: 4-bit GC/DSP ADPCM, 8-byte frame = 14 samples, per-channel coefs table.

Layout:
  FWAV block:
    +0x00 "FWAV"  +0x04 u32 total size  +0x08 u32 (size incl header)
    +0x0C u32 tripletCount
    +0x10 triplets[]  each: u32 id, u32 offset, u32 size  (offsets rel. FWAV base)
        0x7000 -> INFO block,  0x7001 -> DATA block
  INFO block:
    +0x00 "INFO"  +0x04 u32 size
    +0x08 u8 sampleFormat (2=ADPCM)  +0x09 u8 isLooped
    +0x0C u32 sampleRate
    +0x10 u32 loopStartSample
    +0x14 u32 totalSamples
    +0x18 u32 version/reserved
    +0x1C u32 channelCount
    +0x20 per-channel info refs (8 bytes each, 0x7100, rel. to 0x1C field)
    Per-channel info block (20 bytes, at referenced offset):
        +0x00 ref 0x1F00 -> channel ADPCM data, rel. to DATA block body
        +0x08 ref 0x0300 -> channel DSP ADPCM info, rel. to this block
        +0x10 4 bytes padding
    DSP ADPCM info (46 bytes):
        +0x00 16 x i16 coefficients
        +0x20 ADPCM context (main): i16 header, i16 hist1, i16 hist2
        +0x26 ADPCM context (loop): i16 header, i16 hist1, i16 hist2
        +0x28 2 bytes unused
  DATA block:
    +0x00 "DATA"  +0x04 u32 size
    +0x08 payload: zero padding, then per-channel ADPCM streams SEQUENTIALLY
        (channel offsets come from the per-channel 0x1F00 references)

FYI all filenaming is broken, the only thing I have tested to work is the audio conversion
"""
from gcadpcm import decode, to_wav16
import sys
import os
import struct
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def u16(data, o): return struct.unpack_from("<H", data, o)[0]
def u32(data, o): return struct.unpack_from("<I", data, o)[0]


def i16(data, o):
    v = u16(data, o)
    return v - 0x10000 if v >= 0x8000 else v


def read_fwav(data, base, outdir, name):
    assert data[base:base + 4] == b"FWAV", hex(base)
    ntrip = u32(data, base + 0x10)
    off = base + 0x14
    blocks = {}
    for _ in range(ntrip):
        tid, toff, tsz = u32(data, off), u32(data, off + 4), u32(data, off + 8)
        blocks[tid] = (base + toff, tsz)
        off += 12

    info, _ = blocks[0x7000]
    dat, _ = blocks[0x7001]
    assert data[info:info + 4] == b"INFO" and data[dat:dat + 4] == b"DATA"

    fmt, looped = data[info + 0x08], data[info + 0x09]
    rate = u32(data, info + 0x0C)
    total = u32(data, info + 0x14)
    nch = u32(data, info + 0x1C)
    assert fmt == 2, "expected ADPCM, got fmt=%d" % fmt

    payload = data[dat + 8: dat + 8 + (u32(data, dat + 4))]

    # per-channel info references, table at +0x20, values relative to 0x1C field
    refbase = info + 0x1C
    pcm = []
    print("== %s @0x%X  rate=%d nch=%d total=%d fmt=%d looped=%d =="
          % (name, base, rate, nch, total, fmt, looped))
    for c in range(nch):
        pcref = info + 0x20 + 8 * c
        assert u32(data, pcref) == 0x7100, hex(pcref)
        pinfo = refbase + u32(data, pcref + 4)
        assert u32(data, pinfo) == 0x1F00, hex(pinfo)
        data_off = u32(data, pinfo + 4)          # rel. to DATA body
        assert u32(data, pinfo + 8) == 0x0300, hex(pinfo + 8)
        dsp = pinfo + u32(data, pinfo + 12)  # absolute: DSP ADPCM info block
        coefs = [i16(data, dsp + 2 * i) for i in range(16)]
        hdr = u16(data, dsp + 0x20)
        h1, h2 = i16(data, dsp + 0x22), i16(data, dsp + 0x24)
        print("  ch%d: data@payload+%#06X coefs[0..2]=%s ctx_hdr=%#04X hist=(%d,%d)"
              % (c, data_off, coefs[:3], hdr, h1, h2))

        # size of this channel's data = next channel's data offset (or payload end)
        if c + 1 < nch:
            pn = info + 0x20 + 8 * (c + 1)
            pinfo_n = refbase + u32(data, pn + 4)
            next_off = u32(data, pinfo_n + 4)
            chunk = payload[data_off:next_off]
        else:
            # last channel: take until end of payload (drop trailing padding)
            frames = (len(payload) - data_off) // 8
            chunk = payload[data_off:data_off + frames * 8]
        if len(chunk) % 8:
            chunk = chunk[:len(chunk) - len(chunk) % 8]
            print("  ch%d: WARNING truncated %d bytes" % (c, len(chunk)))

        p = decode(chunk, coefs, None, h1, h2)
        if not isinstance(p, np.ndarray):
            p = np.asarray(p, dtype=np.int16)
        pcm.append(p)
        n = len(p)
        nz = int(np.count_nonzero(p))
        rms = float(np.sqrt(np.mean(p.astype(np.float64) ** 2))) if n else 0.0
        print("  ch%d: %d samples (%.3f s)  min=%d max=%d rms=%.1f nonzero=%d"
              % (c, n, n / rate if rate else 0, int(p.min()), int(p.max()), rms, nz))

    # pad shorter channels to the longest
    nmax = max(len(p) for p in pcm)
    pcm = [np.pad(p, (0, nmax - len(p))) if len(p) < nmax else p for p in pcm]

    path = os.path.join(outdir, name + ".wav")
    to_wav16(pcm, rate, path)
    print("  -> %s" % path)
    return path


def find_fwav(data, start=0):
    idxs = []
    o = data.find(b"FWAV", start)
    while o != -1:
        # sanity: u32 total plausible
        ntrip = u32(data, o + 0x10)
        if 1 <= ntrip <= 16:
            idxs.append(o)
        o = data.find(b"FWAV", o + 4)
    return idxs

