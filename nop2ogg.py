"""Convert Switch 2 NxOpus (NOP) .opus files to standard Ogg Opus.

Handles both standard (1/2ch) and SE/multistream (6ch 5.1) variants.
No transcoding - raw Opus packets are passed through unchanged.

Reference implementations:
1) https://github.com/vgmstream/vgmstream/blob/master/src/meta/opus.c
2) https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/oggparseopus.c
"""
import os
import struct
import sys

# --- NxOpus container constants ---------------------------------------------
NXOPUS_STANDARD_MAGIC = 0x80000001  # u32 LE at file start: standard 1/2ch files
NXOPUS_MULTISTREAM_MAGIC = 0x80000005  # u32 at +0x20: SE/multistream 6ch files
NXOPUS_STANDARD_DATA_OFFSET = 0x20  # where the packet list starts (standard files)
NXOPUS_MULTISTREAM_DATA_OFFSET = 0x32  # where the packet list starts (SE files)
NXOPUS_DATA_SECTION_TYPE = 0x80000004  # u32 marking the start of the packet list
NXOPUS_MINIMUM_FILE_SIZE = 0x28  # anything shorter cannot hold the required header

# --- Opus / Ogg constants ----------------------------------------------------
OPUS_FRAME_SIZE_SAMPLES = 960  # 20 ms at Opus' fixed 48 kHz internal rate
OPUS_OGG_PAGE_SIZE_PACKETS = 40  # opus packets grouped per OGG page
OGG_PAGE_TYPE_BOS = 0x02  # "beginning of stream" flag for the OpusHead page
OGG_PAGE_TYPE_NORMAL = 0x00
OGG_SERIAL_NUMBER = 1  # arbitrary OGG stream serial number
OGG_CRC_POLYNOMIAL = 0x04C11DB7  # libogg ogg_crc_look1: MSB-first, init 0, no reflect/XOR
MAX_OGG_SEGMENT_SIZE = 255  # max byte count a single lacing value can represent
OGG_PAGE_CRC_FIELD_OFFSET = 22  # CRC is written at this offset in the page
OGG_PAGE_CRC_FIELD_SIZE = 4


def _make_ogg_crc_table():
    """Build the 256-entry lookup table for the OGG CRC-32 variant."""
    crc_table = []
    for entry_index in range(256):
        entry = entry_index << 24
        for _ in range(8):
            if entry & 0x80000000:
                entry = (entry << 1) ^ OGG_CRC_POLYNOMIAL
            else:
                entry = entry << 1
            entry &= 0xFFFFFFFF
        crc_table.append(entry)
    return crc_table


_OGG_CRC_TABLE = _make_ogg_crc_table()


def ogg_crc(data):
    """Compute the OGG CRC-32 (not the usual zlib CRC) over `data`."""
    crc = 0
    for byte in data:
        crc = _OGG_CRC_TABLE[((crc >> 24) & 0xFF) ^ byte] ^ ((crc << 8) & 0xFFFFFFFF)
    return crc & 0xFFFFFFFF


def _segment_lacing(packets):
    """Split opus packet byte-lengths into OGG segment-lacing values.

    Each lacing value holds up to 255 bytes; a value of exactly 255 must be
    followed by a 0x00 terminator segment, per the Ogg specification.
    """
    lacing_values = []
    for packet_length in packets:
        remaining = packet_length
        while remaining > 0:
            lacing_values.append(min(remaining, MAX_OGG_SEGMENT_SIZE))
            remaining -= MAX_OGG_SEGMENT_SIZE
            if remaining == 0 and lacing_values[-1] == MAX_OGG_SEGMENT_SIZE:
                lacing_values.append(0)
    return lacing_values


def ogg_page(page_type, granule_position, serial_number, page_sequence, lacing_values, page_body):
    """Build one OGG page.

    Layout: "OggS"(4) version(1) type(1) granule(8) serial(4) seq(4)
            CRC(4) lacing_count(1) lacing(N) payload(M)
    The CRC field (offset 22) is computed over the whole page with that
    field zeroed. No inter-page padding: the next page starts right after.
    """
    header = b'OggS\x00' + bytes([page_type]) + \
        struct.pack('<QII', granule_position, serial_number, page_sequence)
    page = header + b'\x00\x00\x00\x00' + \
        bytes([len(lacing_values)]) + bytes(lacing_values) + page_body
    crc = ogg_crc(page)
    page = page[:OGG_PAGE_CRC_FIELD_OFFSET] + \
        struct.pack('<I', crc) + page[OGG_PAGE_CRC_FIELD_OFFSET + OGG_PAGE_CRC_FIELD_SIZE:]
    return page


