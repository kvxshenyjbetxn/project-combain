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

    def create_subtitles(self, audio_path, output_ass_path):
        """Створює файл субтитрів .ass з аудіофайлу."""
        logger.info(f"Субтитри -> Початок створення субтитрів для {os.path.basename(audio_path)}")
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
    Style: Default,Arial,{self.config.get('font_size', 48)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1
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

    def create_video(self, image_paths, audio_path, ass_path, output_video_path):
        """Створює відео з зображень, аудіо та субтитрів з ефектами, ЗАВЖДИ з переходами."""
        cfg = self.config
        codec_cfg = cfg.get('codec', {})
        video_name = os.path.basename(output_video_path)
        logger.info(f"Монтаж -> Початок створення відео '{video_name}'")
        try:
            self.update_callback(f"Аналіз медіа: {video_name}...")
            probe = ffmpeg.probe(audio_path)
            audio_duration = float(probe['format']['duration'])
            
            if not image_paths:
                logger.error(f"Монтаж -> ПОМИЛКА: Немає зображень для створення відео '{video_name}'.")
                self.update_callback("Помилка: не обрано зображень для відео.")
                return False
            
            num_images = len(image_paths)
            transition_effect = cfg.get('transition_effect', 'fade')
            transition_duration = 1.0 if num_images > 1 and transition_effect != "Без переходу" else 0
            
            total_transition_duration = transition_duration * (num_images - 1)
            image_duration = (audio_duration + total_transition_duration) / num_images if num_images > 0 else 0

            if image_duration <= transition_duration and num_images > 1:
                msg = f"Тривалість аудіо замала. Час картинки ({image_duration:.2f}с) <= часу переходу ({transition_duration:.2f}с)."
                logger.error(f"Монтаж -> ПОМИЛКА: {msg}")
                self.update_callback(f"Помилка: {msg}")
                return False

            logger.info(f"Монтаж -> Тривалість аудіо: {audio_duration:.2f}с. Час на картинку: ~{image_duration:.2f}с.")
            self.update_callback(f"Тривалість аудіо: {audio_duration:.2f}с. Час на картинку: ~{image_duration:.2f}с.")

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
            
            self.update_callback(f"Монтаж: '{video_name}' з кодеком '{video_codec}'...")
            logger.info(f"Монтаж -> Рендеринг '{video_name}' з кодеком '{video_codec}'. Параметри: {output_params}")

            ffmpeg_executable = "ffmpeg"
            args = ffmpeg.output(final_video_with_subs, audio_input, output_video_path, **output_params).overwrite_output().get_args()
            
            process = subprocess.Popen([ffmpeg_executable, '-y'] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='ignore')
            
            total_output_frames = int(audio_duration * output_framerate)
            
            # Додаємо throttling для оновлень GUI
            last_update_time = 0
            update_interval = 0.2 # Оновлювати не частіше, ніж раз на 200 мс

            for line in process.stderr:
                line = line.strip()
                logger.debug(f"FFMPEG -> {line}") # Детальний лог у файл залишаємо без змін

                if line.startswith("frame="):
                    current_time = time.time()
                    if current_time - last_update_time > update_interval:
                        last_update_time = current_time

                        if threading.current_thread() is threading.main_thread():
                            # Цей код виконується тільки в основному потоці
                            match = re.search(r"frame=\s*(\d+)", line)
                            if match and total_output_frames > 0:
                                progress = (int(match.group(1)) / total_output_frames) * 100
                                self.update_callback(f"Монтаж відео... {progress:.1f}%")
                        else:
                            # Цей код для паралельних потоків, форматує вивід
                            progress, fps, bitrate = 0.0, "N/A", "N/A"

                            frame_match = re.search(r"frame=\s*(\d+)", line)
                            if frame_match and total_output_frames > 0:
                                progress = (int(frame_match.group(1)) / total_output_frames) * 100

                            fps_match = re.search(r"fps=\s*([\d\.]+)", line)
                            if fps_match:
                                fps = fps_match.group(1)

                            bitrate_match = re.search(r"bitrate=\s*([\d\.]+\w*bits/s)", line)
                            if bitrate_match:
                                bitrate = bitrate_match.group(1)
                            
                            formatted_line = f"Прогрес: {progress:.1f}% | FPS: {fps} | Бітрейт: {bitrate}"
                            logger.info(formatted_line)

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

                self.update_callback(f"Помилка монтажу {os.path.basename(output_video_path)}. Див. лог.")
                return False

            logger.info(f"Монтаж -> УСПІХ: Відео успішно створено: {output_video_path}")
            self.update_callback(f"Монтаж {video_name} завершено.")
            return True

        except Exception as e:
            logger.error(f"Монтаж -> КРИТИЧНА ПОМИЛКА: Непередбачена помилка під час створення відео '{video_name}': {e}", exc_info=True)
            self.update_callback(f"Критична помилка монтажу: {e}")
            return False