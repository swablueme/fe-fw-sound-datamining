#!/usr/bin/env python3
"""Decode every top-level .bfsar in the Sound dir (subdirs ignored).

Reuses decode_bfsar.find_fwav / read_fwav. Output Wavs are written to
<working dir>/out/<bfsar_stem>/ as <bfsar_stem>_<index>.wav.
"""
import os
import glob
import traceback

import decode_bfsar

# Replace FILE_PATH string value with the PATH TO YOUR GAME SOUND eg C:\game\romfs\Sound
BASE = r"FILE_PATH"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)


def main():
    bfsar_files = sorted(glob.glob(os.path.join(BASE, "*.bfsar")))
    summary = []
    for bfsar_path in bfsar_files:
        stem = os.path.splitext(os.path.basename(bfsar_path))[0]
        output_dir = os.path.join(OUT, stem)
        os.makedirs(output_dir, exist_ok=True)
        raw_data = open(bfsar_path, "rb").read()
        fwav_offsets = decode_bfsar.find_fwav(raw_data)
        ok = 0
        fail = 0
        print("\n##### %s  (%d bytes, %d FWAV blocks)"
              % (stem, len(raw_data), len(fwav_offsets)))
        for entry_index, fwav_offset in enumerate(fwav_offsets):
            name = "%s_%03d" % (stem, entry_index)
            try:
                decode_bfsar.read_fwav(raw_data, fwav_offset, output_dir, name)
                ok += 1
            except Exception as error:
                fail += 1
                print("  !! %s @0x%X FAILED: %r" % (name, fwav_offset, error))
                traceback.print_exc()
        summary.append((stem, len(raw_data), len(fwav_offsets), ok, fail))

    print("\n\n================ SUMMARY ================")
    print("%-24s %12s %8s %6s %6s" % ("bfsar", "bytes", "fwav", "ok", "fail"))
    total_fwav = total_ok = total_fail = 0
    for stem, size, fwav_count, ok, fail in summary:
        print("%-24s %12d %8d %6d %6d" % (stem, size, fwav_count, ok, fail))
        total_fwav += fwav_count
        total_ok += ok
        total_fail += fail
    print("-" * 60)
    print("total fwav=%d ok=%d fail=%d" % (total_fwav, total_ok, total_fail))
    print("output dir:", OUT)


if __name__ == "__main__":
    main()
