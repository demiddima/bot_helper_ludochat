# services/content_builder.py
# Commit: fix(content): одиночный файл + текст → caption внутри media; альбом — без текста (пусть фасад решает)

from __future__ import annotations

from typing import Any, Dict, List, Optional
from aiogram.types import Message


def _norm_type(t: str) -> str:
    t = (t or "").lower()
    if t in {"photo", "image", "pic"}:
        return "photo"
    if t in {"video", "mp4"}:
        return "video"
    if t in {"document", "doc", "file"}:
        return "document"
    return "document"


def _mk_text(text_html: str) -> Dict[str, Any]:
    return {"type": "html", "payload": {"text": text_html}}


def _mk_media_item(mtype: str, file_id: str, *, caption: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"file_id": str(file_id)}
    if caption:
        payload["caption"] = caption
    return {"type": _norm_type(mtype), "payload": payload}


def _mk_album(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"type": "album", "payload": {"items": items[:10]}}


def make_media_items_from_event(msg: Message, album: Optional[List[Message]] = None) -> List[Dict[str, Any]]:
    """
    Преобразует вход от Telegram в items:
      - одиночный файл + текст → ОДИН media-элемент с caption
      - одиночный файл без текста → ОДИН media-элемент
      - только текст → ОДИН html-элемент
      - альбом → ОДИН album-элемент (без текста); текст не прикрепляем — фасад решит, что с ним делать
    """
    items: List[Dict[str, Any]] = []

    # Альбом: отдаём только файлы; текст отдельно не прикладываем (фасад сам проверит «одно сообщение»)
    if album:
        batch: List[Dict[str, Any]] = []
        for m in album[:10]:
            if m.photo:
                batch.append(_mk_media_item("photo", m.photo[-1].file_id))
            elif m.video:
                batch.append(_mk_media_item("video", m.video.file_id))
            elif m.document:
                batch.append(_mk_media_item("document", m.document.file_id))
        if batch:
            items.append(_mk_album(batch))
        return items

    # Одиночные медиа: caption берём прямо из сообщения и вкладываем в payload
    if msg.photo:
        cap = (msg.caption_html or msg.caption or "").strip() or None
        items.append(_mk_media_item("photo", msg.photo[-1].file_id, caption=cap))
        return items

    if msg.video:
        cap = (msg.caption_html or msg.caption or "").strip() or None
        items.append(_mk_media_item("video", msg.video.file_id, caption=cap))
        return items

    if msg.document:
        cap = (msg.caption_html or msg.caption or "").strip() or None
        items.append(_mk_media_item("document", msg.document.file_id, caption=cap))
        return items

    # Только текст
    if msg.text:
        items.append(_mk_text(msg.html_text or msg.text))
        return items

    return items


# Совместимость со старым кодом: поддержка собранного словаря collected
def make_media_items(collected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    collected:
      {
        "text_html": Optional[str],
        "single_media": List[{"type": "photo|video|document", "file_id": str, "caption"?: str}],
        "album": List[{"type": "photo|video|document", "file_id": str}],
      }
    """
    text_html = (collected.get("text_html") or "").strip()
    single_media = collected.get("single_media") or []
    album = collected.get("album") or []

    items: List[Dict[str, Any]] = []

    if album:
        batch = []
        for it in album[:10]:
            t = _norm_type(it.get("type"))
            fid = str(it.get("file_id") or "").strip()
            if fid:
                batch.append({"type": t, "payload": {"file_id": fid}})
        if batch:
            items.append(_mk_album(batch))
            return items

    if len(single_media) == 1:
        it = single_media[0]
        t = _norm_type(it.get("type"))
        fid = str(it.get("file_id") or "").strip()
        cap = (it.get("caption") or text_html or "").strip() or None
        if fid:
            items.append(_mk_media_item(t, fid, caption=cap))
        return items

    if text_html and not single_media:
        items.append(_mk_text(text_html))
        return items

    # несколько single_media → считаем альбомом (без текста)
    if len(single_media) > 1:
        batch = []
        for it in single_media[:10]:
            t = _norm_type(it.get("type"))
            fid = str(it.get("file_id") or "").strip()
            if fid:
                batch.append({"type": t, "payload": {"file_id": fid}})
        if batch:
            items.append(_mk_album(batch))

    return items
