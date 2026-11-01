# Switch 2 Sound Conversion Scripts

Standalone Python tools for decoding Nintendo Switch 2 sound assets:

- **BFSAR → WAV**: decodes `.bfsar` archives containing "FWAV" (AAL BFWAV) blocks,
  handling both plain PCM and 4-bit GC/DSP ADPCM, with loop info where present.
- **NxOpus → Ogg**: repacks Nintendo's `NOP` `.opus` container (standard and
  SE/multistream variants) into standard Ogg Opus. No transcoding — the raw Opus
  packets are passed through unchanged.

## Files

| File | Purpose |
|---|---|
| `convert_all_bfsar.py` | Batch entry point: decodes every top-level `.bfsar` in a Sound directory |
| `decode_bfsar.py` | BFSAR / FWAV block parser and per-block WAV writer |
| `gcadpcm.py` | Nintendo 4-bit GC/DSP ADPCM decoder (Numba fast path, pure-Python fallback) |
| `convert_all_OST.py` | Batch entry point: converts every top-level `.opus` in a stream directory |
| `nop2ogg.py` | NxOpus container parser and Ogg page writer |

## Usage

Each entry-point script contains `FILE_PATH` / `OUTPUT_PATH` placeholders —
replace them with your own paths before running, e.g.:

```bat
python convert_all_bfsar.py
python convert_all_OST.py
```

Output WAV files are written under `out\<archive name>\` and OGG files are
written directly into the chosen output directory.

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