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


def concatenate_videos(app, video_files, output_path):
    """Concatenate multiple video files into a single output file."""
    if not video_files:
        logger.error("No video files to concatenate.")
        return False
    
    app.update_progress(app._t('phase_final_video'))
    logger.info(f"Concatenating {len(video_files)} video chunks into {output_path}...")

    concat_list_path = os.path.join(os.path.dirname(output_path), "concat_list.txt")
    with open(concat_list_path, "w", encoding='utf-8') as f:
        for file_path in video_files:
            safe_path = file_path.replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    try:
        (
            ffmpeg
            .input(concat_list_path, format='concat', safe=0)
            .output(output_path, c='copy')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        logger.info("Video concatenation successful.")
        os.remove(concat_list_path)
        return True
    except ffmpeg.Error as e:
        logger.error(f"Failed to concatenate videos. FFmpeg stderr:\n{e.stderr.decode()}")
        if os.path.exists(concat_list_path):
            os.remove(concat_list_path)
        return False


def video_chunk_worker(app, images_for_chunk, audio_path, subs_path, output_path, chunk_index, total_chunks):
    """Process a single video chunk using the montage API."""
    app.log_context.parallel_task = 'Video Montage'
    app.log_context.worker_id = f'Chunk {chunk_index}/{total_chunks}'
    try:
        logger.info(f"ЗАПУСК FFMPEG (відео шматок {chunk_index}/{total_chunks}) для аудіо: {os.path.basename(audio_path)}")
        if app.montage_api.create_video(images_for_chunk, audio_path, subs_path, output_path):
            logger.info(f"ЗАВЕРШЕННЯ FFMPEG (відео шматок {chunk_index}/{total_chunks})")
            return output_path
        logger.error(f"ПОМИЛКА FFMPEG (відео шматок {chunk_index}/{total_chunks})")
        return None
    finally:
        if hasattr(app.log_context, 'parallel_task'): del app.log_context.parallel_task
        if hasattr(app.log_context, 'worker_id'): del app.log_context.worker_id


@contextlib.contextmanager
def suppress_stdout_stderr():
    with open(os.devnull, 'w', encoding='utf-8') as fnull:
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = fnull, fnull
        try:
            yield
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr