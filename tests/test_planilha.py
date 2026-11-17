"""Testes da leitura e da gravação, com uma planilha em memória (nada de rede)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from bussola import demo
from bussola.categorias import MANUAL, REGRA, SEM_CATEGORIA, SEM_REGRA, Classificacao, categorizar
from bussola.limpeza import COLUNAS_PLANILHA, limpar
from bussola.planilha import (
    ABA_REGRAS,
    ABA_TRANSACOES,
    COLUNAS_REGRAS,
    ArmazenamentoMemoria,
    ErroPlanilha,
    aplicar_recategorizacao,
    gravar_novas,
    ler_tabela,
    ler_transacoes,
)
from bussola.pluggy import Conta, Transacao

CORRENTE = Conta(id="corrente", tipo="BANK", subtipo="CHECKING_ACCOUNT")
CARTAO = Conta(id="cartao", tipo="CREDIT", subtipo="CREDIT_CARD")
IMPORTADO_EM = datetime(2026, 11, 12, 13, 30, tzinfo=UTC)  # 10:30 no horário de Brasília


def _transacao(
    identificador: str,
    descricao: str = "COMPRA FICTICIA",
    conta: Conta = CORRENTE,
    valor: float = -10.5,
    parcela: int | None = None,
    total_parcelas: int | None = None,
) -> Transacao:
    return Transacao(
        id=identificador,
        conta_id=conta.id,
        data=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        descricao=descricao,
        valor=valor,
        tipo="DEBIT",
        status="POSTED",
        categoria=None,
        parcela=parcela,
        total_parcelas=total_parcelas,
    )


def _tabela(*transacoes: Transacao) -> pd.DataFrame:
    return categorizar(limpar(list(transacoes), [CORRENTE, CARTAO], IMPORTADO_EM), [])


def _planilha_vazia() -> ArmazenamentoMemoria:
    return ArmazenamentoMemoria({ABA_TRANSACOES: [list(COLUNAS_PLANILHA)]})


def _ids(planilha: ArmazenamentoMemoria) -> set[str]:
    return set(ler_transacoes(planilha)["id"].astype(str))


def _gravar(planilha: ArmazenamentoMemoria, tabela: pd.DataFrame) -> int:
    return len(gravar_novas(planilha, tabela, _ids(planilha)))


def test_planilha_vazia_recebe_todas_as_transacoes() -> None:
    planilha = _planilha_vazia()

    gravadas = _gravar(planilha, _tabela(_transacao("t1"), _transacao("t2")))

    assert gravadas == 2
    assert _ids(planilha) == {"t1", "t2"}


def test_rodar_duas_vezes_nao_duplica_nada() -> None:
    planilha = _planilha_vazia()
    tabela = _tabela(_transacao("t1"), _transacao("t2"))
    _gravar(planilha, tabela)
    depois_da_primeira = planilha.ler(ABA_TRANSACOES)

    gravadas = _gravar(planilha, tabela)

    assert gravadas == 0
    assert planilha.ler(ABA_TRANSACOES) == depois_da_primeira


def test_so_as_novas_entram_e_as_antigas_ficam_intactas() -> None:
    planilha = _planilha_vazia()
    _gravar(planilha, _tabela(_transacao("t1", descricao="ANTIGA")))
    # simula uma edição feita à mão na planilha
    planilha.abas[ABA_TRANSACOES][1][COLUNAS_PLANILHA.index("categoria")] = "Editada à mão"
    antiga = list(planilha.abas[ABA_TRANSACOES][1])

    gravadas = _gravar(planilha, _tabela(_transacao("t1", descricao="MUDOU"), _transacao("t2")))

    linhas = planilha.ler(ABA_TRANSACOES)
    assert gravadas == 1
    assert linhas[1] == antiga
    assert [linha[0] for linha in linhas[1:]] == ["t1", "t2"]


def test_id_repetido_no_mesmo_lote_entra_uma_vez() -> None:
    planilha = _planilha_vazia()

    gravadas = _gravar(planilha, _tabela(_transacao("t1"), _transacao("t1")))

    assert gravadas == 1
    assert len(planilha.ler(ABA_TRANSACOES)) == 2


def test_celulas_vao_como_numeros_e_datas_de_verdade() -> None:
    planilha = _planilha_vazia()
    parcelada = _transacao("t1", conta=CARTAO, valor=119.9, parcela=2, total_parcelas=3)

    _gravar(planilha, _tabela(parcelada))

    linha = dict(zip(COLUNAS_PLANILHA, planilha.ler(ABA_TRANSACOES)[1], strict=True))
    dia_da_compra = (date(2026, 11, 10) - date(1899, 12, 30)).days
    assert linha["valor"] == -119.9
    assert isinstance(linha["valor"], float)
    assert linha["data"] == dia_da_compra
    assert isinstance(linha["data"], int)
    assert linha["importado_em"] == pytest.approx(dia_da_compra + 2 + 10.5 / 24)
    assert (linha["parcela"], linha["total_parcelas"]) == (2, 3)
    assert isinstance(linha["parcela"], int)
    assert linha["conta"] == "Cartão de crédito"
    assert linha["tipo"] == "DEBITO"


def test_campos_vazios_viram_celula_vazia_e_categoria_provisoria_e_gravada() -> None:
    planilha = _planilha_vazia()

    _gravar(planilha, _tabela(_transacao("t1")))

    linha = dict(zip(COLUNAS_PLANILHA, planilha.ler(ABA_TRANSACOES)[1], strict=True))
    assert (linha["parcela"], linha["total_parcelas"], linha["prioridade"]) == ("", "", "")
    assert (linha["categoria"], linha["categorizado_por"]) == (SEM_CATEGORIA, SEM_REGRA)


def test_linha_gravada_tem_so_as_colunas_da_planilha() -> None:
    planilha = _planilha_vazia()

    _gravar(planilha, _tabela(_transacao("t1")))

    assert len(planilha.ler(ABA_TRANSACOES)[1]) == len(COLUNAS_PLANILHA)


def test_descricao_com_cara_de_formula_segue_como_texto() -> None:
    planilha = _planilha_vazia()

    _gravar(planilha, _tabela(_transacao("t1", descricao="=SOMA(A1:A9)")))

    descricao = planilha.ler(ABA_TRANSACOES)[1][COLUNAS_PLANILHA.index("descricao")]
    assert descricao == "=SOMA(A1:A9)"


@pytest.mark.parametrize(
    "cabecalho",
    [
        [],
        ["id", "data"],
        [*COLUNAS_PLANILHA[:3], "descricao2", *COLUNAS_PLANILHA[4:]],
        list(reversed(COLUNAS_PLANILHA)),
    ],
)
def test_cabecalho_diferente_do_esperado_interrompe_sem_gravar(cabecalho: list[str]) -> None:
    planilha = ArmazenamentoMemoria({ABA_TRANSACOES: [list(cabecalho)] if cabecalho else []})
    antes = planilha.ler(ABA_TRANSACOES)

    with pytest.raises(ErroPlanilha, match="cabeçalho"):
        _gravar(planilha, _tabela(_transacao("t1")))

    assert planilha.ler(ABA_TRANSACOES) == antes


def test_aba_inexistente_da_erro() -> None:
    with pytest.raises(ErroPlanilha, match="não existe"):
        ler_tabela(_planilha_vazia(), ABA_REGRAS, COLUNAS_REGRAS)


def test_ler_tabela_completa_as_celulas_vazias_do_fim_da_linha() -> None:
    planilha = ArmazenamentoMemoria(
        {ABA_REGRAS: [list(COLUNAS_REGRAS), ["IFOOD", "Alimentação", "Supérfluo"], ["UBER"]]}
    )

    regras = ler_tabela(planilha, ABA_REGRAS, COLUNAS_REGRAS)

    assert list(regras.columns) == COLUNAS_REGRAS
    assert regras.iloc[1].tolist() == ["UBER", "", ""]


def test_modo_demo_grava_na_planilha_ficticia_sem_duplicar() -> None:
    planilha = demo.planilha_ficticia()
    contas, transacoes = demo.contas_e_transacoes(date(2026, 11, 12))
    tabela = categorizar(limpar(transacoes, contas, IMPORTADO_EM), [])

    primeira = _gravar(planilha, tabela)
    segunda = _gravar(planilha, tabela)

    assert (primeira, segunda) == (len(transacoes), 0)
    assert len(ler_tabela(planilha, ABA_REGRAS, COLUNAS_REGRAS)) == 5


def test_recategorizacao_troca_so_as_tres_colunas_de_categoria() -> None:
    planilha = _planilha_vazia()
    _gravar(planilha, _tabela(_transacao("t1"), _transacao("t2"), _transacao("t3")))
    antes = planilha.ler(ABA_TRANSACOES)

    aplicar_recategorizacao(planilha, {1: Classificacao("Transporte", "Importante", REGRA)})

    depois = planilha.ler(ABA_TRANSACOES)
    primeira = COLUNAS_PLANILHA.index("categoria")
    assert depois[2][primeira : primeira + 3] == ["Transporte", "Importante", REGRA]
    assert depois[2][:primeira] == antes[2][:primeira]
    assert depois[2][primeira + 3 :] == antes[2][primeira + 3 :]
    assert [depois[0], depois[1], depois[3]] == [antes[0], antes[1], antes[3]]


def test_recategorizacao_sem_mudancas_nao_escreve_nada() -> None:
    planilha = _planilha_vazia()
    _gravar(planilha, _tabela(_transacao("t1")))
    antes = planilha.ler(ABA_TRANSACOES)

    aplicar_recategorizacao(planilha, {})

    assert planilha.ler(ABA_TRANSACOES) == antes


def test_linha_marcada_como_manual_sobrevive_a_uma_execucao_completa() -> None:
    from bussola.categorias import montar_regras, recategorizar

    planilha = _planilha_vazia()
    _gravar(planilha, _tabela(_transacao("t1", descricao="UBER *TRIP"), _transacao("t2", descricao="UBER *TRIP")))
    primeira = COLUNAS_PLANILHA.index("categoria")
    planilha.abas[ABA_TRANSACOES][1][primeira : primeira + 3] = ["Trabalho", "Essencial", MANUAL]
    regras = montar_regras(pd.DataFrame([["UBER", "Transporte", "Importante"]], columns=COLUNAS_REGRAS))

    aplicar_recategorizacao(planilha, recategorizar(ler_transacoes(planilha), regras, {}, {}))

    linhas = planilha.ler(ABA_TRANSACOES)
    assert linhas[1][primeira : primeira + 3] == ["Trabalho", "Essencial", MANUAL]
    assert linhas[2][primeira : primeira + 3] == ["Transporte", "Importante", REGRA]
