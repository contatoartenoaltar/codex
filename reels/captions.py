"""Legendas comerciais aprovadas para a rotação automática de Reels."""
from __future__ import annotations

import hashlib


CAPTIONS = (
    "Envelopes personalizados com a identidade da sua igreja, logo e QR Code Pix. "
    "Conheça nossos modelos em artenoaltar.com.br. #ArteNoAltar #Igreja",
    "Cada detalhe comunica cuidado. Personalizamos envelopes para dízimos, ofertas, "
    "missões e outros propósitos da sua igreja. #EnvelopesPersonalizados #ArteNoAltar",
    "Sua igreja merece materiais com identidade. Escolha um modelo e envie sua logo para "
    "fazermos uma simulação. #GráficaCristã #ArteNoAltar",
    "Mais de 70 modelos de envelopes para diferentes temas e momentos da sua igreja. "
    "Enviamos para todo o Brasil. #Igreja #EnvelopesPersonalizados",
    "Pedido mínimo de 100 unidades, com personalização da logo e do QR Code Pix. "
    "Acesse artenoaltar.com.br. #ArteNoAltar #GráficaCristã",
)


def choose(source_id, cycle=0):
    if not isinstance(source_id, str) or not source_id or type(cycle) is not int or cycle < 0:
        raise ValueError("Identificação de legenda inválida.")
    value = int.from_bytes(hashlib.sha256(source_id.encode()).digest()[:8], "big")
    return CAPTIONS[(value + cycle) % len(CAPTIONS)]
