"""Convert Switch 2 NxOpus (NOP) .opus files to standard Ogg Opus.

Handles both standard (1/2ch) and SE/multistream (6ch 5.1) variants.
No transcoding - raw Opus packets are passed through unchanged.

Reference implementations:
1) https://github.com/vgmstream/vgmstream/blob/master/src/meta/opus.c
2_ https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/oggparseopus.c
"""
import os
import struct
import sys


def _make_crc_table():
    # OGG CRC-32 (libogg ogg_crc_look1): MSB-first, poly 0x04C11DB7,
    # init 0, no input/output reflection, no final XOR.
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = (c << 1) ^ 0x04C11DB7 if c & 0x80000000 else c << 1
            c &= 0xFFFFFFFF
        table.append(c)
    return table


_CRC_TABLE = _make_crc_table()


def ogg_crc(data):
    crc = 0
    for b in data:
        crc = _CRC_TABLE[((crc >> 24) & 0xFF) ^ b] ^ ((crc << 8) & 0xFFFFFFFF)
    return crc & 0xFFFFFFFF


def _lacing(packets):
    # Split packet byte-lengths into OGG segment-lacing values (<=255 each, with a
    # trailing 0x00 terminator whenever a value is exactly 255, per the Ogg spec).
    out = []
    for n in packets:
        while n > 0:
            out.append(min(n, 255))
            n -= 255
            if n == 0 and out[-1] == 255:
                out.append(0)
    return out


def ogg_page(htype, granule, serial, seq, lacing, body):
    # OGG page: "OggS"(4) version(1) type(1) granule(8) serial(4) seq(4)
    #           CRC(4) lacing_count(1) lacing(N) payload(M)
    # The CRC field is at offset 22 and is computed over the whole page with that
    # field zeroed. No inter-page padding: the next page starts right after the body.
    header = b'OggS\x00' + bytes([htype]) + \
        struct.pack('<QII', granule, serial, seq)
    page = header + b'\x00\x00\x00\x00' + \
        bytes([len(lacing)]) + bytes(lacing) + body
    crc = ogg_crc(page)
    page = page[:22] + struct.pack('<I', crc) + page[26:]
    return page


def convert(in_path, out_path, serial=1):
    data = open(in_path, 'rb').read()
    if len(data) < 0x28:
        raise ValueError(f"{in_path}: too short ({len(data)} bytes)")

    magic = struct.unpack_from('<I', data, 0x00)[0]
    if magic != 0x80000001:
        raise ValueError(f"{in_path}: bad magic {magic:#010x}")

    channels = data[0x09]
    sample_rate = struct.unpack_from('<I', data, 0x0C)[0]
    data_offset = struct.unpack_from('<I', data, 0x10)[0]
    pre_skip = struct.unpack_from('<I', data, 0x1C)[0]

    if channels not in (1, 2, 6):
        raise ValueError(f"{in_path}: unsupported channel count {channels}")

    stream_count = coupled_count = None
    mapping = None
    if channels == 6:
        if data_offset != 0x32:
            raise ValueError(
                f"{in_path}: SE file, expected data_offset=0x32 got {data_offset:#x}")
        ms_type = struct.unpack_from('<I', data, 0x20)[0]
        if ms_type != 0x80000005:
            raise ValueError(
                f"{in_path}: bad multistream type {ms_type:#010x}")
        stream_count = data[0x28]
        coupled_count = data[0x29]
        mapping = list(data[0x2C:0x32])
    else:
        if data_offset != 0x20:
            raise ValueError(
                f"{in_path}: std file, expected data_offset=0x20 got {data_offset:#x}")

    # Data section at data_offset
    if data_offset + 8 > len(data):
        raise ValueError(f"{in_path}: too short for data section")
    data_type = struct.unpack_from('<I', data, data_offset)[0]
    if data_type != 0x80000004:
        raise ValueError(f"{in_path}: bad data type {data_type:#010x}")
    data_size = struct.unpack_from('<I', data, data_offset + 4)[0]

    frames_start = data_offset + 8
    frames_end = min(frames_start + data_size, len(data))

    # Parse frames: [u32 BE size][u32 BE final_range][size bytes opus]
    pos = frames_start
    packets = []
    while pos + 8 <= frames_end:
        size, final_range = struct.unpack_from('>II', data, pos)
        pos += 8
        if size == 0 or pos + size > frames_end:
            break
        packets.append(data[pos:pos + size])
        pos += size

    if not packets:
        raise ValueError(f"{in_path}: no opus frames found")

    # Build OpusHead
    if channels == 6:
        # Multistream OpusHead (ffmpeg/libopus layout):
        # magic(8) version(1) channel_count(1) pre_skip(2) input_sample_rate(4)
        # gain(2) mapping_family(1) stream_count(1) coupled_stream_count(1) mapping[N]
        opus_head = b'OpusHead' + struct.pack(
            '<BBHIHBBB',
            1,              # version
            channels,       # total channel count
            pre_skip,       # uint16
            sample_rate,    # uint32
            0,              # gain (uint16)
            # mapping_family = 1 (channel mapping; required for >2ch/multistream)
            1,
            stream_count,   # uint8
            coupled_count   # uint8
        )
        opus_head += bytes(mapping)
    else:
        # Standard OpusHead:
        # magic(8) ver(1) channels(1) pre_skip(2) input_sample_rate(4)
        # gain(2) mapping_family(1)
        opus_head = b'OpusHead' + struct.pack(
            '<BBHIHB',
            1,              # version
            channels,
            pre_skip,
            sample_rate,
            0,              # gain
            0               # mapping_family
        )

    # OpusTags: magic, vendor_len(0), comment_count(0)
    opus_tags = b'OpusTags' + struct.pack('<I', 0) + struct.pack('<I', 0)

    # Build OGG pages
    pages = [
        ogg_page(0x02, 0, serial, 0, _lacing([len(opus_head)]), opus_head),
        ogg_page(0x00, 0, serial, 1, _lacing([len(opus_tags)]), opus_tags),
    ]
    seq = 2
    granule = pre_skip  # start at pre_skip, not 0
    BATCH = 40
    for i in range(0, len(packets), BATCH):
        chunk = packets[i:i + BATCH]
        granule += len(chunk) * 960
        lacing = _lacing([len(p) for p in chunk])
        body = b''.join(chunk)
        pages.append(ogg_page(0x00, granule, serial, seq, lacing, body))
        seq += 1

    with open(out_path, 'wb') as f:
        f.write(b''.join(pages))
    return len(packets), channels, sample_rate, pre_skip


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    out_dir = sys.argv[2] if len(
        sys.argv) > 2 else os.path.join(src_dir, 'ogg')
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(f for f in os.listdir(src_dir)
                   if f.lower().endswith('.opus'))
    if not files:
        print("No .opus files found.")
        return
    ok = fail = 0
    for n, name in enumerate(files, 1):
        in_path = os.path.join(src_dir, name)
        out = os.path.join(out_dir, os.path.splitext(name)[0] + '.ogg')
        try:
            frames, ch, sr, ps = convert(in_path, out, serial=1)
            ok += 1
            if len(files) > 200:
                print(
                    f"[{n}/{len(files)}] {name} -> {frames} frames, {ch}ch @ {sr}Hz, pre_skip={ps}")
        except Exception as e:
            fail += 1
            print(f"FAIL {name}: {e}")
    print(f"Done: {ok} converted, {fail} failed. Output: {out_dir}")


if __name__ == '__main__':
    main()
