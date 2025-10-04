import logging
import os
import sys
import datetime
import random
import re
import subprocess
import threading
import time
from tkinter import messagebox # Потрібно для повідомлень про помилки

# Нові залежності, які ми перевіряли в оригінальному файлі
import whisper
import ffmpeg

# Отримуємо існуючий логер
logger = logging.getLogger("TranslationApp")

# Визначаємо шлях, щоб знайти, куди зберігати лог
from constants.app_settings import DETAILED_LOG_FILE

def format_time(seconds: float) -> str:
    """Конвертує секунди у формат часу для .ass (Г:ХХ:СС.цс)."""
    delta = datetime.timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    centiseconds = int(delta.microseconds / 10000)
    return f"{hours}:{minutes:02}:{seconds_val:02}.{centiseconds:02}"

# --- API для монтажу ---
class MontageAPI:
    def __init__(self, config, app_instance, update_callback):
        self.config = config.get("montage", {})
        self.app = app_instance
        self.update_callback = update_callback
        self.whisper_model_instance = None
        self.codec_map = {
            "libx264 (CPU)": "libx264",
            # Windows/Linux
            "h264_amf (AMD H.264)": "h264_amf",
            "hevc_amf (AMD H.265)": "hevc_amf",
            "av1_amf (AMD AV1)": "av1_amf",
            "h264_nvenc (NVIDIA H.264)": "h264_nvenc",
            "hevc_nvenc (NVIDIA H.265)": "hevc_nvenc",
            # macOS
            "h264_videotoolbox (Apple H.264)": "h264_videotoolbox",
            "hevc_videotoolbox (Apple H.265/HEVC)": "hevc_videotoolbox",
        }

    def _load_whisper_model(self):
        """Завантажує модель Whisper, якщо вона ще не завантажена."""
        if self.whisper_model_instance is None:
            model_name = self.config.get("whisper_model", "base")
            logger.info(f"Whisper -> Запит на завантаження моделі: {model_name}")
            
            download_root = None
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
                download_root = os.path.join(base_path, "whisper_models")
                os.makedirs(download_root, exist_ok=True)
                logger.info(f"Whisper -> Програма запущена як EXE. Шлях для моделей: {download_root}")

            self.update_callback(f"Завантаження моделі Whisper ({model_name})...")
            try:
                self.whisper_model_instance = whisper.load_model(model_name, download_root=download_root)
                logger.info(f"Whisper -> УСПІХ: Модель '{model_name}' успішно завантажена.")
            except Exception as e:
                logger.error(f"Whisper -> ПОМИЛКА: Не вдалося завантажити модель '{model_name}': {e}", exc_info=True)
                self.whisper_model_instance = None
        return self.whisper_model_instance

    def create_subtitles(self, audio_path, output_ass_path, lang_code=None):
        """Створює файл субтитрів .ass з аудіофайлу."""
        backend = self.config.get('whisper_backend', 'standard')
        
        if backend == 'amd':
            return self._create_subtitles_amd(audio_path, output_ass_path, lang_code)
        else:
            return self._create_subtitles_standard(audio_path, output_ass_path)
    
    def _create_subtitles_standard(self, audio_path, output_ass_path):
        """Створює субтитри використовуючи стандартний Whisper (Python library)."""
        logger.info(f"Субтитри (Standard) -> Початок створення субтитрів для {os.path.basename(audio_path)}")
        try:
            model = self._load_whisper_model()
            if not model:
                self.update_callback("Помилка: не вдалося завантажити модель Whisper.")
                logger.error("Субтитри -> ПОМИЛКА: Модель Whisper не завантажена.")
                return False

            logger.info(f"Субтитри -> Початок транскрибації файлу: {os.path.basename(audio_path)}...")

            result = model.transcribe(audio_path, verbose=False)

            if not result or not result.get('segments'):
                logger.error("Субтитри -> ПОМИЛКА: Результат транскрибації порожній або недійсний.")
                self.update_callback("Помилка: транскрибація не повернула результат.")
                return False
            
            logger.info("Субтитри -> Транскрибацію завершено, обробка сегментів...")
            processed_segments = []
            for segment in result['segments']:
                processed_segments.extend(self._split_long_segment(segment))

            self.update_callback(f"Генерація .ass для {os.path.basename(audio_path)}...")
            logger.info(f"Субтитри -> Генерація файлу .ass: {os.path.basename(output_ass_path)}...")
            header = f"""[Script Info]
    Title: {os.path.basename(output_ass_path)}
    ScriptType: v4.00+
    [V4+ Styles]
    Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
    Style: Default,{self.config.get('font_style')},{self.config.get('font_size', 48)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1
    [Events]
    Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
    """
            with open(output_ass_path, 'w', encoding='utf-8') as f:
                f.write(header)
                for segment in processed_segments:
                    start_time = format_time(segment['start'])
                    end_time = format_time(segment['end'])
                    text = segment['text'].strip().replace('\n', ' \\N ')
                    dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}\n"
                    f.write(dialogue_line)
            logger.info(f"Субтитри -> УСПІХ: Файл субтитрів збережено: {output_ass_path}")
            return True
        except Exception as e:
            logger.error(f"Субтитри -> ПОМИЛКА: Непередбачена помилка під час створення субтитрів: {e}", exc_info=True)
            self.update_callback(f"Помилка транскрибації: {e}")
            return False

    def _split_long_segment(self, segment):
        """Розбиває довгий сегмент субтитрів на менші частини."""
        MAX_CHARS = 84 
        text = segment['text'].strip()

        if len(text) <= MAX_CHARS:
            return [segment]

        new_segments = []
        words = text.split()
        current_line = ""
        line_start_time = segment['start']
        total_duration = segment['end'] - segment['start']

        for i, word in enumerate(words):
            if len(current_line + " " + word) > MAX_CHARS:
                line_char_ratio = len(current_line) / len(text)
                line_end_time = line_start_time + (total_duration * line_char_ratio)

                new_segments.append({
                    'start': line_start_time,
                    'end': line_end_time,
                    'text': current_line
                })
                line_start_time = line_end_time
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word

        if current_line:
            new_segments.append({
                'start': line_start_time,
                'end': segment['end'],
                'text': current_line
            })

        return new_segments

    def _create_subtitles_amd(self, audio_path, output_ass_path, lang_code=None):
        """Створює субтитри використовуючи AMD Whisper CLI."""
        logger.info(f"Субтитри (AMD) -> Початок для {os.path.basename(audio_path)}")
        
        try:
            # 1. Визначення шляху до main.exe
            if getattr(sys, 'frozen', False):
                base_path = os.path.dirname(sys.executable)
            else:
                base_path = os.path.dirname(os.path.dirname(__file__))
            
            amd_exe = os.path.join(base_path, "whisper-cli-amd", "main.exe")
            
            if not os.path.exists(amd_exe):
                logger.error(f"AMD Whisper не знайдено: {amd_exe}")
                self.update_callback("Помилка: AMD Whisper CLI не знайдено!")
                return False
            
            # 2. Визначення моделі
            model_name = self.config.get('whisper_model', 'base')
            model_file = f"ggml-{model_name}.bin"
            model_path = os.path.join(base_path, "whisper-cli-amd", model_file)
            
            if not os.path.exists(model_path):
                logger.error(f"Модель AMD Whisper не знайдена: {model_path}")
                self.update_callback(f"Помилка: Модель {model_file} не знайдена в папці whisper-cli-amd!")
                return False
            
            logger.info(f"Використання AMD моделі: {model_file}")
            
            # 3. Параметри запуску
            # Мова - з lang_code (конвертуємо в lowercase) або за замовчуванням 'en'
            if lang_code:
                language = lang_code.lower()
                logger.info(f"Мова транскрипції: {language} (з lang_code: {lang_code})")
            else:
                language = 'en'
                logger.info(f"Мова транскрипції: {language} (за замовчуванням)")
            
            threads = self.config.get('amd_whisper_threads', 4)
            use_gpu = self.config.get('amd_whisper_use_gpu', True)
            
            # 4. Підготовка команди
            cmd = [
                amd_exe,
                '-m', model_path,
                '-f', audio_path,
                '-l', language,
                '-osrt',           # Вивести SRT файл
                '-t', str(threads) # CPU threads
            ]
            
            # Додати GPU параметр тільки якщо use_gpu=True
            if use_gpu:
                cmd.extend(['-gpu', '0'])
                logger.info(f"Режим: GPU (AMD), Threads: {threads}")
            else:
                logger.info(f"Режим: CPUonly, Threads: {threads}")
            
            cmd.append('--no-timestamps')  # Не друкувати в консоль
            
            logger.info(f"Виконання AMD CLI: {' '.join(cmd)}")
            self.update_callback(f"Транскрибація AMD GPU... {os.path.basename(audio_path)}")
            
            # 5. Запуск процесу
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600  # 10 хвилин таймаут для довгих аудіо
            )
            
            if result.returncode != 0:
                logger.error(f"AMD Whisper повернув код помилки {result.returncode}")
                logger.error(f"stderr: {result.stderr}")
                self.update_callback(f"Помилка AMD Whisper: {result.stderr[:200]}")
                return False
            
            # 6. Знайти створений SRT файл
            # AMD CLI створює файл як {audio_path}.srt
            expected_srt = f"{audio_path}.srt"
            
            if not os.path.exists(expected_srt):
                # Спробувати альтернативну назву (без розширення)
                base_name = os.path.splitext(audio_path)[0]
                expected_srt = f"{base_name}.srt"
            
            if not os.path.exists(expected_srt):
                logger.error(f"SRT файл не знайдено після AMD Whisper: очікувалось {expected_srt}")
                logger.error(f"stdout: {result.stdout}")
                return False
            
            logger.info(f"SRT файл знайдено: {expected_srt}")
            
            # 7. Конвертація SRT → ASS
            self.update_callback(f"Конвертація в ASS... {os.path.basename(audio_path)}")
            success = self._convert_srt_to_ass(expected_srt, output_ass_path)
            
            # 8. Видалення тимчасового SRT
            try:
                if os.path.exists(expected_srt):
                    os.remove(expected_srt)
                    logger.info(f"Видалено тимчасовий SRT: {expected_srt}")
            except Exception as e:
                logger.warning(f"Не вдалося видалити тимчасовий SRT: {e}")
            
            if success:
                logger.info(f"Субтитри (AMD) -> УСПІХ: {output_ass_path}")
            
            return success
            
        except subprocess.TimeoutExpired:
            logger.error("AMD Whisper перевищив таймаут (10 хв)")
            self.update_callback("Помилка: таймаут транскрибації AMD")
            return False
        except Exception as e:
            logger.error(f"Субтитри (AMD) -> ПОМИЛКА: {e}", exc_info=True)
            self.update_callback(f"Помилка AMD транскрибації: {e}")
            return False

    def _convert_srt_to_ass(self, srt_path, output_ass_path):
        """Конвертує SRT файл в ASS зі збереженням стилів."""
        try:
            # 1. Парсинг SRT
            segments = self._parse_srt_file(srt_path)
            
            if not segments:
                logger.error("SRT файл порожній або невалідний")
                return False
            
            logger.info(f"Розпарсено {len(segments)} сегментів з SRT")
            
            # 2. Обробка довгих сегментів (використати існуючу логіку)
            processed_segments = []
            for segment in segments:
                processed_segments.extend(self._split_long_segment(segment))
            
            logger.info(f"Після обробки довгих сегментів: {len(processed_segments)} сегментів")
            
            # 3. Генерація ASS (копіювати з _create_subtitles_standard)
            header = f"""[Script Info]
Title: {os.path.basename(output_ass_path)}
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{self.config.get('font_style')},{self.config.get('font_size', 48)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
            
            with open(output_ass_path, 'w', encoding='utf-8') as f:
                f.write(header)
                for segment in processed_segments:
                    start_time = format_time(segment['start'])
                    end_time = format_time(segment['end'])
                    text = segment['text'].strip().replace('\n', ' \\N ')
                    dialogue_line = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}\n"
                    f.write(dialogue_line)
            
            logger.info(f"ASS файл успішно створено: {output_ass_path}")
            return True
            
        except Exception as e:
            logger.error(f"Помилка конвертації SRT→ASS: {e}", exc_info=True)
            return False

    def _parse_srt_file(self, srt_path):
        """Парсить SRT файл у формат segments [{start, end, text}]."""
        segments = []
        
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Розбити на блоки
            blocks = content.strip().split('\n\n')
            
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) < 3:
                    continue  # Пропустити невалідні блоки
                
                try:
                    timecode_line = lines[1]
                    text_lines = lines[2:]
                    
                    # Парсинг таймкодів: "00:00:00,000 --> 00:00:02,500"
                    if ' --> ' not in timecode_line:
                        continue
                    
                    start_str, end_str = timecode_line.split(' --> ')
                    
                    start_sec = self._srt_time_to_seconds(start_str.strip())
                    end_sec = self._srt_time_to_seconds(end_str.strip())
                    text = ' '.join(text_lines).strip()
                    
                    if text:  # Пропустити порожні субтитри
                        segments.append({
                            'start': start_sec,
                            'end': end_sec,
                            'text': text
                        })
                
                except (ValueError, IndexError) as e:
                    logger.warning(f"Не вдалося розпарсити SRT блок: {e}")
                    continue
            
            return segments
            
        except Exception as e:
            logger.error(f"Помилка читання SRT файлу: {e}", exc_info=True)
            return []

    def _srt_time_to_seconds(self, time_str):
        """Конвертує SRT timestamp '00:00:02,500' в секунди (float)."""
        # Формат: HH:MM:SS,mmm
        time_part, ms_part = time_str.split(',')
        h, m, s = map(int, time_part.split(':'))
        ms = int(ms_part)
        
        total_seconds = h * 3600 + m * 60 + s + ms / 1000.0
        return total_seconds

    def create_video(self, image_paths, audio_path, ass_path, output_video_path, task_key=None, chunk_index=None):
        """Створює відео з зображень, аудіо та субтитрів з ефектами, ЗАВЖДИ з переходами."""
        cfg = self.config
        codec_cfg = cfg.get('codec', {})
        video_name = os.path.basename(output_video_path)
        logger.info(f"Монтаж -> Початок створення відео '{video_name}'")
        try:
            self.update_callback(f"Аналіз медіа: {video_name}...", task_key=task_key, chunk_index=chunk_index, progress=0)
            probe = ffmpeg.probe(audio_path)
            audio_duration = float(probe['format']['duration'])
            
            if not image_paths:
                logger.error(f"Монтаж -> ПОМИЛКА: Немає зображень для створення відео '{video_name}'.")
                self.update_callback("Помилка: не обрано зображень для відео.", task_key=task_key, chunk_index=chunk_index)
                return False
            
            num_images = len(image_paths)
            transition_effect = cfg.get('transition_effect', 'fade')
            transition_duration = 1.0 if num_images > 1 and transition_effect != "Без переходу" else 0
            
            total_transition_duration = transition_duration * (num_images - 1)
            image_duration = (audio_duration + total_transition_duration) / num_images if num_images > 0 else 0

            if image_duration <= transition_duration and num_images > 1:
                msg = f"Тривалість аудіо замала. Час картинки ({image_duration:.2f}с) <= часу переходу ({transition_duration:.2f}с)."
                logger.error(f"Монтаж -> ПОМИЛКА: {msg}")
                self.update_callback(f"Помилка: {msg}", task_key=task_key, chunk_index=chunk_index)
                return False

            logger.info(f"Монтаж -> Тривалість аудіо: {audio_duration:.2f}с. Час на картинку: ~{image_duration:.2f}с.")
            self.update_callback(f"Тривалість аудіо: {audio_duration:.2f}с. Час на картинку: ~{image_duration:.2f}с.", task_key=task_key, chunk_index=chunk_index)

            video_streams = []
            output_width, output_height = 1920, 1080
            output_framerate = cfg.get('output_framerate', 30)
            
            MOTION_PERIOD_SECONDS = 20.0 
            ZOOM_PERIOD_SECONDS = 10.0
            motion_period_frames = MOTION_PERIOD_SECONDS * output_framerate
            zoom_period_frames = ZOOM_PERIOD_SECONDS * output_framerate

            for i, img_path in enumerate(image_paths):
                stream = ffmpeg.input(img_path, loop=1, framerate=output_framerate).filter('scale', size=f'{output_width*2}x{output_height*2}')
                
                if cfg.get('motion_enabled', False) or cfg.get('zoom_enabled', False):
                    total_frames = int(image_duration * output_framerate)
                    pan_x_expr, pan_y_expr = "0", "0"
                    
                    if cfg.get('motion_enabled', False):
                        motion_type = cfg.get('motion_type', 'Випадковий')
                        if motion_type == "Випадковий":
                            motion_type = random.choice(["Гойдання (ліво-право)", "Гойдання (верх-низ)", "Гойдання (знак нескінченності)"])
                        
                        amplitude = cfg.get('motion_intensity', 5.0) * 5
                        if motion_type == "Гойдання (ліво-право)": pan_x_expr = f"sin(2*PI*on/{motion_period_frames})*{amplitude}"
                        elif motion_type == "Гойдання (верх-низ)": pan_y_expr = f"sin(2*PI*on/{motion_period_frames})*{amplitude}"
                        elif motion_type == "Гойдання (знак нескінченності)":
                            pan_x_expr = f"sin(2*PI*on/{motion_period_frames})*{amplitude}"
                            pan_y_expr = f"sin(4*PI*on/{motion_period_frames})*{amplitude/2}"

                    zoom_expr = "1.1" if cfg.get('motion_enabled', False) and not cfg.get('zoom_enabled', False) else "1.0"
                    
                    if cfg.get('zoom_enabled', False):
                        intensity_decimal = cfg.get('zoom_intensity', 10.0) / 100.0
                        zoom_speed = cfg.get('zoom_speed', 1.0)
                        base_zoom = 1.0 + intensity_decimal / 2.0
                        amplitude_zoom = intensity_decimal / 2.0
                        zoom_expr = f"{base_zoom} - {amplitude_zoom} * cos(2*PI*{zoom_speed}*on/{zoom_period_frames})"
                    
                    x_final_expr = f"(iw-iw/({zoom_expr}))/2 + {pan_x_expr}"
                    y_final_expr = f"(ih-ih/({zoom_expr}))/2 + {pan_y_expr}"

                    stream = stream.filter('zoompan', z=zoom_expr, d=total_frames, s=f'{output_width}x{output_height}', x=x_final_expr, y=y_final_expr, fps=output_framerate)
                else:
                    stream = stream.filter('scale', size=f'{output_width}x{output_height}', force_original_aspect_ratio='decrease').filter('pad', w=output_width, h=output_height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')

                video_streams.append(stream.trim(duration=image_duration))

            if transition_effect == "Без переходу" or len(video_streams) == 1:
                final_video = ffmpeg.concat(*video_streams, v=1, a=0)
            else:
                processed_stream = video_streams[0]
                for i in range(1, len(video_streams)):
                    offset = i * image_duration - i * transition_duration
                    processed_stream = ffmpeg.filter([processed_stream, video_streams[i]], 'xfade', transition=transition_effect, duration=transition_duration, offset=offset)
                final_video = processed_stream

            final_video_with_subs = final_video.filter('subtitles', filename=ass_path, force_style=f'Fontsize={cfg.get("font_size", 48)}')
            audio_input = ffmpeg.input(audio_path, vn=None)

            selected_codec_display_name = codec_cfg.get('video_codec', 'libx264 (CPU)')
            video_codec = self.codec_map.get(selected_codec_display_name, 'libx264')
            
            output_params = {
                'vcodec': video_codec, 'acodec': 'aac',
                't': audio_duration, 'pix_fmt': 'yuv420p',
                'r': output_framerate
            }
            
            if video_codec == 'libx264':
                output_params['crf'] = codec_cfg.get('x264_crf', 23)
            elif 'nvenc' in video_codec:
                output_params['cq'] = codec_cfg.get('nvenc_cq', 23)
                output_params['rc'] = 'constqp'
            elif 'amf' in video_codec:
                output_params['usage'] = codec_cfg.get('amf_usage', 'transcoding')
                output_params['quality'] = codec_cfg.get('amf_quality', 'balanced')
                rc = codec_cfg.get('amf_rc', 'cqp')
                output_params['rc'] = rc
                if rc != 'cqp': 
                    output_params['b:v'] = codec_cfg.get('amf_bitrate', '8000k')
            elif 'videotoolbox' in video_codec:
                output_params['b:v'] = codec_cfg.get('vt_bitrate', '8000k')

            output_params = {k: v for k, v in output_params.items() if v != '' and v is not None}
            
            self.update_callback(f"Монтаж: '{video_name}' з кодеком '{video_codec}'...", task_key=task_key, chunk_index=chunk_index)
            logger.info(f"Монтаж -> Рендеринг '{video_name}' з кодеком '{video_codec}'. Параметри: {output_params}")

            ffmpeg_executable = "ffmpeg"
            args = ffmpeg.output(final_video_with_subs, audio_input, output_video_path, **output_params).overwrite_output().get_args()
            
            # Додаємо прапорець -nostdin, щоб запобігти зависанню ffmpeg в очікуванні вводу
            process = subprocess.Popen([ffmpeg_executable, '-y', '-nostdin'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='ignore')
            
            total_output_frames = int(audio_duration * output_framerate)
            
            # Додаємо throttling для оновлень GUI
            last_update_time = 0
            update_interval = 0.2 # Оновлювати не частіше, ніж раз на 200 мс

            for line in process.stderr:
                line = line.strip()
                logger.debug(f"FFMPEG -> {line}")

                if line.startswith("frame="):
                    current_time = time.time()
                    if current_time - last_update_time > update_interval:
                        last_update_time = current_time
                        
                        progress = 0.0
                        frame_match = re.search(r"frame=\s*(\d+)", line)
                        if frame_match and total_output_frames > 0:
                            progress = (int(frame_match.group(1)) / total_output_frames) * 100
                        
                        # Формуємо повідомлення для основного логу
                        fps_match = re.search(r"fps=\s*([\d\.]+)", line)
                        fps = fps_match.group(1) if fps_match else "N/A"
                        bitrate_match = re.search(r"bitrate=\s*([\d\.]+\w*bits/s)", line)
                        bitrate = bitrate_match.group(1) if bitrate_match else "N/A"
                        formatted_line = f"Прогрес: {progress:.1f}% | FPS: {fps} | Бітрейт: {bitrate}"
                        
                        # Передаємо дані в callback
                        self.update_callback(formatted_line, task_key=task_key, chunk_index=chunk_index, progress=progress)

            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Монтаж -> ПОМИЛКА FFMPEG для '{video_name}' (код {process.returncode}):\n{stderr}")
                error_shown = False
                if "InitializeEncoder failed" in stderr or "No such device" in stderr or "Error initializing" in stderr or "Error selecting encoder" in stderr:
                    error_message = (f"Не вдалося ініціалізувати апаратний кодек '{video_codec}'.\n"
                                     "Переконайтесь у наявності останніх драйверів та підтримці кодека.\n"
                                     f"Деталі в '{DETAILED_LOG_FILE}'.")
                    if threading.current_thread() is threading.main_thread(): 
                        messagebox.showerror("Помилка апаратного кодека", error_message)
                        error_shown = True
                if not error_shown and threading.current_thread() is threading.main_thread():
                    messagebox.showerror("Помилка FFmpeg", f"Сталася помилка. Деталі в файлі '{DETAILED_LOG_FILE}'.")
                
                # Надсилаємо сповіщення про помилку в Telegram
                task_info = getattr(threading.current_thread(), 'task_info', {})
                self.app.send_telegram_error_notification(
                    task_name=task_info.get('task_name', 'Невідоме завдання'),
                    lang_code=task_info.get('lang_code', 'N/A'),
                    step=self.app._t('step_name_create_video'),
                    error_details=f"Помилка FFmpeg (код {process.returncode}). Перевірте детальний лог."
                )

                self.update_callback(f"Помилка монтажу {os.path.basename(output_video_path)}. Див. лог.", task_key=task_key, chunk_index=chunk_index)
                return False

            logger.info(f"Монтаж -> УСПІХ: Відео успішно створено: {output_video_path}")
            self.update_callback(f"Монтаж {video_name} завершено.", task_key=task_key, chunk_index=chunk_index, progress=100)
            return True

        except Exception as e:
            logger.error(f"Монтаж -> КРИТИЧНА ПОМИЛКА: Непередбачена помилка під час створення відео '{video_name}': {e}", exc_info=True)
            self.update_callback(f"Критична помилка монтажу: {e}", task_key=task_key, chunk_index=chunk_index)
            return False