def convert(nop_file_path, ogg_file_path):
    """Convert one NxOpus .opus file to a standard Ogg Opus file.

    Returns (opus_packet_count, channel_count, sample_rate, pre_skip_samples).
    """
    with open(nop_file_path, 'rb') as nop_file:
        nop_data = nop_file.read()
    if len(nop_data) < NXOPUS_MINIMUM_FILE_SIZE:
        raise ValueError(f"{nop_file_path}: too short ({len(nop_data)} bytes)")

    file_magic = struct.unpack_from('<I', nop_data, 0x00)[0]
    if file_magic != NXOPUS_STANDARD_MAGIC:
        raise ValueError(f"{nop_file_path}: bad magic {file_magic:#010x}")

    channel_count = nop_data[0x09]
    sample_rate = struct.unpack_from('<I', nop_data, 0x0C)[0]
    data_section_offset = struct.unpack_from('<I', nop_data, 0x10)[0]
    pre_skip_samples = struct.unpack_from('<I', nop_data, 0x1C)[0]

    if channel_count not in (1, 2, 6):
        raise ValueError(f"{nop_file_path}: unsupported channel count {channel_count}")

    stream_count = None
    coupled_stream_count = None
    channel_mapping = None
    if channel_count == 6:
        if data_section_offset != NXOPUS_MULTISTREAM_DATA_OFFSET:
            raise ValueError(
                f"{nop_file_path}: SE file, expected data_offset="
                f"{NXOPUS_MULTISTREAM_DATA_OFFSET:#x} got {data_section_offset:#x}")
        multistream_type = struct.unpack_from('<I', nop_data, 0x20)[0]
        if multistream_type != NXOPUS_MULTISTREAM_MAGIC:
            raise ValueError(
                f"{nop_file_path}: bad multistream type {multistream_type:#010x}")
        stream_count = nop_data[0x28]
        coupled_stream_count = nop_data[0x29]
        channel_mapping = list(nop_data[0x2C:0x32])
    else:
        if data_section_offset != NXOPUS_STANDARD_DATA_OFFSET:
            raise ValueError(
                f"{nop_file_path}: standard file, expected data_offset="
                f"{NXOPUS_STANDARD_DATA_OFFSET:#x} got {data_section_offset:#x}")

    # Data section starts at data_section_offset
    if data_section_offset + 8 > len(nop_data):
        raise ValueError(f"{nop_file_path}: too short for data section")
    data_section_type = struct.unpack_from('<I', nop_data, data_section_offset)[0]
    if data_section_type != NXOPUS_DATA_SECTION_TYPE:
        raise ValueError(f"{nop_file_path}: bad data section type {data_section_type:#010x}")
    data_section_size = struct.unpack_from('<I', nop_data, data_section_offset + 4)[0]

    packet_list_start = data_section_offset + 8
    packet_list_end = min(packet_list_start + data_section_size, len(nop_data))

    # Parse the packet list: repeated [u32 BE size][u32 BE final_range][size bytes opus]
    packet_position = packet_list_start
    opus_packets = []
    while packet_position + 8 <= packet_list_end:
        packet_size, final_range_code = struct.unpack_from(
            '>II', nop_data, packet_position)
        packet_position += 8
        if packet_size == 0 or packet_position + packet_size > packet_list_end:
            break
        opus_packets.append(nop_data[packet_position:packet_position + packet_size])
        packet_position += packet_size

    if not opus_packets:
        raise ValueError(f"{nop_file_path}: no opus packets found")

    # Build OpusHead
    OPUS_HEAD_VERSION = 1
    OPUS_GAIN_DEFAULT = 0  # uint16, 0 == no gain adjustment
    OPUS_MAPPING_FAMILY_NONE = 0  # standard files: no channel mapping table
    OPUS_MAPPING_FAMILY_MULTISTREAM = 1  # >2ch files require the mapping table
    if channel_count == 6:
        # Multistream OpusHead (ffmpeg/libopus layout):
        # magic(8) version(1) channel_count(1) pre_skip(2) input_sample_rate(4)
        # gain(2) mapping_family(1) stream_count(1) coupled_stream_count(1) mapping[N]
        opus_head = b'OpusHead' + struct.pack(
            '<BBHIHBBB',
            OPUS_HEAD_VERSION,
            channel_count,
            pre_skip_samples,
            sample_rate,
            OPUS_GAIN_DEFAULT,
            OPUS_MAPPING_FAMILY_MULTISTREAM,
            stream_count,
            coupled_stream_count,
        )
        opus_head += bytes(channel_mapping)
    else:
        # Standard OpusHead:
        # magic(8) ver(1) channels(1) pre_skip(2) input_sample_rate(4)
        # gain(2) mapping_family(1)
        opus_head = b'OpusHead' + struct.pack(
            '<BBHIHB',
            OPUS_HEAD_VERSION,
            channel_count,
            pre_skip_samples,
            sample_rate,
            OPUS_GAIN_DEFAULT,
            OPUS_MAPPING_FAMILY_NONE,
        )

    # OpusTags: magic, vendor_len(0), comment_count(0)
    opus_tags = b'OpusTags' + struct.pack('<I', 0) + struct.pack('<I', 0)

    # Build OGG pages
    pages = [
        ogg_page(
            OGG_PAGE_TYPE_BOS, 0, OGG_SERIAL_NUMBER, 0,
            _segment_lacing([len(opus_head)]), opus_head,
        ),
        ogg_page(
            OGG_PAGE_TYPE_NORMAL, 0, OGG_SERIAL_NUMBER, 1,
            _segment_lacing([len(opus_tags)]), opus_tags,
        ),
    ]
    page_sequence = 2
    # Granule counts are in 48 kHz samples; start at pre_skip, not 0
    granule_position = pre_skip_samples
    for batch_start in range(0, len(opus_packets), OPUS_OGG_PAGE_SIZE_PACKETS):
        packet_batch = opus_packets[
            batch_start:batch_start + OPUS_OGG_PAGE_SIZE_PACKETS]
        granule_position += len(packet_batch) * OPUS_FRAME_SIZE_SAMPLES
        batch_lacing = _segment_lacing([len(p) for p in packet_batch])
        batch_body = b''.join(packet_batch)
        pages.append(ogg_page(
            OGG_PAGE_TYPE_NORMAL, granule_position, OGG_SERIAL_NUMBER,
            page_sequence, batch_lacing, batch_body,
        ))
        page_sequence += 1

    with open(ogg_file_path, 'wb') as ogg_file:
        ogg_file.write(b''.join(pages))
    return len(opus_packets), channel_count, sample_rate, pre_skip_samples


