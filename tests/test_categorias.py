"""Testes da categorização, só com dados fictícios."""

from __future__ import annotations

import pandas as pd
import pytest

from bussola.categorias import (
    MANUAL,
    PLUGGY,
    REGRA,
    SEM_CATEGORIA,
    SEM_REGRA,
    Classificacao,
    Regra,
    categorizar,
    classificar,
    descricoes_sem_regra,
    montar_regras,
    normalizar,
    precisam_da_pluggy,
    recategorizar,
)
from bussola.limpeza import COLUNA_CATEGORIA_PLUGGY, COLUNAS_PLANILHA
from bussola.planilha import COLUNAS_REGRAS


def _regras(*linhas: tuple[str, str, str]) -> list[Regra]:
    return montar_regras(pd.DataFrame(list(linhas), columns=COLUNAS_REGRAS))


REGRAS = _regras(
    ("IFOOD", "Alimentação", "Supérfluo"),
    ("UBER", "Transporte", "Importante"),
    ("Padaria Pão Quente", "Alimentação", "Supérfluo"),
    ("StreamingMax", "Assinaturas", "Supérfluo"),
)


def _gravadas(*linhas: tuple[str, str, str, str, str]) -> pd.DataFrame:
    """Tabela como a lida da planilha. Cada linha: id, descrição, categoria, prioridade, quem."""
    tabela = pd.DataFrame("", index=range(len(linhas)), columns=COLUNAS_PLANILHA)
    for posicao, (identificador, descricao, categoria, prioridade, quem) in enumerate(linhas):
        tabela.loc[posicao, ["id", "descricao", "categoria", "prioridade", "categorizado_por"]] = [
            identificador,
            descricao,
            categoria,
            prioridade,
            quem,
        ]
    return tabela


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("STREAMING MAX", "streamingmax"),
        ("StreamingMax", "streamingmax"),
        ("  Farmácia São João ", "farmaciasaojoao"),
        ("AÇAÍ\tDO\nZÉ", "acaidoze"),
        ("", ""),
    ],
)
def test_normalizar_ignora_maiusculas_acentos_e_espacos(texto: str, esperado: str) -> None:
    assert normalizar(texto) == esperado


@pytest.mark.parametrize(
    ("descricao", "categoria"),
    [
        ("IFOOD *RESTAURANTE", "Alimentação"),
        ("ifood *restaurante", "Alimentação"),
        ("Pag*IFood Sao Paulo", "Alimentação"),
        ("STREAMING MAX", "Assinaturas"),
        ("S T R E A M I N G M A X assinatura", "Assinaturas"),
        ("PADARIA PAO QUENTE", "Alimentação"),
        ("padariapãoquente centro", "Alimentação"),
    ],
)
def test_regra_casa_quando_a_palavra_chave_esta_contida(descricao: str, categoria: str) -> None:
    resultado = classificar(descricao, None, REGRAS)

    assert (resultado.categoria, resultado.categorizado_por) == (categoria, REGRA)


def test_regra_traz_a_prioridade() -> None:
    assert classificar("UBER *TRIP", None, REGRAS) == Classificacao("Transporte", "Importante", REGRA)


def test_quando_varias_regras_casam_vence_a_palavra_chave_mais_longa() -> None:
    regras = _regras(
        ("UBER", "Transporte", "Importante"),
        ("UBER EATS", "Alimentação", "Supérfluo"),
    )

    assert classificar("UBER   EATS PEDIDO", None, regras).categoria == "Alimentação"
    assert classificar("UBER *TRIP", None, regras).categoria == "Transporte"


def test_empate_de_tamanho_vence_a_regra_mais_acima_na_planilha() -> None:
    regras = _regras(("LOJA A", "Primeira", "Essencial"), ("A LOJA", "Segunda", "Supérfluo"))

    # as duas palavras-chave têm 5 letras depois de normalizadas e as duas casam
    assert classificar("A LOJA A", None, regras).categoria == "Primeira"


