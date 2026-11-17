"""Testes dos lançamentos manuais e da correção de categoria. Só dados fictícios."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TypedDict

import pandas as pd
import pytest

from bussola.categorias import MANUAL, PLUGGY, REGRA, categorizar, montar_regras, recategorizar
from bussola.lancamentos import (
    ENTRADA,
    GASTO,
    PREFIXO_DO_ID,
    ErroLancamento,
    corrigir_categoria,
    lancamentos_manuais,
    lancar,
)
from bussola.limpeza import CARTAO_DE_CREDITO, COLUNAS_PLANILHA, CONTA_CORRENTE, DINHEIRO, limpar
from bussola.planilha import (
    ABA_TRANSACOES,
    COLUNAS_REGRAS,
    ArmazenamentoMemoria,
    aplicar_recategorizacao,
    gravar_novas,
    ler_transacoes,
)
from bussola.pluggy import Conta, Transacao
from bussola.projecoes import NAO_E_RENDA, com_gasto_e_renda

AGORA = datetime(2026, 11, 16, 13, 30, tzinfo=UTC)  # 10:30 de 16/11 no horário de Brasília
HOJE = date(2026, 11, 16)
CORRENTE = Conta(id="corrente", tipo="BANK", subtipo="CHECKING_ACCOUNT")


def _do_banco(identificador: str, descricao: str) -> Transacao:
    return Transacao(
        id=identificador,
        conta_id=CORRENTE.id,
        data=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        descricao=descricao,
        valor=-50.0,
        tipo="DEBIT",
        status="POSTED",
        categoria="Compras",
        parcela=None,
        total_parcelas=None,
    )


def _planilha(*do_banco: Transacao) -> ArmazenamentoMemoria:
    planilha = ArmazenamentoMemoria({ABA_TRANSACOES: [list(COLUNAS_PLANILHA)]})
    if do_banco:
        gravar_novas(planilha, categorizar(limpar(list(do_banco), [CORRENTE], AGORA), []), set())
    return planilha


class Campos(TypedDict, total=False):
    """Os campos de um lançamento que um teste quer trocar."""

    tipo: str
    valor: float
    data: date
    conta: str
    descricao: str
    categoria: str
    prioridade: str
    agora: datetime


def _lancar(
    planilha: ArmazenamentoMemoria,
    *,
    tipo: str = GASTO,
    valor: float = 25.0,
    data: date = HOJE,
    conta: str = DINHEIRO,
    descricao: str = "Feira de sábado",
    categoria: str = "Supermercado",
    prioridade: str = "Essencial",
    agora: datetime = AGORA,
) -> str:
    return lancar(
        planilha,
        tipo=tipo,
        valor=valor,
        data=data,
        conta=conta,
        descricao=descricao,
        categoria=categoria,
        prioridade=prioridade,
        agora=agora,
    )


def test_gasto_manual_entra_negativo_e_marcado_como_manual() -> None:
    planilha = _planilha()

    identificador = _lancar(planilha)

    linha = dict(zip(COLUNAS_PLANILHA, planilha.ler(ABA_TRANSACOES)[1], strict=True))
    assert identificador.startswith(PREFIXO_DO_ID) and linha["id"] == identificador
    assert (linha["valor"], linha["tipo"], linha["conta"]) == (-25.0, "DEBITO", DINHEIRO)
    assert (linha["categoria"], linha["prioridade"], linha["categorizado_por"]) == (
        "Supermercado",
        "Essencial",
        MANUAL,
    )
    assert linha["descricao"] == "Feira de sábado"
    assert (linha["parcela"], linha["total_parcelas"]) == ("", "")
    assert linha["data"] == (HOJE - date(1899, 12, 30)).days
    assert linha["importado_em"] == pytest.approx((HOJE - date(1899, 12, 30)).days + 10.5 / 24)


def test_entrada_manual_entra_positiva() -> None:
    planilha = _planilha()

    _lancar(planilha, tipo=ENTRADA, valor=40.0, categoria=NAO_E_RENDA, prioridade="")

    linha = dict(zip(COLUNAS_PLANILHA, planilha.ler(ABA_TRANSACOES)[1], strict=True))
    assert (linha["valor"], linha["tipo"], linha["prioridade"]) == (40.0, "CREDITO", "")


def test_lancamento_nao_toca_nas_linhas_que_ja_existem_e_cada_um_tem_seu_id() -> None:
    planilha = _planilha(_do_banco("b1", "LOJA"))
    antes = planilha.ler(ABA_TRANSACOES)

    primeiro = _lancar(planilha)
    segundo = _lancar(planilha)

    depois = planilha.ler(ABA_TRANSACOES)
    assert depois[: len(antes)] == antes
    assert len(depois) == len(antes) + 2
    assert primeiro != segundo


@pytest.mark.parametrize(
    ("mudanca", "trecho"),
    [
        ({"valor": 0.0}, "maior que zero"),
        ({"valor": -5.0}, "maior que zero"),
        ({"data": date(2026, 11, 17)}, "futuro"),
        ({"descricao": "   "}, "descrição"),
        ({"categoria": ""}, "categoria"),
        ({"prioridade": "Urgente"}, "prioridade"),
        ({"conta": "Poupança"}, "conta"),
        ({"tipo": "Estorno"}, "tipo"),
    ],
)
def test_lancamento_invalido_e_recusado_sem_gravar(mudanca: Campos, trecho: str) -> None:
    planilha = _planilha()

    with pytest.raises(ErroLancamento, match=trecho):
        _lancar(planilha, **mudanca)

    assert len(planilha.ler(ABA_TRANSACOES)) == 1


def test_data_de_hoje_vale_pelo_dia_no_horario_de_brasilia() -> None:
    # 01:00 UTC do dia 17 ainda é 22:00 do dia 16 no horário de Brasília: lançar no dia 17 seria futuro
    quase_meia_noite = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)

    _lancar(_planilha(), data=date(2026, 11, 16), agora=quase_meia_noite)
    with pytest.raises(ErroLancamento, match="futuro"):
        _lancar(_planilha(), data=date(2026, 11, 17), agora=quase_meia_noite)


def test_lancamento_manual_sobrevive_a_recategorizacao_do_robo() -> None:
    planilha = _planilha()
    _lancar(planilha, descricao="UBER pago em dinheiro", categoria="Trabalho")
    regras = montar_regras(pd.DataFrame([["UBER", "Transporte", "Importante"]], columns=COLUNAS_REGRAS))

    aplicar_recategorizacao(planilha, recategorizar(ler_transacoes(planilha), regras, {}, {}))

    assert ler_transacoes(planilha)["categoria"].tolist() == ["Trabalho"]


def test_dinheiro_conta_como_gasto_e_como_renda_mas_nao_na_fatura() -> None:
    planilha = _planilha()
    _lancar(planilha, valor=25.0)
    _lancar(planilha, tipo=ENTRADA, valor=100.0, categoria="Renda", prioridade="")
    _lancar(planilha, tipo=ENTRADA, valor=40.0, categoria=NAO_E_RENDA, prioridade="")

    dados = com_gasto_e_renda(ler_transacoes(planilha))

    assert dados["gasto"].tolist() == [25.0, 0.0, 0.0]
    assert dados["renda"].tolist() == [0.0, 100.0, 0.0]
    assert (dados["conta"] == CARTAO_DE_CREDITO).sum() == 0


def test_lancamentos_manuais_lista_so_os_do_app_do_mais_recente_para_o_mais_antigo() -> None:
    planilha = _planilha(_do_banco("b1", "LOJA"))
    _lancar(planilha, descricao="antigo", data=date(2026, 11, 2))
    _lancar(planilha, descricao="recente", data=date(2026, 11, 15))
    corrigir_categoria(planilha, "b1", "Presentes", "Supérfluo")  # manual, mas veio do banco

    manuais = lancamentos_manuais(ler_transacoes(planilha))

    assert manuais["descricao"].tolist() == ["recente", "antigo"]


def test_corrigir_categoria_troca_so_as_tres_colunas_e_marca_como_manual() -> None:
    planilha = _planilha(_do_banco("b1", "LOJA"), _do_banco("b2", "MERCADO"))
    antes = planilha.ler(ABA_TRANSACOES)

    corrigir_categoria(planilha, "b2", " Presentes ", "Supérfluo")

    depois = planilha.ler(ABA_TRANSACOES)
    primeira = COLUNAS_PLANILHA.index("categoria")
    assert depois[2][primeira : primeira + 3] == ["Presentes", "Supérfluo", MANUAL]
    assert depois[2][:primeira] == antes[2][:primeira]
    assert depois[2][primeira + 3 :] == antes[2][primeira + 3 :]
    assert depois[:2] == antes[:2]
    assert antes[2][primeira + 2] == PLUGGY


def test_correcao_nao_e_desfeita_por_uma_regra_criada_depois() -> None:
    planilha = _planilha(_do_banco("b1", "LOJA DE PRESENTES"))
    corrigir_categoria(planilha, "b1", "Presentes", "")
    regras = montar_regras(pd.DataFrame([["LOJA", "Compras", "Supérfluo"]], columns=COLUNAS_REGRAS))

    mudancas = recategorizar(ler_transacoes(planilha), regras, {}, {})

    assert mudancas == {}
    assert REGRA not in ler_transacoes(planilha)["categorizado_por"].tolist()


@pytest.mark.parametrize(
    ("identificador", "categoria", "prioridade", "trecho"),
    [
        ("nao-existe", "Presentes", "", "não foi encontrada"),
        ("b1", "", "", "categoria"),
        ("b1", "Presentes", "Urgente", "prioridade"),
    ],
)
def test_correcao_invalida_e_recusada_sem_gravar(
    identificador: str, categoria: str, prioridade: str, trecho: str
) -> None:
    planilha = _planilha(_do_banco("b1", "LOJA"))
    antes = planilha.ler(ABA_TRANSACOES)

    with pytest.raises(ErroLancamento, match=trecho):
        corrigir_categoria(planilha, identificador, categoria, prioridade)

    assert planilha.ler(ABA_TRANSACOES) == antes


def test_id_repetido_na_planilha_impede_a_correcao() -> None:
    planilha = _planilha(_do_banco("b1", "LOJA"))
    planilha.abas[ABA_TRANSACOES].append(list(planilha.abas[ABA_TRANSACOES][1]))

    with pytest.raises(ErroLancamento, match="mais de uma linha"):
        corrigir_categoria(planilha, "b1", "Presentes", "")
