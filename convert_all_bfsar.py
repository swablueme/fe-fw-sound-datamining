#!/usr/bin/env python3
"""Decode every top-level .bfsar in the Sound dir (subdirs ignored).

Reuses decode_bfsar.find_fwav / read_fwav. Output Wavs are written to
<working dir>/out/<bfsar_stem>/ as <bfsar_stem>_<index>.wav.
"""
import os
import glob
import traceback

import decode_bfsar

#Replace FILE_PATH string value with the PATH TO YOUR GAME SOUND eg C:\game\romfs\Sound
BASE = r"FILE_PATH"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
os.makedirs(OUT, exist_ok=True)


def main():
    files = sorted(glob.glob(os.path.join(BASE, "*.bfsar")))
    summary = []
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        fdir = os.path.join(OUT, stem)
        os.makedirs(fdir, exist_ok=True)
        data = open(f, "rb").read()
        offs = decode_bfsar.find_fwav(data)
        ok = 0
        fail = 0
        print("\n##### %s  (%d bytes, %d FWAV blocks)" % (stem, len(data), len(offs)))
        for i, off in enumerate(offs):
            name = "%s_%03d" % (stem, i)
            try:
                decode_bfsar.read_fwav(data, off, fdir, name)
                ok += 1
            except Exception as e:
                fail += 1
                print("  !! %s @0x%X FAILED: %r" % (name, off, e))
                traceback.print_exc()
        summary.append((stem, len(data), len(offs), ok, fail))

    print("\n\n================ SUMMARY ================")
    print("%-24s %12s %8s %6s %6s" % ("bfsar", "bytes", "fwav", "ok", "fail"))
    to = to_ok = to_f = 0
    for stem, size, nf, ok, fail in summary:
        print("%-24s %12d %8d %6d %6d" % (stem, size, nf, ok, fail))
        to += nf
        to_ok += ok
        to_f += fail
    print("-" * 60)
    print("total fwav=%d ok=%d fail=%d" % (to, to_ok, to_f))
    print("output dir:", OUT)


if __name__ == "__main__":
    main()
