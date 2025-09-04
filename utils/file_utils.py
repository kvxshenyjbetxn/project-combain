# utils/file_utils.py

import re
import logging
import math # <-- ДОДАНО ВІДСУТНІЙ ІМПОРТ

logger = logging.getLogger("TranslationApp")

def sanitize_filename(name):
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.replace("...", "")
    name = name.strip().rstrip('.')
    return name[:150].strip()

def chunk_text(text: str, num_chunks: int) -> list[str]:
    if num_chunks <= 0: return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) < num_chunks:
        logger.warning(f"Text has {len(sentences)} sentences, but {num_chunks} chunks requested. Splitting by characters.")
        avg_len = len(text) / num_chunks
        chunks = [text[int(i*avg_len):int((i+1)*avg_len)] for i in range(num_chunks)]
        return [c for c in chunks if c.strip()] or [text]
    
    chunks = [''] * num_chunks
    base_size, remainder = divmod(len(sentences), num_chunks)
    sent_idx = 0
    for i in range(num_chunks):
        num_to_take = base_size + (1 if i < remainder else 0)
        chunks[i] = " ".join(sentences[sent_idx:sent_idx + num_to_take])
        sent_idx += num_to_take
    return [c for c in chunks if c.strip()]

def chunk_text_voicemaker(text: str, limit: int) -> list[str]:
    chunks, remaining_text = [], text.strip()
    while len(remaining_text) > limit:
        split_pos = -1
        for p in ['.', '!', '?', '\n']:
            pos = remaining_text.rfind(p, 0, limit)
            if pos > split_pos: split_pos = pos
        
        if split_pos == -1: split_pos = remaining_text.rfind(' ', 0, limit)
        if split_pos == -1: split_pos = limit - 1
        
        chunk = remaining_text[:split_pos + 1]
        chunks.append(chunk.strip())
        remaining_text = remaining_text[split_pos + 1:].strip()
    
    if remaining_text: chunks.append(remaining_text)
    logger.info(f"Text split into {len(chunks)} chunks for Voicemaker.")
    return [c for c in chunks if c]

def chunk_text_speechify(text: str, limit: int, num_chunks_target: int) -> list[str]:
    """
    Розбиває текст на частини для Speechify, намагаючись дотриматися цільової кількості частин.
    Схожа на логіку Voicemaker, але адаптована для потенційно більшої кількості частин.
    """
    if len(text) <= limit:
        return [text]

    # Спочатку спробуємо розділити по реченнях, щоб отримати приблизну кількість
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # Якщо речень менше, ніж потрібно частин, логіка буде іншою
    if len(sentences) < num_chunks_target:
        # Проста нарізка за лімітом, як у Voicemaker
        logger.info(f"Text has few sentences ({len(sentences)}), splitting by character limit for Speechify.")
        return chunk_text_voicemaker(text, limit)
        
    # Якщо речень достатньо, групуємо їх у цільову кількість частин
    logger.info(f"Grouping {len(sentences)} sentences into approximately {num_chunks_target} chunks for Speechify.")
    
    chunks = []
    current_chunk = ""
    # Визначаємо, скільки речень має бути в кожній частині
    sentences_per_chunk = math.ceil(len(sentences) / num_chunks_target)
    
    for i, sentence in enumerate(sentences):
        if len(current_chunk) + len(sentence) > limit or (i > 0 and i % sentences_per_chunk == 0):
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += " " + sentence
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    # Перевірка: якщо останній чанк занадто малий, об'єднуємо його з попереднім
    if len(chunks) > 1 and len(chunks[-1]) < limit * 0.2:
        last_chunk = chunks.pop()
        chunks[-1] += " " + last_chunk
        
    logger.info(f"Text split into {len(chunks)} chunks for Speechify.")
    return [c for c in chunks if c]

def chunk_text_speechify(text: str, limit: int, num_chunks_target: int) -> list[str]:
    """
    Розбиває текст на частини для Speechify, намагаючись дотриматися цільової кількості частин.
    Схожа на логіку Voicemaker, але адаптована для потенційно більшої кількості частин.
    """
    if len(text) <= limit:
        return [text]

    # Спочатку спробуємо розділити по реченнях, щоб отримати приблизну кількість
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # Якщо речень менше, ніж потрібно частин, логіка буде іншою
    if len(sentences) < num_chunks_target:
        # Проста нарізка за лімітом, як у Voicemaker
        logger.info(f"Text has few sentences ({len(sentences)}), splitting by character limit for Speechify.")
        return chunk_text_voicemaker(text, limit)
        
    # Якщо речень достатньо, групуємо їх у цільову кількість частин
    logger.info(f"Grouping {len(sentences)} sentences into approximately {num_chunks_target} chunks for Speechify.")
    
    chunks = []
    current_chunk = ""
    # Визначаємо, скільки речень має бути в кожній частині
    sentences_per_chunk = math.ceil(len(sentences) / num_chunks_target)
    
    for i, sentence in enumerate(sentences):
        if len(current_chunk) + len(sentence) > limit or (i > 0 and i % sentences_per_chunk == 0):
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += " " + sentence
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    # Перевірка: якщо останній чанк занадто малий, об'єднуємо його з попереднім
    if len(chunks) > 1 and len(chunks[-1]) < limit * 0.2:
        last_chunk = chunks.pop()
        chunks[-1] += " " + last_chunk
        
    logger.info(f"Text split into {len(chunks)} chunks for Speechify.")
    return [c for c in chunks if c]