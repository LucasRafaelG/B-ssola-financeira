"""Lê as configurações do projeto a partir das variáveis de ambiente.

Localmente as variáveis vêm do arquivo `.env`; no GitHub Actions, dos Secrets.
A credencial do Google não passa por aqui: a biblioteca do Google a descobre
sozinha no ambiente (no computador, o `gcloud` com impersonação da conta de
serviço; no GitHub Actions, a identidade federada do workflow).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Horário de Brasília. As datas do banco chegam em UTC e são convertidas para este fuso.
FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")
DIAS_HISTORICO_PADRAO = 90


class ErroConfiguracao(RuntimeError):
    """Falta alguma variável de ambiente obrigatória, ou o valor é inválido."""


@dataclass(frozen=True)
class CredenciaisPluggy:
    # repr=False: se alguém imprimir a configuração sem querer, os segredos não aparecem.
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    item_id: str = field(repr=False)


@dataclass(frozen=True)
class AcessoReal:
    """O que é preciso para trabalhar com os dados de verdade."""

    pluggy: CredenciaisPluggy
    sheet_id: str = field(repr=False)


@dataclass(frozen=True)
class Configuracao:
    dias_historico: int
    """Quantos dias buscar na primeira execução, quando a planilha está vazia."""
    acesso: AcessoReal | None
    """`None` no modo demo, que usa dados fictícios e não acessa nada de fora."""


def carregar(ambiente: Mapping[str, str] | None = None) -> Configuracao:
    """Monta a configuração. Sem argumento, lê o `.env` e as variáveis do sistema."""
    if ambiente is None:
        load_dotenv()
        ambiente = os.environ

    dias_historico = _dias_historico(ambiente.get("DIAS_HISTORICO", "").strip())

    modo = ambiente.get("DATA_MODE", "").strip().lower() or "real"
    if modo == "demo":
        return Configuracao(dias_historico=dias_historico, acesso=None)
    if modo != "real":
        raise ErroConfiguracao('DATA_MODE deve ser "real" ou "demo".')

    nomes = ("PLUGGY_CLIENT_ID", "PLUGGY_CLIENT_SECRET", "PLUGGY_ITEM_ID", "SHEET_ID")
    valores = {nome: ambiente.get(nome, "").strip() for nome in nomes}
    faltando = [nome for nome, valor in valores.items() if not valor]
    if faltando:
        raise ErroConfiguracao(
            "Variáveis de ambiente faltando ou vazias: "
            + ", ".join(faltando)
            + ". Preencha o arquivo .env (veja o .env.example)."
        )

    return Configuracao(
        dias_historico=dias_historico,
        acesso=AcessoReal(
            pluggy=CredenciaisPluggy(
                client_id=valores["PLUGGY_CLIENT_ID"],
                client_secret=valores["PLUGGY_CLIENT_SECRET"],
                item_id=valores["PLUGGY_ITEM_ID"],
            ),
            sheet_id=valores["SHEET_ID"],
        ),
    )


def _dias_historico(texto: str) -> int:
    if not texto:
        return DIAS_HISTORICO_PADRAO
    if not texto.isdecimal() or int(texto) < 1:
        raise ErroConfiguracao("DIAS_HISTORICO deve ser um número inteiro maior que zero.")
    return int(texto)
