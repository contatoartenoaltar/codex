"""Transporte Meta específico para carrosséis de três imagens."""
from __future__ import annotations

import io
from pathlib import Path
import urllib.parse

from PIL import Image

from stories.meta_client import MAX_IMAGE, MetaClient, identifier


class CarouselMetaClient(MetaClient):
    def stage_image(self, image):
        if self.page is None:
            raise ValueError("Confira a conta antes de enviar a imagem.")
        image = Path(image)
        if image.is_symlink() or image.stat().st_size > MAX_IMAGE:
            raise ValueError("Imagem do carrossel inválida.")
        raw = image.read_bytes()
        with Image.open(io.BytesIO(raw)) as photo:
            if photo.format != "JPEG" or photo.size != (1080, 1350):
                raise ValueError("O slide precisa ser um JPEG 1080 × 1350.")
            photo.verify()
        result = self._request("POST", str(self.page["id"]) + "/photos", {"published": "false"},
                               token=self.page["access_token"], image=raw)
        return {"id": identifier(str(result.get("id")))}

    def _staged_source(self, staged_photo):
        if self.page is None:
            raise ValueError("Confira a conta antes de preparar o carrossel.")
        photo = self._request("GET", identifier(staged_photo), {"fields": "images"},
                              token=self.page["access_token"])
        candidates = []
        for item in photo.get("images", []):
            if not isinstance(item, dict) or not isinstance(item.get("source"), str):
                continue
            parsed = urllib.parse.urlsplit(item["source"])
            host = (parsed.hostname or "").lower()
            width, height = item.get("width"), item.get("height")
            if (parsed.scheme == "https" and not parsed.username and not parsed.password and
                    not parsed.fragment and parsed.port in (None, 443) and
                    host.endswith((".fbcdn.net", ".fbsbx.com", ".facebook.com")) and
                    type(width) is int and type(height) is int and 320 <= width <= 1440 and
                    height > 0 and abs(width / height - 4 / 5) < .01):
                candidates.append(item)
        if not candidates:
            raise ValueError("A Meta não retornou um slide 4:5 compatível.")
        return max(candidates, key=lambda entry: entry["width"])["source"]

    def create_carousel_child(self, image, *, staged_photo):
        source = self._staged_source(staged_photo)
        result = self._request("POST", self.account_id + "/media",
                               {"image_url": source, "is_carousel_item": "true"})
        return {"id": identifier(str(result.get("id")))}

    def create_carousel(self, children, caption):
        children = [identifier(str(value)) for value in children]
        if len(children) != 3 or len(set(children)) != 3:
            raise ValueError("O carrossel precisa de três contêineres filhos diferentes.")
        if not isinstance(caption, str) or not caption.strip() or len(caption) > 2200:
            raise ValueError("Legenda do carrossel inválida.")
        result = self._request("POST", self.account_id + "/media",
                               {"media_type": "CAROUSEL", "children": ",".join(children),
                                "caption": caption.strip()})
        return {"id": identifier(str(result.get("id")))}