def test_regra_vence_a_categoria_da_pluggy() -> None:
    assert classificar("IFOOD", "Food delivery", REGRAS).categorizado_por == REGRA


def test_sem_regra_usa_a_categoria_da_pluggy_com_prioridade_vazia() -> None:
    assert classificar("MERCADO", "Groceries", REGRAS) == Classificacao("Groceries", "", PLUGGY)


def test_sem_regra_e_sem_pluggy_fica_sem_categoria() -> None:
    assert classificar("MERCADO", None, REGRAS) == Classificacao(SEM_CATEGORIA, "", SEM_REGRA)
    assert classificar("MERCADO", "", REGRAS).categorizado_por == SEM_REGRA


def test_linhas_de_regra_sem_palavra_chave_sao_ignoradas() -> None:
    regras = _regras(("", "Vazia", "Essencial"), ("   ", "Espaços", "Essencial"))

    assert regras == []
    assert classificar("QUALQUER COISA", None, regras).categorizado_por == SEM_REGRA


def test_categorizar_preenche_as_tres_colunas_da_tabela() -> None:
    tabela = pd.DataFrame(
        {
            "descricao": ["UBER *TRIP", "MERCADO", "LOJA"],
            COLUNA_CATEGORIA_PLUGGY: pd.array([None, "Groceries", None], dtype="str"),
            "categoria": pd.array([None, None, None], dtype="str"),
            "prioridade": pd.array([None, None, None], dtype="str"),
            "categorizado_por": pd.array([None, None, None], dtype="str"),
        }
    )

    resultado = categorizar(tabela, REGRAS)

    assert list(resultado["categoria"]) == ["Transporte", "Groceries", SEM_CATEGORIA]
    assert list(resultado["prioridade"]) == ["Importante", "", ""]
    assert list(resultado["categorizado_por"]) == [REGRA, PLUGGY, SEM_REGRA]


def test_recategorizar_aplica_regra_nova_em_linhas_sem_regra_e_pluggy() -> None:
    gravadas = _gravadas(
        ("a", "UBER *TRIP", SEM_CATEGORIA, "", SEM_REGRA),
        ("b", "IFOOD *REST", "Food delivery", "", PLUGGY),
    )

    mudancas = recategorizar(gravadas, REGRAS, {}, {})

    assert mudancas == {
        0: Classificacao("Transporte", "Importante", REGRA),
        1: Classificacao("Alimentação", "Supérfluo", REGRA),
    }


def test_recategorizar_nunca_toca_em_linhas_manual_nem_de_origem_desconhecida() -> None:
    gravadas = _gravadas(
        ("a", "UBER *TRIP", "Trabalho", "Essencial", MANUAL),
        ("c", "UBER *TRIP", "Qualquer", "", "valor estranho"),
    )

    assert recategorizar(gravadas, REGRAS, {"a": "Taxi", "c": "Taxi"}, {"Trabalho": "X"}) == {}


def test_linha_de_regra_acompanha_a_regra_como_ela_esta_hoje() -> None:
    gravadas = _gravadas(
        # a regra UBER mudou de categoria e prioridade depois que a linha foi gravada
        ("a", "UBER *TRIP", "Categoria antiga", "Supérfluo", REGRA),
        # já está de acordo com a regra atual: não muda
        ("b", "IFOOD *REST", "Alimentação", "Supérfluo", REGRA),
    )

    assert recategorizar(gravadas, REGRAS, {}, {}) == {
        0: Classificacao("Transporte", "Importante", REGRA)
    }


def test_linha_de_regra_passa_para_a_regra_mais_longa_criada_depois() -> None:
    regras = _regras(
        ("UBER", "Transporte", "Importante"),
        ("UBER EATS", "Alimentação", "Supérfluo"),
    )
    gravadas = _gravadas(("a", "UBER EATS PEDIDO", "Transporte", "Importante", REGRA))

    assert recategorizar(gravadas, regras, {}, {}) == {
        0: Classificacao("Alimentação", "Supérfluo", REGRA)
    }


