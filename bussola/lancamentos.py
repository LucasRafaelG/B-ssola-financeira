"""O que se grava à mão pelo aplicativo: lançamentos e correções de categoria.

Lançamento manual: uma transação que não passa pelo banco (dinheiro vivo, por
exemplo). Entra na aba `transacoes` com um id próprio e marcada como `manual`.

Correção de categoria: troca a categoria e a prioridade de uma transação que já
existe e a marca como `manual`.

Nos dois casos a marca `manual` garante que o robô nunca sobrescreve a escolha.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pandas as pd

from bussola.categorias import MANUAL, PRIORIDADES, Classificacao
from bussola.config import FUSO_HORARIO
from bussola.limpeza import (
    CARTAO_DE_CREDITO,
    COLUNAS_PLANILHA,
    CONTA_CORRENTE,
    DINHEIRO,
    TIPO_CREDITO,
    TIPO_DEBITO,
)
from bussola.planilha import Armazenamento, aplicar_recategorizacao, gravar_novas, ler_transacoes

GASTO = "Gasto"
ENTRADA = "Entrada"
CONTAS = (DINHEIRO, CONTA_CORRENTE, CARTAO_DE_CREDITO)
PREFIXO_DO_ID = "manual-"


class ErroLancamento(ValueError):
    """O lançamento ou a correção não é válido. A mensagem diz o que corrigir."""


def lancar(
    armazenamento: Armazenamento,
    *,
    tipo: str,
    valor: float,
    data: date,
    conta: str,
    descricao: str,
    categoria: str,
    prioridade: str,
    agora: datetime,
) -> str:
    """Grava um lançamento manual no fim da aba `transacoes` e devolve o id dele.

    `valor` é sempre positivo; o sinal vem do tipo (gasto negativo, entrada positiva).
    """
    descricao, categoria, prioridade = descricao.strip(), categoria.strip(), prioridade.strip()
    if tipo not in (GASTO, ENTRADA):
        raise ErroLancamento(f"O tipo deve ser {GASTO} ou {ENTRADA}.")
    if not valor > 0:
        raise ErroLancamento("O valor deve ser maior que zero.")
    if data > agora.astimezone(FUSO_HORARIO).date():
        raise ErroLancamento("A data não pode ser no futuro.")
    if conta not in CONTAS:
        raise ErroLancamento(f"A conta deve ser uma destas: {', '.join(CONTAS)}.")
    if not descricao:
        raise ErroLancamento("Escreva uma descrição.")
    _conferir_categoria(categoria, prioridade)

    identificador = f"{PREFIXO_DO_ID}{uuid4().hex}"
    linha = {
        "id": identificador,
        "data": pd.Timestamp(data),
        "descricao": descricao,
        "valor": round(-valor if tipo == GASTO else valor, 2),
        "tipo": TIPO_DEBITO if tipo == GASTO else TIPO_CREDITO,
        "conta": conta,
        "categoria": categoria,
        "prioridade": prioridade,
        "categorizado_por": MANUAL,
        "parcela": pd.NA,
        "total_parcelas": pd.NA,
        "importado_em": pd.Timestamp(agora.astimezone(FUSO_HORARIO).replace(tzinfo=None)),
    }
    gravar_novas(armazenamento, pd.DataFrame([linha], columns=COLUNAS_PLANILHA), set())
    return identificador


def corrigir_categoria(
    armazenamento: Armazenamento, identificador: str, categoria: str, prioridade: str
) -> None:
    """Troca a categoria e a prioridade de uma transação e a marca como `manual`.

    Só essas três colunas da linha são alteradas.
    """
    categoria, prioridade = categoria.strip(), prioridade.strip()
    _conferir_categoria(categoria, prioridade)
    gravadas = ler_transacoes(armazenamento)
    posicoes = [posicao for posicao, valor in enumerate(gravadas["id"]) if valor == identificador]
    if len(posicoes) != 1:
        raise ErroLancamento(
            "A transação não foi encontrada na planilha. Recarregue e tente de novo."
            if not posicoes
            else "Há mais de uma linha com o mesmo id na planilha. Corrija direto na planilha."
        )
    aplicar_recategorizacao(
        armazenamento, {posicoes[0]: Classificacao(categoria, prioridade, MANUAL)}
    )


def lancamentos_manuais(transacoes: pd.DataFrame) -> pd.DataFrame:
    """As transações lançadas pelo aplicativo, da mais recente para a mais antiga."""
    manuais = transacoes[transacoes["id"].astype(str).str.startswith(PREFIXO_DO_ID)]
    return manuais.sort_values(["data", "importado_em"], ascending=False, kind="stable")


def _conferir_categoria(categoria: str, prioridade: str) -> None:
    if not categoria:
        raise ErroLancamento("Escolha ou escreva uma categoria.")
    if prioridade and prioridade not in PRIORIDADES:
        raise ErroLancamento(f"A prioridade deve ser {', '.join(PRIORIDADES)} ou ficar vazia.")
