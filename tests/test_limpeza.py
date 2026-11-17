"""Testes da limpeza, só com dados fictícios."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from bussola import demo
from bussola.limpeza import COLUNA_CATEGORIA_PLUGGY, COLUNAS_PLANILHA, ErroLimpeza, limpar
from bussola.pluggy import Conta, Transacao

CORRENTE = Conta(id="corrente", tipo="BANK", subtipo="CHECKING_ACCOUNT")
CARTAO = Conta(id="cartao", tipo="CREDIT", subtipo="CREDIT_CARD")
CONTAS = [CORRENTE, CARTAO]
IMPORTADO_EM = datetime(2026, 11, 12, 13, 30, tzinfo=UTC)


def _transacao(
    identificador: str = "t1",
    conta: Conta = CORRENTE,
    valor: float = -10.0,
    tipo: str = "DEBIT",
    data: datetime = datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
    categoria: str | None = None,
    parcela: int | None = None,
    total_parcelas: int | None = None,
) -> Transacao:
    return Transacao(
        id=identificador,
        conta_id=conta.id,
        data=data,
        descricao="COMPRA FICTICIA",
        valor=valor,
        tipo=tipo,
        status="POSTED",
        categoria=categoria,
        parcela=parcela,
        total_parcelas=total_parcelas,
    )


def _limpar(*transacoes: Transacao) -> pd.DataFrame:
    return limpar(list(transacoes), CONTAS, IMPORTADO_EM)


def test_colunas_sao_as_da_planilha_na_ordem_mais_a_auxiliar() -> None:
    tabela = _limpar(_transacao())

    assert list(tabela.columns) == [*COLUNAS_PLANILHA, COLUNA_CATEGORIA_PLUGGY]


@pytest.mark.parametrize(
    ("conta", "valor_pluggy", "tipo_pluggy", "valor_esperado", "tipo_esperado"),
    [
        (CORRENTE, -25.5, "DEBIT", -25.5, "DEBITO"),
        (CORRENTE, 100.0, "CREDIT", 100.0, "CREDITO"),
        (CARTAO, 25.5, "DEBIT", -25.5, "DEBITO"),  # cartão: gasto vem positivo
        (CARTAO, -100.0, "CREDIT", 100.0, "CREDITO"),  # cartão: pagamento vem negativo
    ],
)
def test_gasto_fica_negativo_e_entrada_positiva_nas_duas_contas(
    conta: Conta, valor_pluggy: float, tipo_pluggy: str, valor_esperado: float, tipo_esperado: str
) -> None:
    linha = _limpar(_transacao(conta=conta, valor=valor_pluggy, tipo=tipo_pluggy)).iloc[0]

    assert linha["valor"] == valor_esperado
    assert linha["tipo"] == tipo_esperado


def test_nome_da_conta_e_traduzido() -> None:
    tabela = _limpar(_transacao("t1", conta=CORRENTE), _transacao("t2", conta=CARTAO))

    assert list(tabela["conta"]) == ["Conta corrente", "Cartão de crédito"]


def test_data_vira_o_dia_no_horario_de_brasilia() -> None:
    tabela = _limpar(
        # 01:00 UTC do dia 11 ainda é 22:00 do dia 10 no horário de Brasília
        _transacao("noite", data=datetime(2026, 11, 11, 1, 0, tzinfo=UTC)),
        # 03:00 UTC é meia-noite no horário de Brasília: já é dia 11
        _transacao("virada", data=datetime(2026, 11, 11, 3, 0, tzinfo=UTC)),
    )

    assert [momento.date() for momento in tabela["data"]] == [date(2026, 11, 10), date(2026, 11, 11)]
    assert all(momento.time().isoformat() == "00:00:00" for momento in tabela["data"])


def test_importado_em_fica_no_horario_de_brasilia() -> None:
    tabela = _limpar(_transacao())

    assert tabela["importado_em"].iloc[0] == pd.Timestamp("2026-11-12 10:30:00")


def test_parcelas_sao_inteiros_ou_vazias() -> None:
    tabela = _limpar(
        _transacao("parcelada", conta=CARTAO, valor=50.0, parcela=2, total_parcelas=3),
        _transacao("simples"),
    )

    assert tabela["parcela"].dtype == "Int64"
    assert (tabela["parcela"].iloc[0], tabela["total_parcelas"].iloc[0]) == (2, 3)
    assert pd.isna(tabela["parcela"].iloc[1])
    assert pd.isna(tabela["total_parcelas"].iloc[1])


def test_categoria_fica_vazia_e_a_da_pluggy_vai_para_a_coluna_auxiliar() -> None:
    tabela = _limpar(_transacao("com", categoria="Groceries"), _transacao("sem"))

    assert tabela[["categoria", "prioridade", "categorizado_por"]].isna().all().all()
    assert tabela[COLUNA_CATEGORIA_PLUGGY].iloc[0] == "Groceries"
    assert pd.isna(tabela[COLUNA_CATEGORIA_PLUGGY].iloc[1])


def test_descricao_e_id_ficam_como_vieram() -> None:
    linha = _limpar(_transacao("abc-123")).iloc[0]

    assert linha["id"] == "abc-123"
    assert linha["descricao"] == "COMPRA FICTICIA"


def test_lista_vazia_gera_tabela_vazia_com_as_mesmas_colunas_e_tipos() -> None:
    vazia = _limpar()
    cheia = _limpar(_transacao())

    assert len(vazia) == 0
    assert list(vazia.columns) == list(cheia.columns)
    assert list(vazia.dtypes) == list(cheia.dtypes)


def test_tipo_de_transacao_desconhecido_da_erro() -> None:
    with pytest.raises(ErroLimpeza, match="Tipo de transação"):
        _limpar(_transacao(tipo="ESTORNO"))


def test_tipo_de_conta_desconhecido_da_erro() -> None:
    poupanca = Conta(id="poupanca", tipo="INVESTMENT", subtipo="SAVINGS")

    with pytest.raises(ErroLimpeza, match="Tipo de conta"):
        limpar([], [poupanca], IMPORTADO_EM)


def test_transacao_de_conta_fora_da_lista_da_erro() -> None:
    with pytest.raises(ErroLimpeza, match="não está na lista"):
        limpar([_transacao()], [CARTAO], IMPORTADO_EM)


def test_data_sem_fuso_da_erro() -> None:
    with pytest.raises(ErroLimpeza, match="fuso"):
        _limpar(_transacao(data=datetime(2026, 11, 10, 15, 0)))


def test_dados_do_modo_demo_passam_pela_limpeza() -> None:
    contas, transacoes = demo.contas_e_transacoes(date(2026, 11, 12))

    tabela = limpar(transacoes, contas, IMPORTADO_EM)

    assert len(tabela) == len(transacoes)
    assert tabela["id"].is_unique
    assert (tabela.loc[tabela["tipo"] == "DEBITO", "valor"] < 0).all()
    assert (tabela.loc[tabela["tipo"] == "CREDITO", "valor"] > 0).all()
    assert set(tabela["conta"]) == {"Conta corrente", "Cartão de crédito"}
