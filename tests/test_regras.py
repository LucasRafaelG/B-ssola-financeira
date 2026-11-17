"""Testes da criação de regras: validação, gravação, cobertura e prévia. Só dados fictícios."""

from __future__ import annotations

import pandas as pd
import pytest

from bussola.categorias import (
    MANUAL,
    PLUGGY,
    REGRA,
    SEM_REGRA,
    ErroRegra,
    PreviaDaRegra,
    cobertura_das_regras,
    previa_da_regra,
    validar_regra,
)
from bussola.limpeza import COLUNAS_PLANILHA
from bussola.planilha import (
    ABA_REGRAS,
    COLUNAS_REGRAS,
    ArmazenamentoMemoria,
    Celula,
    ErroPlanilha,
    acrescentar_regra,
    apagar_regra,
    editar_regra,
)

REGRAS_INICIAIS: list[list[Celula]] = [
    ["IFOOD", "Alimentação", "Supérfluo"],
    ["UBER", "Transporte", "Importante"],
    ["UBER EATS", "Alimentação", "Supérfluo"],
    ["", "Linha vazia", ""],
]


def _planilha() -> ArmazenamentoMemoria:
    return ArmazenamentoMemoria(
        {ABA_REGRAS: [list(COLUNAS_REGRAS), *[list(linha) for linha in REGRAS_INICIAIS]]}
    )


def _tabela_de_regras() -> pd.DataFrame:
    return pd.DataFrame(REGRAS_INICIAIS, columns=COLUNAS_REGRAS)


def _transacoes(*linhas: tuple[str, str]) -> pd.DataFrame:
    """Cada linha: descrição, categorizado_por."""
    tabela = pd.DataFrame("", index=range(len(linhas)), columns=COLUNAS_PLANILHA)
    tabela["descricao"] = [linha[0] for linha in linhas]
    tabela["categorizado_por"] = [linha[1] for linha in linhas]
    return tabela


TRANSACOES = _transacoes(
    ("IFOOD *RESTAURANTE", REGRA),
    ("ifood *outro", REGRA),
    ("UBER *TRIP", REGRA),
    ("UBER   EATS PEDIDO", REGRA),
    ("PADARIA DO ZÉ", PLUGGY),
    ("Padaria do Ze 2", SEM_REGRA),
    ("PADARIA DO ZE", MANUAL),
    ("MERCADO", PLUGGY),
)


def test_regra_nova_entra_no_fim_e_as_antigas_ficam_intactas() -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_REGRAS)

    acrescentar_regra(planilha, "  Padaria do Zé ", " Alimentação ", "Importante")

    depois = planilha.ler(ABA_REGRAS)
    assert depois[:-1] == antes
    assert depois[-1] == ["Padaria do Zé", "Alimentação", "Importante"]


def test_regra_sem_prioridade_e_aceita() -> None:
    planilha = _planilha()

    acrescentar_regra(planilha, "Pagamento de fatura", "Pagamento de cartão de crédito", "")

    assert planilha.ler(ABA_REGRAS)[-1] == ["Pagamento de fatura", "Pagamento de cartão de crédito", ""]


@pytest.mark.parametrize(
    ("palavra_chave", "categoria", "prioridade", "trecho"),
    [
        ("", "Alimentação", "Essencial", "palavra-chave"),
        ("   ", "Alimentação", "Essencial", "palavra-chave"),
        ("PADARIA", "", "Essencial", "categoria"),
        ("PADARIA", "   ", "Essencial", "categoria"),
        ("PADARIA", "Alimentação", "Urgente", "prioridade"),
        ("ifood", "Outra", "Essencial", "Já existe"),
        ("I F O O D", "Outra", "Essencial", "Já existe"),
        ("Uber Éats", "Outra", "Essencial", "Já existe"),
    ],
)
def test_regra_invalida_e_recusada_sem_gravar(
    palavra_chave: str, categoria: str, prioridade: str, trecho: str
) -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_REGRAS)

    with pytest.raises(ErroRegra, match=trecho):
        acrescentar_regra(planilha, palavra_chave, categoria, prioridade)

    assert planilha.ler(ABA_REGRAS) == antes


def test_aba_de_regras_com_cabecalho_errado_nao_recebe_regra() -> None:
    planilha = ArmazenamentoMemoria({ABA_REGRAS: [["palavra", "categoria", "prioridade"]]})

    with pytest.raises(ErroPlanilha, match="cabeçalho"):
        acrescentar_regra(planilha, "PADARIA", "Alimentação", "Essencial")

    assert planilha.ler(ABA_REGRAS) == [["palavra", "categoria", "prioridade"]]


def test_validar_regra_devolve_os_textos_sem_espacos_sobrando() -> None:
    assert validar_regra(" Padaria ", " Alimentação ", " Essencial ", _tabela_de_regras()) == (
        "Padaria",
        "Alimentação",
        "Essencial",
    )


