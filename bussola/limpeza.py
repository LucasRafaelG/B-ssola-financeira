"""Transforma as transações da Pluggy na tabela da aba `transacoes` da planilha.

Regras:
- valor: gasto negativo, entrada positiva, decidido pelo tipo da transação;
- data: o dia no horário de Brasília (a Pluggy envia em UTC);
- tipo e conta: traduzidos para os nomes usados na planilha.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from bussola.config import FUSO_HORARIO
from bussola.pluggy import Conta, Transacao

COLUNAS_PLANILHA = [
    "id",
    "data",
    "descricao",
    "valor",
    "tipo",
    "conta",
    "categoria",
    "prioridade",
    "categorizado_por",
    "parcela",
    "total_parcelas",
    "importado_em",
]

# Coluna auxiliar: a categorização usa como alternativa quando nenhuma regra casa.
# Não é gravada na planilha.
COLUNA_CATEGORIA_PLUGGY = "categoria_pluggy"

_TIPOS_DAS_COLUNAS = {
    "id": "str",
    "data": "datetime64[ns]",
    "descricao": "str",
    "valor": "float64",
    "tipo": "str",
    "conta": "str",
    "categoria": "str",
    "prioridade": "str",
    "categorizado_por": "str",
    "parcela": "Int64",
    "total_parcelas": "Int64",
    "importado_em": "datetime64[ns]",
    COLUNA_CATEGORIA_PLUGGY: "str",
}

# tipo da Pluggy -> (nome na planilha, sinal do valor)
TIPO_DEBITO = "DEBITO"
TIPO_CREDITO = "CREDITO"
_TIPOS = {"DEBIT": (TIPO_DEBITO, -1), "CREDIT": (TIPO_CREDITO, 1)}

# tipo de conta da Pluggy -> nome na planilha
CONTA_CORRENTE = "Conta corrente"
CARTAO_DE_CREDITO = "Cartão de crédito"
# Não vem do banco: é a "conta" dos lançamentos manuais em dinheiro vivo.
DINHEIRO = "Dinheiro"
_NOMES_DE_CONTA = {"BANK": CONTA_CORRENTE, "CREDIT": CARTAO_DE_CREDITO}


class ErroLimpeza(RuntimeError):
    """Chegou um dado que a limpeza não sabe tratar (tipo ou conta desconhecidos)."""


def limpar(
    transacoes: Sequence[Transacao], contas: Sequence[Conta], importado_em: datetime
) -> pd.DataFrame:
    """Monta a tabela com as colunas da planilha, mais a coluna auxiliar da Pluggy.

    As colunas `categoria`, `prioridade` e `categorizado_por` saem vazias: quem
    preenche é a categorização.
    """
    nome_da_conta = {conta.id: _nome_da_conta(conta) for conta in contas}
    momento_da_importacao = _horario_local(importado_em)

    linhas = []
    for transacao in transacoes:
        if transacao.tipo not in _TIPOS:
            raise ErroLimpeza(f"Tipo de transação desconhecido: {transacao.tipo}.")
        if transacao.conta_id not in nome_da_conta:
            raise ErroLimpeza("Transação de uma conta que não está na lista de contas.")
        tipo, sinal = _TIPOS[transacao.tipo]
        linhas.append(
            {
                "id": transacao.id,
                "data": _horario_local(transacao.data).normalize(),
                "descricao": transacao.descricao,
                "valor": sinal * abs(transacao.valor),
                "tipo": tipo,
                "conta": nome_da_conta[transacao.conta_id],
                "categoria": None,
                "prioridade": None,
                "categorizado_por": None,
                "parcela": transacao.parcela,
                "total_parcelas": transacao.total_parcelas,
                "importado_em": momento_da_importacao,
                COLUNA_CATEGORIA_PLUGGY: transacao.categoria,
            }
        )

    return pd.DataFrame(linhas, columns=list(_TIPOS_DAS_COLUNAS)).astype(_TIPOS_DAS_COLUNAS)


def _nome_da_conta(conta: Conta) -> str:
    if conta.tipo not in _NOMES_DE_CONTA:
        raise ErroLimpeza(f"Tipo de conta desconhecido: {conta.tipo}/{conta.subtipo}.")
    return _NOMES_DE_CONTA[conta.tipo]


def _horario_local(momento: datetime) -> pd.Timestamp:
    """Converte para o horário de Brasília e descarta o fuso (a planilha não guarda fuso)."""
    if momento.tzinfo is None:
        raise ErroLimpeza("Data sem fuso horário: não dá para converter para o horário de Brasília.")
    return pd.Timestamp(momento).tz_convert(FUSO_HORARIO).tz_localize(None)
