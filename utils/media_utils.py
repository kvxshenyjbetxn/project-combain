# utils/media_utils.py

import os
import random
import logging
import contextlib
import sys
import ffmpeg

logger = logging.getLogger("TranslationApp")

def concatenate_audio_files(audio_files: list, output_path: str) -> bool:
    if not audio_files:
        logger.error("No audio files provided for concatenation.")
        return False

    logger.info(f"Concatenating {len(audio_files)} audio files into {output_path}...")
    concat_list_path = os.path.join(os.path.dirname(output_path), f"audio_concat_{random.randint(1000,9999)}.txt")
    
    try:
        with open(concat_list_path, "w", encoding='utf-8') as f:
            for file_path in audio_files:
                safe_path = file_path.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        (
            ffmpeg
            .input(concat_list_path, format='concat', safe=0)
            .output(output_path, c='copy')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        logger.info(f"Successfully concatenated audio to {output_path}")
        return True
    except ffmpeg.Error as e:
        logger.error(f"Failed to concatenate audio files. FFmpeg stderr:\n{e.stderr.decode(errors='ignore')}")
        return False
    finally:
        if os.path.exists(concat_list_path):
            os.remove(concat_list_path)

@contextlib.contextmanager
def suppress_stdout_stderr():
    with open(os.devnull, 'w', encoding='utf-8') as fnull:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = fnull, fnull
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr