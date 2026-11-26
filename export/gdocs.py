"""Cria Google Docs a partir do HTML (conversão nativa do Drive: headings, negrito, tabelas e links).

Configuração nos secrets:
    [gcp_service_account]   JSON da conta de serviço (mesmo formato usado no Streamlit Cloud)
    [google] folder_id      pasta de destino. Precisa estar num Drive compartilhado
                            (contas de serviço não têm cota própria no Meu Drive), e a conta de
                            serviço precisa ser membro desse Drive compartilhado com papel de Editor
                            de conteúdo ou acima.
"""
from __future__ import annotations

import io

from core import config

SCOPES = ["https://www.googleapis.com/auth/drive"]


class GDocsError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(config.get_section("gcp_service_account")) and bool(config.get("folder_id", section="google"))


def _drive():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = config.get_section("gcp_service_account")
    if not info:
        raise GDocsError("Conta de serviço do Google não configurada ([gcp_service_account]).")
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def create_doc(title: str, html: str, folder_id: str | None = None) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    folder_id = folder_id or config.get("folder_id", section="google")
    if not folder_id:
        raise GDocsError("Pasta do Drive não configurada ([google] folder_id).")
    meta = {"name": title, "mimeType": "application/vnd.google-apps.document", "parents": [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(html.encode("utf-8")), mimetype="text/html", resumable=False)
    try:
        f = _drive().files().create(body=meta, media_body=media, fields="id,webViewLink",
                                    supportsAllDrives=True).execute()
    except Exception as ex:
        raise GDocsError(f"Falha ao criar o Google Doc: {ex}") from ex
    return f["webViewLink"]
