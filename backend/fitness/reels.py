"""
Сборщик Reels: таймлайн разнородных сегментов (ai-видео / чужой мем-клип / картинка)
→ один вертикальный MP4. Вызывается вьюхой reels_assemble (эндпоинт /api/reels/assemble),
которую по HTTP+X-Cron-Secret дёргает n8n. Django-моделей не трогает — stateful-часть
(таблицы reels_*) живёт в n8n, сюда приходит уже готовый таймлайн с URL-ами ассетов.

Контракт входа (request.payload):
{
  "output": {"width":1080, "height":1920, "fps":30},   # опц., дефолты ниже
  "timeline": [
    {"type":"ai"|"clip"|"image"|"card",
     "url":"https://...",      # ИЛИ "data":"<base64>" (инлайн-ассет, напр. мем из TG)
     "duration": 3.0,          # обязат. для image/card; для clip/ai — опц. обрезка
     "text": "POV: ...",       # опц. текст-плашка поверх сегмента (как в Shorts)
     "color": "black",         # только для card — цвет подложки
     "keep_audio": true}       # опц. (дефолт true); false → заглушить дорожку
  ]
}
Типы: ai — сгенерённый клип (url провайдера); clip — чужой мем-видео; image —
картинка (нужен duration); card — текстовая плашка без файла (нужен duration).

Идея надёжности: каждый сегмент по отдельности нормализуем к ЕДИНЫМ параметрам
(размер/fps/кодек/аудио) в промежуточный MPEG-TS, затем клеим их concat-протоколом
с `-c copy` — так стыки не рассыпаются из-за разных исходников.
"""
import base64
import os
import subprocess
import tempfile
from urllib.request import Request, urlopen

# Дефолты вертикали под Reels/Shorts.
DEF_W, DEF_H, DEF_FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # ставится в Dockerfile


class AssembleError(Exception):
    pass


def _run(cmd):
    """Запустить ffmpeg/ffprobe, поднять AssembleError с хвостом stderr при ошибке."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stderr or "")[-1500:]
        raise AssembleError(f"{cmd[0]} failed (code {p.returncode}): {tail}")
    return p.stdout


def _download(url, dst):
    req = Request(url, headers={"User-Agent": "fitness-bot"})
    with urlopen(req, timeout=60) as r, open(dst, "wb") as f:
        f.write(r.read())


def _has_audio(src):
    """Есть ли у файла аудиодорожка (ffprobe вернёт индекс потока, если есть)."""
    out = _run(["ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=index", "-of", "csv=p=0", src])
    return bool(out.strip())


def _drawtext_filter(text, workdir):
    """drawtext через textfile (чтобы не экранировать двоеточия/кавычки в тексте).
    Белый текст с полупрозрачной подложкой, крупно, ближе к верху."""
    tf = tempfile.NamedTemporaryFile("w", suffix=".txt", dir=workdir,
                                     delete=False, encoding="utf-8")
    tf.write(text)
    tf.close()
    return (
        f"drawtext=fontfile={FONT}:textfile={tf.name}:"
        f"fontcolor=white:fontsize=h/16:box=1:boxcolor=black@0.5:boxborderw=20:"
        f"x=(w-text_w)/2:y=h*0.12:line_spacing=8"
    )


def _normalize(seg, out_ts, w, h, fps, workdir):
    """Один сегмент → нормализованный MPEG-TS (h264/aac, WxH, fps, 48k стерео).
    Гарантируем РОВНО одну аудиодорожку на каждый сегмент — иначе финальный
    concat с `-c copy` разъедется на разнородных потоках."""
    stype = seg.get("type")
    src = seg["_src"]
    duration = seg.get("duration")
    keep_audio = seg.get("keep_audio", True)

    # Видео-фильтр: вписать в WxH с сохранением пропорций + добить чёрными полями.
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )
    if seg.get("text"):
        vf += "," + _drawtext_filter(seg["text"], workdir)

    # input 0 — контент, input 1 — бесконечная тишина (fallback-аудио).
    cmd = ["ffmpeg", "-y"]
    if stype == "card":
        # Текстовая плашка: цветная подложка нужной длины, без внешнего файла.
        if not duration:
            raise AssembleError("card-сегмент без duration")
        color = seg.get("color", "black")
        cmd += ["-f", "lavfi", "-t", str(duration),
                "-i", f"color=c={color}:s={w}x{h}:r={fps}"]
        use_own_audio = False
    elif stype == "image":
        if not duration:
            raise AssembleError("image-сегмент без duration")
        cmd += ["-loop", "1", "-t", str(duration), "-i", src]
        use_own_audio = False
    else:
        cmd += ["-i", src]
        if duration:
            cmd += ["-t", str(duration)]
        use_own_audio = keep_audio and _has_audio(src)
    cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]

    amap = ["-map", "0:v:0", "-map", ("0:a:0" if use_own_audio else "1:a:0")]

    cmd += ["-vf", vf, *amap,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-shortest", "-r", str(fps), "-video_track_timescale", "90000",
            "-f", "mpegts", out_ts]
    _run(cmd)


def assemble(payload):
    """Главная точка: payload (см. модуль-docstring) → путь к готовому MP4 во временной
    директории. Директорию удаляет вызывающая вьюха (после чтения файла)."""
    timeline = payload.get("timeline") or []
    if not isinstance(timeline, list) or not timeline:
        raise AssembleError("пустой timeline")

    out = payload.get("output") or {}
    w = int(out.get("width", DEF_W))
    h = int(out.get("height", DEF_H))
    fps = int(out.get("fps", DEF_FPS))

    workdir = tempfile.mkdtemp(prefix="reels_")
    ts_parts = []
    for i, seg in enumerate(timeline):
        stype = seg.get("type")
        if stype == "card":
            seg["_src"] = None                       # генерится в ffmpeg, файла нет
        else:
            # Ассет: либо инлайн base64 (`data`) — так шлём мем из Telegram без
            # публичного URL, — либо `url` (сгенерённые провайдером клипы).
            ext = ".jpg" if stype == "image" else ".mp4"
            src = os.path.join(workdir, f"src_{i}{ext}")
            raw = seg.get("data")
            if raw:
                with open(src, "wb") as f:
                    f.write(base64.b64decode(raw))
            elif seg.get("url"):
                _download(seg["url"], src)
            else:
                raise AssembleError(f"сегмент {i}: нужен url или data")
            seg["_src"] = src
        ts = os.path.join(workdir, f"seg_{i}.ts")
        _normalize(seg, ts, w, h, fps, workdir)
        ts_parts.append(ts)

    final = os.path.join(workdir, "final.mp4")
    concat = "concat:" + "|".join(ts_parts)
    _run(["ffmpeg", "-y", "-i", concat,
          "-c", "copy", "-bsf:a", "aac_adtstoasc",
          "-movflags", "+faststart", final])
    return final, workdir
