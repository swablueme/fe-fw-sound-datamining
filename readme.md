# Fire Emblem: Fortune's Weave — Sound Data-Mining Scripts

Tools for extracting the **OST (music)** and **sound effects** from a
_Fire Emblem: Fortune's Weave_ `romfs` dump — the kind created by running the
userland **Smile Basic 4** exploit on a Nintendo Switch 2.

## Usage (how to get your files out)

You only need two steps per type of audio.

1. **Get Python** (skip if you already have it): download and install it from
   [python.org](https://www.python.org/downloads/). During installation, tick
   the box that says "Add Python to PATH".
2. **Point the scripts at your dump**: each converter has a line near the top
   with a placeholder you must replace with your own folder address:
   - `convert_all_bfsar.py` → open it in any text editor and replace `FILE_PATH`
     with the address of your `romfs\Sound` folder, e.g.
     `C:\Users\yourname\Downloads\romfs\Sound`
     (in the text file, use forward slashes or double the backslashes, e.g.
     `C:\game\romfs\Sound`).
   - `convert_all_OST.py` → replace `FILE_PATH` with your `romfs\Sound\stream`
     folder and `OUTPUT_PATH` with wherever you want the `.ogg` music files.
3. **Run the script**: in the folder where the scripts live, open a terminal
   (right-click the folder → "Open in Terminal" / "Open in PowerShell") and type:
   ```bat
   python convert_all_bfsar.py
   ```
   and/or
   ```bat
   python convert_all_OST.py
   ```
4. **Collect your audio**:
   - Sound effects appear as `.wav` files in a new `out\` folder, one subfolder
     per archive.
   - Music appears as `.ogg` files in the output folder you chose (play them
     with any modern player such as VLC).

Progress and a final summary (counts of OK / failed files) are printed as it
runs; any failures are also written to a log file next to the output.

## What's in this repo

| File                   | Purpose                                                                     |
| ---------------------- | --------------------------------------------------------------------------- |
| `convert_all_bfsar.py` | Batch entry point: decodes every top-level `.bfsar` in a Sound directory    |
| `decode_bfsar.py`      | BFSAR / FWAV block parser and per-block WAV writer                          |
| `gcadpcm.py`           | Nintendo 4-bit GC/DSP ADPCM decoder (Numba fast path, pure-Python fallback) |
| `convert_all_OST.py`   | Batch entry point: converts every top-level `.opus` in a stream directory   |
| `nop2ogg.py`           | NxOpus container parser and Ogg page writer                                 |

Technical notes: BFSAR archives are parsed for "FWAV" (AAL BFWAV) blocks,
handling both plain PCM and 4-bit GC/DSP ADPCM; `.opus` (NxOpus/NOP) files are
repacked into standard Ogg Opus with **no transcoding** — the raw Opus packets
are passed through unchanged.

## Verification

Spectrographic analysis was performed with
[Spek](https://www.spek.cc/) to inspect the decoded output for artifacts and to
establish that no lossy transcoding had been accidentally performed — the
decoded audio matched the source content (band limits, noise floor, and
silence regions were clean, with no double-encoding artifacts).

## Credits / References

Format documentation and reference implementations consulted while writing
these scripts:

- [nintendo-formats.com — BFWAV](https://nintendo-formats.com/libs/nw/bfwav.html)
- [nintendo-formats.com — BFSAR](https://nintendo-formats.com/libs/nw/bfsar.html)
- [Citric-Composer — Common specs](https://gota7.github.io/Citric-Composer/specs/common.html)
- [Citric-Composer — binaryWAV spec](https://gota7.github.io/Citric-Composer/specs/binaryWav.html)
- [VGAudio — GcAdpcmDecoder.cs](https://github.com/thealexbarney/vgaudio)
  (the GC/DSP ADPCM decoder in `gcadpcm.py` is ported from this)
- [vgmstream — opus.c](https://github.com/vgmstream/vgmstream/blob/master/src/meta/opus.c)
  (NxOpus container layout)
- [FFmpeg — oggparseopus.c](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/oggparseopus.c)
  (NxOpus / Opus-in-Ogg handling)
- [Throne of Knowledge wiki — Editing KTSL2ASBIN files](https://github.com/three-houses-research-team/Throne-of-Knowledge/wiki/Editing-KTSL2ASBIN-files)
  (useful information on what the structure of PCM files might look like)
- [Spek](https://www.spek.cc/) — waveform / spectrogram analysis of decoded output

## AI Assistance Disclaimer

Code generation for this project was assisted by
**Qwen 3.8 27B**, specifically the
[Qwen3.8-27B-Heretic-Ara-16GB-VRAM-IQ4-XS-MTP-GGUF](https://huggingface.co/Bucoid/Qwen3.8-27B-Heretic-Ara-16GB-VRAM-IQ4-XS-MTP-GGUF)
quantized model from Hugging Face.