def main():
    source_directory = sys.argv[1] if len(sys.argv) > 1 else '.'
    output_directory = sys.argv[2] if len(sys.argv) > 2 else os.path.join(source_directory, 'ogg')
    os.makedirs(output_directory, exist_ok=True)
    opus_files = sorted(
        filename for filename in os.listdir(source_directory)
        if filename.lower().endswith('.opus')
    )
    if not opus_files:
        print("No .opus files found.")
        return
    converted_count = 0
    failed_count = 0
    for file_number, filename in enumerate(opus_files, 1):
        input_path = os.path.join(source_directory, filename)
        output_path = os.path.join(
            output_directory, os.path.splitext(filename)[0] + '.ogg')
        try:
            packet_count, channel_count, sample_rate, pre_skip = convert(
                input_path, output_path)
            converted_count += 1
            if len(opus_files) > 200:
                print(
                    f"[{file_number}/{len(opus_files)}] {filename} -> "
                    f"{packet_count} packets, {channel_count}ch @ "
                    f"{sample_rate}Hz, pre_skip={pre_skip}")
        except Exception as conversion_error:
            failed_count += 1
            print(f"FAIL {filename}: {conversion_error}")
    print(f"Done: {converted_count} converted, {failed_count} failed. Output: {output_directory}")


if __name__ == '__main__':
    main()
