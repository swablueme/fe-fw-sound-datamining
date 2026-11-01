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

# --- FWAV block IDs ----------------------------------------------------------
BLOCK_ID_INFO = 0x7000          # audio parameter block
BLOCK_ID_DATA = 0x7001          # ADPCM payload block
PER_CHANNEL_INFO_ID = 0x7100    # ID field of each per-channel info reference
PER_CHANNEL_DATA_REF_ID = 0x1F00  # reference to the channel's ADPCM data
PER_CHANNEL_DSP_REF_ID = 0x0300  # reference to the channel's DSP ADPCM info
SAMPLE_FORMAT_ADPCM = 2         # INFO block +0x08: 2 == 4-bit GC/DSP ADPCM
MAX_PLAUSIBLE_TRIPLET_COUNT = 16  # sanity cap when scanning for FWAV blocks


def read_u16(data, offset):
    """Read a little-endian unsigned 16-bit int at `offset`."""
    return struct.unpack_from("<H", data, offset)[0]


def read_u32(data, offset):
    """Read a little-endian unsigned 32-bit int at `offset`."""
    return struct.unpack_from("<I", data, offset)[0]


def read_i16(data, offset):
    """Read a little-endian signed 16-bit int at `offset`."""
    return struct.unpack_from("<h", data, offset)[0]


def read_fwav(data, fwav_offset, output_directory, base_name):
    """Decode one FWAV block and write its WAV file. Returns the written path."""
    assert data[fwav_offset:fwav_offset + 4] == b"FWAV", hex(fwav_offset)

    # Triplet table: each entry is (u32 id, u32 offset, u32 size),
    # offsets relative to the FWAV block base
    triplet_count = read_u32(data, fwav_offset + 0x10)
    triplet_position = fwav_offset + 0x14
    block_offsets = {}
    for _ in range(triplet_count):
        block_id = read_u32(data, triplet_position)
        block_offset = read_u32(data, triplet_position + 4)
        block_offsets[block_id] = fwav_offset + block_offset
        triplet_position += 12

    info_offset = block_offsets[BLOCK_ID_INFO]
    data_block_offset = block_offsets[BLOCK_ID_DATA]
    assert data[info_offset:info_offset + 4] == b"INFO", hex(info_offset)
    assert data[data_block_offset:data_block_offset + 4] == b"DATA", hex(data_block_offset)

    sample_format = data[info_offset + 0x08]
    is_looped = data[info_offset + 0x09]
    sample_rate = read_u32(data, info_offset + 0x0C)
    total_samples = read_u32(data, info_offset + 0x14)
    channel_count = read_u32(data, info_offset + 0x1C)
    assert sample_format == SAMPLE_FORMAT_ADPCM, \
        "expected ADPCM, got fmt=%d" % sample_format

    data_block_size = read_u32(data, data_block_offset + 4)
    adpcm_payload = data[data_block_offset + 8: data_block_offset + 8 + data_block_size]

    # Per-channel info references sit at +0x20, 8 bytes each; their values are
    # relative to the channel_count field at +0x1C, not the block start
    channel_ref_base = info_offset + 0x1C
    pcm_channels = []
    print("== %s @0x%X  rate=%d channels=%d total=%d fmt=%d looped=%d =="
          % (base_name, fwav_offset, sample_rate, channel_count,
             total_samples, sample_format, is_looped))

    for channel_index in range(channel_count):
        channel_ref_offset = info_offset + 0x20 + 8 * channel_index
        assert read_u32(data, channel_ref_offset) == PER_CHANNEL_INFO_ID, \
            hex(channel_ref_offset)
        channel_info_offset = channel_ref_base + read_u32(data, channel_ref_offset + 4)
        assert read_u32(data, channel_info_offset) == PER_CHANNEL_DATA_REF_ID, \
            hex(channel_info_offset)
        channel_data_offset = read_u32(data, channel_info_offset + 4)  # rel. to DATA body
        assert read_u32(data, channel_info_offset + 8) == PER_CHANNEL_DSP_REF_ID, \
            hex(channel_info_offset + 8)
        dsp_info_offset = channel_info_offset + read_u32(data, channel_info_offset + 12)
        dsp_coefficients = [
            read_i16(data, dsp_info_offset + 2 * i) for i in range(16)]
        context_header = read_u16(data, dsp_info_offset + 0x20)
        context_history_1 = read_i16(data, dsp_info_offset + 0x22)
        context_history_2 = read_i16(data, dsp_info_offset + 0x24)
        print("  ch%d: data@payload+%#06X coefs[0..2]=%s ctx_hdr=%#04X hist=(%d,%d)"
              % (channel_index, channel_data_offset, dsp_coefficients[:3],
                 context_header, context_history_1, context_history_2))

        # Size of this channel's data = next channel's data offset (or payload end)
        if channel_index + 1 < channel_count:
            next_channel_ref = info_offset + 0x20 + 8 * (channel_index + 1)
            next_channel_info = channel_ref_base + read_u32(data, next_channel_ref + 4)
            next_channel_data_offset = read_u32(data, next_channel_info + 4)
            channel_chunk = adpcm_payload[channel_data_offset:next_channel_data_offset]
        else:
            # Last channel: take until end of payload (drop trailing padding)
            full_frame_count = (len(adpcm_payload) - channel_data_offset) // 8
            channel_chunk = adpcm_payload[
                channel_data_offset:channel_data_offset + full_frame_count * 8]
        if len(channel_chunk) % 8:
            channel_chunk = channel_chunk[:len(channel_chunk) - len(channel_chunk) % 8]
            print("  ch%d: WARNING truncated %d bytes" % (channel_index, len(channel_chunk)))

        decoded_samples = decode(
            channel_chunk, dsp_coefficients, None,
            context_history_1, context_history_2)
        if not isinstance(decoded_samples, np.ndarray):
            decoded_samples = np.asarray(decoded_samples, dtype=np.int16)
        pcm_channels.append(decoded_samples)
        sample_count = len(decoded_samples)
        non_zero_count = int(np.count_nonzero(decoded_samples))
        rms = float(np.sqrt(np.mean(decoded_samples.astype(np.float64) ** 2))) \
            if sample_count else 0.0
        print("  ch%d: %d samples (%.3f s)  min=%d max=%d rms=%.1f nonzero=%d"
              % (channel_index, sample_count,
                 sample_count / sample_rate if sample_rate else 0,
                 int(decoded_samples.min()), int(decoded_samples.max()),
                 rms, non_zero_count))

    # Pad shorter channels to the longest so the WAV interleaves evenly
    max_channel_length = max(len(samples) for samples in pcm_channels)
    padded_channels = [
        np.pad(samples, (0, max_channel_length - len(samples)))
        if len(samples) < max_channel_length else samples
        for samples in pcm_channels]

    output_path = os.path.join(output_directory, base_name + ".wav")
    to_wav16(padded_channels, sample_rate, output_path)
    print("  -> %s" % output_path)
    return output_path


def find_fwav(data, start=0):
    """Find the offsets of all FWAV blocks in `data` (sanity-checked)."""
    fwav_offsets = []
    search_position = data.find(b"FWAV", start)
    while search_position != -1:
        # Sanity: the triplet count at +0x10 must be plausible
        triplet_count = read_u32(data, search_position + 0x10)
        if 1 <= triplet_count <= MAX_PLAUSIBLE_TRIPLET_COUNT:
            fwav_offsets.append(search_position)
        search_position = data.find(b"FWAV", search_position + 4)
    return fwav_offsets
