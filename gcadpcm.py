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

# --- GC/DSP ADPCM format constants ------------------------------------------
SAMPLES_PER_FRAME = 14        # decoded samples produced by one 8-byte frame
NIBBLES_PER_FRAME = 16        # nibbles consumed by one frame (1 scale byte + 14 samples)
MIN_SIGNED_16 = -32768        # lowest possible 16-bit PCM sample
MAX_SIGNED_16 = 32767         # highest possible 16-bit PCM sample
BASE_SCALE_MULTIPLIER = 2048  # base of the per-frame scale (shifted by the scale nibble)
OUTPUT_SHIFT_AMOUNT = 11      # fixed right-shift applied to the corrected value
OUTPUT_ROUNDING_HALF = 1024   # half of 2^OUTPUT_SHIFT_AMOUNT, added before rounding
WAV_BITS_PER_SAMPLE = 16      # bit depth used by to_wav16
WAV_FORMAT_PCM = 1            # WAV fmt chunk: audio format 1 == PCM


try:
    from numba import njit
    _HAS_NUMBA = True
except Exception:
    _HAS_NUMBA = False


def _clamp_to_16_bit(value):
    """Clamp an arbitrary int into the signed 16-bit PCM range."""
    if value > MAX_SIGNED_16:
        return MAX_SIGNED_16
    if value < MIN_SIGNED_16:
        return MIN_SIGNED_16
    return value


def _sign_extend_nibble(nibble_value):
    """Sign-extend a 4-bit unsigned nibble to a signed int (-8..7)."""
    masked = nibble_value & 0x0F
    return masked - 16 if masked >= 8 else masked


def nibble_count_to_sample_count(nibble_count):
    """How many decoded samples are held by `nibble_count` raw nibbles."""
    full_frames = nibble_count // NIBBLES_PER_FRAME
    remaining_nibbles = nibble_count % NIBBLES_PER_FRAME
    # The first 2 remaining nibbles are a new scale byte, not samples
    extra_samples = 0 if remaining_nibbles < 2 else remaining_nibbles - 2
    return SAMPLES_PER_FRAME * full_frames + extra_samples


def sample_count_to_nibble_count(sample_count):
    """How many raw nibbles are needed to encode `sample_count` samples."""
    full_frames = sample_count // SAMPLES_PER_FRAME
    remaining_samples = sample_count % SAMPLES_PER_FRAME
    remaining_nibbles = remaining_samples + 2  # +1 scale byte (2 nibbles)
    return NIBBLES_PER_FRAME * full_frames + remaining_nibbles


def sample_count_to_byte_count(sample_count):
    """How many raw bytes are needed to encode `sample_count` samples."""
    return (sample_count_to_nibble_count(sample_count) + 1) // 2


