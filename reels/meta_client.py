"""Cliente Meta isolado para Reels já finalizados.

Construir o cliente não consulta a rede nem altera a autorização existente.
O vídeo precisa estar disponível em uma URL HTTPS temporária e restrita ao
domínio configurado pelo chamador.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


MAX_RESPONSE = 262144
SCOPES = frozenset({"instagram_basic", "instagram_content_publish"})
ACCOUNT = "arte.no.altar"


class PreparationRetryError(ValueError):
    """A preparação não foi confirmada e pode ser consultada novamente."""


class PublishUncertainError(ValueError):
    """A chamada final perdeu a resposta e nunca deve ser repetida às cegas."""


class MetaRejectedError(ValueError):
    """A Meta respondeu e recusou uma operação sem expor detalhes privados."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", value):
        raise ValueError("Identificador da Meta inválido.")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirecionamento da Meta recusado.")


def credentials(directory):
    """Lê a configuração existente sem renovar token ou gravar arquivos."""
    import meta

    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("A autorização precisa estar em um diretório local.")
    for name in ("meta-config.json", "meta-connection.json"):
        if (directory / name).is_symlink():
            raise ValueError("A autorização precisa estar em arquivos privados locais.")
    settings = meta.config(directory)
    connection = meta.read_private(directory / "meta-connection.json")
    expiry = connection.get("expires_at")
    if (connection.get("app_id") != settings["app_id"] or
            not isinstance(connection.get("access_token"), str) or
            not connection["access_token"] or isinstance(expiry, bool) or
            (expiry is not None and (not isinstance(expiry, (int, float)) or
                                     not math.isfinite(expiry) or expiry <= time.time()))):
        raise ValueError("A autorização existente da Meta não está disponível ou está expirada.")
    return settings, connection["access_token"]


def _media_origin(value):
    parsed = urllib.parse.urlsplit(value if isinstance(value, str) else "")
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
            parsed.port not in (None, 443) or parsed.path not in ("", "/") or
            parsed.query or parsed.fragment):
        raise ValueError("Origem pública dos Reels inválida.")
    return f"https://{parsed.hostname.lower()}"


class MetaClient:
    simulation = False

    def __init__(self, settings, token, account_id, media_origin, *, opener=None):
        self.account_id = identifier(account_id)
        if (not isinstance(settings.get("version"), str) or
                not re.fullmatch(r"v[1-9][0-9]*\.0", settings["version"]) or
                not isinstance(settings.get("app_secret"), str) or not settings["app_secret"] or
                not isinstance(token, str) or not token):
            raise ValueError("Configuração da Meta inválida.")
        self.settings = dict(settings)
        self.token = token
        self.media_origin = _media_origin(media_origin)
        self.opener = opener if opener is not None else urllib.request.build_opener(NoRedirect)

    @classmethod
    def from_directory(cls, directory, account_id, media_origin):
        settings, token = credentials(directory)
        return cls(settings, token, account_id, media_origin)

    def _request(self, method, path, data=None, *, final_publish=False):
        if (method not in ("GET", "POST") or
                not re.fullmatch(r"(?:me/permissions|[1-9][0-9]{0,39}(?:/(?:media|media_publish))?)", path)):
            raise ValueError("Operação da Meta não permitida.")
        proof = hmac.new(self.settings["app_secret"].encode(), self.token.encode(),
                         hashlib.sha256).hexdigest()
        fields = dict(data or {}) | {"appsecret_proof": proof}
        url = f'https://graph.facebook.com/{self.settings["version"]}/{path}'
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        body = None
        if method == "GET":
            url += "?" + urllib.parse.urlencode(fields)
        else:
            body = urllib.parse.urlencode(fields).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise PreparationRetryError("A resposta da Meta excedeu o limite.")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise PreparationRetryError("A Meta não confirmou a operação do Reel.")
            if "error" in result:
                raise MetaRejectedError("A Meta recusou a operação do Reel.")
            return result
        except urllib.error.HTTPError:
            raise MetaRejectedError("A Meta recusou a operação do Reel.") from None
        except MetaRejectedError:
            raise
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError,
                PreparationRetryError):
            if final_publish:
                raise PublishUncertainError(
                    "A publicação do Reel não foi confirmada. Confira o Instagram antes de qualquer nova tentativa."
                ) from None
            raise PreparationRetryError(
                "A Meta não confirmou a preparação do Reel; tente novamente."
            ) from None

    def verify_account(self, account_id):
        if account_id != self.account_id:
            raise ValueError("A conta do Reel mudou.")
        permissions = self._request("GET", "me/permissions").get("data", [])
        if not isinstance(permissions, list):
            raise ValueError("Não foi possível conferir as permissões da conta.")
        granted = {item.get("permission") for item in permissions
                   if isinstance(item, dict) and item.get("status") == "granted"}
        if not SCOPES.issubset(granted):
            raise ValueError("A autorização não inclui as permissões necessárias para Reels.")
        account = self._request("GET", self.account_id, {"fields": "id,username"})
        if str(account.get("id")) != self.account_id or account.get("username") != ACCOUNT:
            raise ValueError("O destino precisa ser a conta empresarial @arte.no.altar.")
        return {"id": self.account_id, "username": ACCOUNT, "reels_allowed": True}

    def _video_url(self, value):
        parsed = urllib.parse.urlsplit(value if isinstance(value, str) else "")
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or
                parsed.query or parsed.port not in (None, 443) or
                (parsed.hostname or "").lower() != urllib.parse.urlsplit(self.media_origin).hostname or
                not re.fullmatch(r"/reels-media/[a-f0-9]{64}\.(?:mp4|mov)", parsed.path)):
            raise ValueError("URL temporária do Reel inválida.")
        return value

    def create_container(self, video_url, caption, *, share_to_feed=True):
        if share_to_feed is not True:
            raise ValueError("O Reel da Arte no Altar também deve aparecer no Feed.")
        if not isinstance(caption, str) or not caption.strip() or len(caption) > 2200:
            raise ValueError("Revise a legenda do Reel.")
        result = self._request("POST", self.account_id + "/media", {
            "media_type": "REELS",
            "video_url": self._video_url(video_url),
            "caption": caption.strip(),
            "share_to_feed": "true",
        })
        return {"id": identifier(str(result.get("id")))}

    def container_status(self, container):
        result = self._request("GET", identifier(container), {"fields": "status_code"})
        return result.get("status_code")

    def publish(self, container):
        result = self._request("POST", self.account_id + "/media_publish",
                               {"creation_id": identifier(container)}, final_publish=True)
        try:
            remote = identifier(str(result.get("id")))
        except ValueError:
            # A chamada final recebeu uma resposta sem recibo utilizável. Ela
            # pode ter sido efetivada e não pode ser repetida automaticamente.
            raise PublishUncertainError(
                "A publicação do Reel não foi confirmada. Confira o Instagram antes de qualquer nova tentativa."
            ) from None
        return {"id": remote}