def test_cobertura_conta_cada_transacao_para_a_regra_que_vence_nela() -> None:
    cobertura = cobertura_das_regras(_tabela_de_regras(), TRANSACOES)

    # "UBER EATS PEDIDO" conta para UBER EATS (mais longa), não para UBER; a linha vazia some
    assert cobertura.to_dict("records") == [
        {"palavra_chave": "IFOOD", "categoria": "Alimentação", "prioridade": "Supérfluo", "cobre": 2},
        {"palavra_chave": "UBER", "categoria": "Transporte", "prioridade": "Importante", "cobre": 1},
        {"palavra_chave": "UBER EATS", "categoria": "Alimentação", "prioridade": "Supérfluo", "cobre": 1},
    ]


def test_cobertura_sem_regras_ou_sem_transacoes() -> None:
    sem_regras = pd.DataFrame(columns=COLUNAS_REGRAS)

    assert cobertura_das_regras(sem_regras, TRANSACOES).empty
    assert cobertura_das_regras(_tabela_de_regras(), _transacoes())["cobre"].tolist() == [0, 0, 0]


def test_previa_separa_o_que_mudaria_do_que_fica_como_esta() -> None:
    assert previa_da_regra("padaria do zé", TRANSACOES) == PreviaDaRegra(
        encontradas=3, mudariam=2, manuais=1, ja_com_regra=0
    )
    assert previa_da_regra("UBER", TRANSACOES) == PreviaDaRegra(
        encontradas=2, mudariam=0, manuais=0, ja_com_regra=2
    )


def test_previa_de_palavra_chave_vazia_ou_que_nao_aparece() -> None:
    assert previa_da_regra("   ", TRANSACOES) == PreviaDaRegra(0, 0, 0, 0)
    assert previa_da_regra("FARMACIA", TRANSACOES) == PreviaDaRegra(0, 0, 0, 0)


def test_editar_troca_a_regra_no_mesmo_lugar_e_nao_toca_nas_outras() -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_REGRAS)

    editar_regra(planilha, "uber", " UBER TRIP ", " Transporte ", "Essencial")

    depois = planilha.ler(ABA_REGRAS)
    assert depois[2] == ["UBER TRIP", "Transporte", "Essencial"]
    assert depois[:2] == antes[:2] and depois[3:] == antes[3:]


def test_editar_pode_manter_a_mesma_palavra_chave() -> None:
    planilha = _planilha()

    editar_regra(planilha, "IFOOD", "iFood", "Lazer", "")

    assert planilha.ler(ABA_REGRAS)[1] == ["iFood", "Lazer", ""]


@pytest.mark.parametrize(
    ("atual", "nova_palavra", "categoria", "prioridade", "trecho"),
    [
        ("IFOOD", "Uber Eats", "Alimentação", "", "Já existe"),
        ("IFOOD", "", "Alimentação", "", "palavra-chave"),
        ("IFOOD", "IFOOD", "", "", "categoria"),
        ("IFOOD", "IFOOD", "Alimentação", "Urgente", "prioridade"),
        ("NAO EXISTE", "NOVA", "Alimentação", "", "não foi encontrada"),
        ("", "NOVA", "Alimentação", "", "não foi encontrada"),
    ],
)
def test_edicao_invalida_e_recusada_sem_gravar(
    atual: str, nova_palavra: str, categoria: str, prioridade: str, trecho: str
) -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_REGRAS)

    with pytest.raises(ErroRegra, match=trecho):
        editar_regra(planilha, atual, nova_palavra, categoria, prioridade)

    assert planilha.ler(ABA_REGRAS) == antes


def test_apagar_tira_so_aquela_regra() -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_REGRAS)

    apagar_regra(planilha, "u b e r")

    assert planilha.ler(ABA_REGRAS) == [antes[0], antes[1], antes[3], antes[4]]


def test_apagar_regra_que_nao_existe_nao_grava() -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_REGRAS)

    with pytest.raises(ErroRegra, match="não foi encontrada"):
        apagar_regra(planilha, "FARMACIA")

    assert planilha.ler(ABA_REGRAS) == antes


def test_palavra_chave_repetida_na_planilha_impede_editar_e_apagar() -> None:
    planilha = _planilha()
    planilha.abas[ABA_REGRAS].append(["ifood", "Outra", ""])
    antes = planilha.ler(ABA_REGRAS)

    with pytest.raises(ErroRegra, match="mais de uma regra"):
        editar_regra(planilha, "IFOOD", "IFOOD", "Lazer", "")
    with pytest.raises(ErroRegra, match="mais de uma regra"):
        apagar_regra(planilha, "IFOOD")

    assert planilha.ler(ABA_REGRAS) == antes