def decode(adpcm_bytes, coefficients, sample_count=None, previous_sample_1=0, previous_sample_2=0):
    """Decode an ADPCM byte stream to a list of int16 samples.

    adpcm_bytes        : raw ADPCM frames (bytes or bytearray)
    coefficients       : 16 signed short predictor coefficients
    sample_count       : how many samples to emit (default: everything in adpcm_bytes)
    previous_sample_1  : most recent history value (continues an in-progress stream)
    previous_sample_2  : second most recent history value
    """
    if sample_count is None:
        sample_count = nibble_count_to_sample_count(len(adpcm_bytes) * 2)

    if _HAS_NUMBA:
        adpcm_array = (
            np.frombuffer(adpcm_bytes, dtype=np.uint8)
            if isinstance(adpcm_bytes, (bytes, bytearray))
            else np.ascontiguousarray(adpcm_bytes, dtype=np.uint8)
        )
        coefficient_array = np.ascontiguousarray(coefficients, dtype=np.int16)
        return _decode_with_numba(
            adpcm_array,
            coefficient_array,
            int(sample_count),
            int(previous_sample_1),
            int(previous_sample_2),
        )

    pcm_samples = [0] * sample_count
    history_1 = previous_sample_1
    history_2 = previous_sample_2
    output_position = 0
    input_position = 0
    total_bytes = len(adpcm_bytes)
    frame_count = (sample_count + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME

    for _ in range(frame_count):
        if input_position >= total_bytes:
            break
        scale_byte = adpcm_bytes[input_position]
        input_position += 1
        # scale nibble selects 2^n * BASE_SCALE_MULTIPLIER as the frame scale
        scale = (1 << (scale_byte & 0x0F)) * BASE_SCALE_MULTIPLIER
        predictor_index = (scale_byte >> 4) & 0x0F
        coefficient_1 = coefficients[predictor_index * 2]
        coefficient_2 = coefficients[predictor_index * 2 + 1]

        samples_to_read = min(SAMPLES_PER_FRAME, sample_count - output_position)
        for sample_index in range(samples_to_read):
            if sample_index % 2 == 0:
                if input_position >= total_bytes:
                    break
                delta = _sign_extend_nibble(adpcm_bytes[input_position] >> 4)
            else:
                if input_position >= total_bytes:
                    break
                delta = _sign_extend_nibble(adpcm_bytes[input_position])
                input_position += 1
            distance = scale * delta
            predicted = coefficient_1 * history_1 + coefficient_2 * history_2
            corrected = predicted + distance
            # fixed-point divide by 2^OUTPUT_SHIFT_AMOUNT, rounding half up
            scaled_sample = (corrected + OUTPUT_ROUNDING_HALF) >> OUTPUT_SHIFT_AMOUNT
            history_2 = history_1
            history_1 = _clamp_to_16_bit(scaled_sample)
            if output_position < sample_count:
                pcm_samples[output_position] = history_1
            output_position += 1
    return pcm_samples


def to_wav16(channels, sample_rate, output_path):
    """Write `channels` (list of int16 sequences) as a 16-bit PCM WAV file."""
    channel_count = len(channels)
    max_samples = max(len(channel) for channel in channels)
    interleaved = np.empty((max_samples, channel_count), dtype=np.int16)
    for channel_index, channel in enumerate(channels):
        channel_array = np.asarray(channel, dtype=np.int16)
        interleaved[:len(channel_array), channel_index] = channel_array
    pcm_bytes = interleaved.tobytes()
    with open(output_path, "wb") as wav_file:
        wav_file.write(b"RIFF")
        wav_file.write(struct.pack("<I", 36 + len(pcm_bytes)))
        wav_file.write(b"WAVEfmt ")
        # fmt chunk: size, PCM, channels, rate, byte_rate, block_align, bits
        wav_file.write(struct.pack(
            "<IHHIIHH",
            16,
            WAV_FORMAT_PCM,
            channel_count,
            sample_rate,
            sample_rate * channel_count * WAV_BITS_PER_SAMPLE,
            channel_count * WAV_BITS_PER_SAMPLE,
            WAV_BITS_PER_SAMPLE,
        ))
        wav_file.write(b"data")
        wav_file.write(struct.pack("<I", len(pcm_bytes)))
        wav_file.write(pcm_bytes)
    return output_path


if _HAS_NUMBA:

    @njit(cache=True)
    def _decode_with_numba(adpcm_array, coefficient_array, sample_count, previous_sample_1, previous_sample_2):
        pcm_samples = np.zeros(sample_count, dtype=np.int16)
        history_1 = np.int64(previous_sample_1)
        history_2 = np.int64(previous_sample_2)
        output_position = np.int64(0)
        input_position = np.int64(0)
        total_bytes = adpcm_array.shape[0]
        frame_count = (sample_count + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME
        for _ in range(frame_count):
            if input_position >= total_bytes:
                break
            scale_byte = adpcm_array[input_position]
            input_position += 1
            scale = np.int64(1 << int(scale_byte & 0x0F)) * BASE_SCALE_MULTIPLIER
            predictor_index = np.int64((scale_byte >> 4) & 0x0F)
            coefficient_1 = np.int64(coefficient_array[predictor_index * 2])
            coefficient_2 = np.int64(coefficient_array[predictor_index * 2 + 1])
            samples_to_read = min(SAMPLES_PER_FRAME, sample_count - output_position)
            for sample_index in range(samples_to_read):
                if sample_index % 2 == 0:
                    if input_position >= total_bytes:
                        break
                    delta = np.int64(adpcm_array[input_position] >> 4)
                else:
                    if input_position >= total_bytes:
                        break
                    delta = np.int64(adpcm_array[input_position] & 0x0F)
                    input_position += 1
                if delta >= 8:
                    delta -= 16
                corrected = coefficient_1 * history_1 + coefficient_2 * history_2 + scale * delta
                scaled_sample = np.int64((corrected + OUTPUT_ROUNDING_HALF) >> OUTPUT_SHIFT_AMOUNT)
                history_2 = history_1
                if scaled_sample > MAX_SIGNED_16:
                    history_1 = np.int64(MAX_SIGNED_16)
                elif scaled_sample < MIN_SIGNED_16:
                    history_1 = np.int64(MIN_SIGNED_16)
                else:
                    history_1 = scaled_sample
                if output_position < sample_count:
                    pcm_samples[output_position] = history_1
                output_position += 1
        return pcm_samples