def test_linha_que_perdeu_a_regra_vai_para_a_pluggy_ou_fica_sem_categoria() -> None:
    sem_ifood = _regras(("UBER", "Transporte", "Importante"))
    gravadas = _gravadas(
        ("a", "IFOOD *REST", "Alimentação", "Supérfluo", REGRA),
        ("b", "IFOOD *OUTRO", "Alimentação", "Supérfluo", REGRA),
    )

    mudancas = recategorizar(gravadas, sem_ifood, {"a": "Delivery de comida"}, {})

    assert mudancas == {
        0: Classificacao("Delivery de comida", "", PLUGGY),
        1: Classificacao(SEM_CATEGORIA, "", SEM_REGRA),
    }


def test_precisam_da_pluggy_as_sem_categoria_e_as_que_perderam_a_regra() -> None:
    gravadas = _gravadas(
        ("sem", "PADARIA", SEM_CATEGORIA, "", SEM_REGRA),
        ("perdeu", "LOJA ANTIGA", "Compras", "", REGRA),
        ("coberta", "UBER *TRIP", "Transporte", "Importante", REGRA),
        ("pluggy", "MERCADO", "Supermercado", "", PLUGGY),
        ("manual", "LOJA ANTIGA", "Presentes", "", MANUAL),
    )

    assert precisam_da_pluggy(gravadas, REGRAS) == {"sem", "perdeu"}


def test_recategorizar_usa_a_pluggy_so_em_linhas_sem_regra() -> None:
    gravadas = _gravadas(
        ("a", "MERCADO", SEM_CATEGORIA, "", SEM_REGRA),
        ("b", "MERCADO", "Groceries", "", PLUGGY),
        ("c", "PADARIA", SEM_CATEGORIA, "", SEM_REGRA),
    )

    mudancas = recategorizar(gravadas, REGRAS, {"a": "Groceries", "b": "Outra coisa"}, {})

    assert mudancas == {0: Classificacao("Groceries", "", PLUGGY)}


def test_recategorizar_nao_devolve_linhas_que_ficariam_iguais() -> None:
    gravadas = _gravadas(("a", "PADARIA", SEM_CATEGORIA, "", SEM_REGRA))

    assert recategorizar(gravadas, REGRAS, {}, {}) == {}


def test_recategorizar_traduz_a_categoria_de_linhas_pluggy_e_so_delas() -> None:
    traducoes = {"Groceries": "Supermercado", "Lazer": "NAO DEVE APARECER"}
    gravadas = _gravadas(
        ("a", "MERCADO", "Groceries", "", PLUGGY),
        ("b", "MERCADO", "Supermercado", "", PLUGGY),
        ("c", "MERCADO", "Categoria sem tradução", "", PLUGGY),
        ("d", "CINEMA", "Lazer", "Supérfluo", MANUAL),
        ("e", "IFOOD", "Groceries", "", PLUGGY),
    )

    mudancas = recategorizar(gravadas, REGRAS, {}, traducoes)

    assert mudancas == {
        0: Classificacao("Supermercado", "", PLUGGY),
        4: Classificacao("Alimentação", "Supérfluo", REGRA),
    }


def test_descricoes_sem_regra_conta_e_ordena_pelas_mais_frequentes() -> None:
    gravadas = _gravadas(
        ("a", "PADARIA", "Bakery", "", PLUGGY),
        ("b", "MERCADO", SEM_CATEGORIA, "", SEM_REGRA),
        ("c", "PADARIA", "Bakery", "", PLUGGY),
        ("d", "UBER *TRIP", "Transporte", "Importante", REGRA),
        ("e", "ALGO MANUAL", "Lazer", "Supérfluo", MANUAL),
        ("f", "FARMACIA", "Pharmacy", "", PLUGGY),
    )

    resumo = descricoes_sem_regra(gravadas, quantas=2)

    assert resumo.to_dict("records") == [
        {"descricao": "PADARIA", "vezes": 2, "categoria_atual": "Bakery"},
        {"descricao": "FARMACIA", "vezes": 1, "categoria_atual": "Pharmacy"},
    ]
