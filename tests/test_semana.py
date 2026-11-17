"""Testes do resumo semanal, só com dados fictícios."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from bussola.formatos import dia_da_semana, periodo
from bussola.limpeza import CARTAO_DE_CREDITO, COLUNAS_PLANILHA, CONTA_CORRENTE
from bussola.semana import inicio_da_semana, resumir_semana, semanas_disponiveis

PAGAMENTO = "Pagamento de cartão de crédito"
SEGUNDA = date(2026, 11, 9)  # semana de 9 a 15 de novembro
HOJE = date(2026, 11, 20)

# (data, descrição, valor, conta, categoria, categorizado_por)
Linha = tuple[str, str, float, str, str, str]


def _transacoes(*linhas: Linha) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [f"t{numero}" for numero in range(len(linhas))],
            "data": pd.to_datetime([linha[0] for linha in linhas]),
            "descricao": [linha[1] for linha in linhas],
            "valor": [float(linha[2]) for linha in linhas],
            "tipo": ["DEBITO" if linha[2] < 0 else "CREDITO" for linha in linhas],
            "conta": [linha[3] for linha in linhas],
            "categoria": [linha[4] for linha in linhas],
            "prioridade": "",
            "categorizado_por": [linha[5] for linha in linhas],
            "parcela": pd.array([None] * len(linhas), dtype="Int64"),
            "total_parcelas": pd.array([None] * len(linhas), dtype="Int64"),
            "importado_em": pd.Timestamp("2026-11-20 10:00"),
        }
    )[COLUNAS_PLANILHA]


DADOS = _transacoes(
    # base: 12 semanas antes de 09/11 começam em 17/08; o histórico começa em 31/08 (70 dias)
    ("2026-08-31", "MERCADO", -700.0, CONTA_CORRENTE, "Supermercado", "pluggy"),
    ("2026-10-10", "UBER", -140.0, CONTA_CORRENTE, "Transporte", "regra"),
    # semana anterior (2 a 8 de novembro)
    ("2026-11-03", "MERCADO", -90.0, CONTA_CORRENTE, "Supermercado", "pluggy"),
    # a semana (9 a 15 de novembro)
    ("2026-11-09", "UBER", -42.0, CONTA_CORRENTE, "Transporte", "regra"),
    ("2026-11-11", "RESTAURANTE", -95.0, CARTAO_DE_CREDITO, "Alimentação", "pluggy"),
    ("2026-11-13", "MERCADO", -131.0, CONTA_CORRENTE, "Supermercado", "pluggy"),
    ("2026-11-13", "RESTAURANTE", -20.0, CARTAO_DE_CREDITO, "Alimentação", "pluggy"),
    ("2026-11-14", "ESTORNO RESTAURANTE", 15.0, CARTAO_DE_CREDITO, "Alimentação", "pluggy"),
    ("2026-11-12", "CLIENTE", 600.0, CONTA_CORRENTE, "Renda", "manual"),
    ("2026-11-10", "PAGAMENTO DE FATURA", -400.0, CONTA_CORRENTE, PAGAMENTO, "regra"),
    ("2026-11-10", "PAGAMENTO RECEBIDO", 400.0, CARTAO_DE_CREDITO, PAGAMENTO, "pluggy"),
    # semana seguinte
    ("2026-11-16", "PADARIA", -9.0, CONTA_CORRENTE, "Padaria", "pluggy"),
)


def test_semana_comeca_na_segunda() -> None:
    assert inicio_da_semana(date(2026, 11, 9)) == date(2026, 11, 9)
    assert inicio_da_semana(date(2026, 11, 15)) == date(2026, 11, 9)
    assert inicio_da_semana(date(2026, 11, 16)) == date(2026, 11, 16)


def test_semanas_disponiveis_vao_da_atual_ate_a_primeira_com_historico() -> None:
    semanas = semanas_disponiveis(DADOS, HOJE)

    assert semanas[0] == date(2026, 11, 16)
    assert semanas[-1] == date(2026, 8, 31)
    assert len(semanas) == 12
    assert semanas_disponiveis(_transacoes(), HOJE) == [date(2026, 11, 16)]


def test_totais_da_semana_ignoram_movimentos_internos() -> None:
    resumo = resumir_semana(DADOS, SEGUNDA, HOJE)

    # 42 + 95 + 131 + 20 - 15 (estorno) = 273; o pagamento da fatura não conta
    assert resumo.gasto == 273.0
    assert resumo.gasto_da_semana_anterior == 90.0
    assert (resumo.renda, resumo.entradas) == (600.0, 1)
    assert (resumo.inicio, resumo.fim, resumo.dias_decorridos) == (SEGUNDA, date(2026, 11, 15), 7)
    # 6 transações contam (as 2 do pagamento da fatura ficam fora)
    assert resumo.transacoes == 6
    # sem regra: restaurante (2), mercado e estorno; UBER é regra e CLIENTE é manual
    assert resumo.sem_regra == 4


def test_gasto_por_dia_tem_sempre_sete_dias() -> None:
    por_dia = resumir_semana(DADOS, SEGUNDA, HOJE).por_dia

    assert por_dia["data"].tolist() == [date(2026, 11, dia) for dia in range(9, 16)]
    assert por_dia["gasto"].tolist() == [42.0, 0.0, 95.0, 0.0, 151.0, -15.0, 0.0]


def test_media_de_referencia_usa_so_o_trecho_com_historico() -> None:
    resumo = resumir_semana(DADOS, SEGUNDA, HOJE)

    # de 31/08 a 08/11 são 70 dias; gastos nesse trecho: 700 + 140 + 90 = 930
    assert resumo.dias_de_referencia == 70
    assert resumo.media_diaria_de_referencia == pytest.approx(930 / 70)


def test_categorias_comparam_a_semana_com_a_media_semanal() -> None:
    categorias = resumir_semana(DADOS, SEGUNDA, HOJE).por_categoria

    por_nome = {linha.categoria: linha for linha in categorias.itertuples(index=False)}
    # Supermercado: 131 na semana; base 790 em 70 dias = 79 por semana
    assert por_nome["Supermercado"].semana == 131.0
    assert por_nome["Supermercado"].media_semanal == pytest.approx(79.0)
    assert por_nome["Supermercado"].diferenca == pytest.approx(52.0)
    # Alimentação: 95 + 20 - 15 = 100, sem histórico
    assert (por_nome["Alimentação"].semana, por_nome["Alimentação"].media_semanal) == (100.0, 0.0)
    # Transporte: 42 na semana; base 140 em 70 dias = 14 por semana
    assert por_nome["Transporte"].diferenca == pytest.approx(28.0)
    assert PAGAMENTO not in por_nome and "Renda" not in por_nome
    # da maior diferença para a menor
    assert categorias["categoria"].tolist() == ["Alimentação", "Supermercado", "Transporte"]


def test_maiores_gastos_vem_do_maior_para_o_menor_sem_estornos() -> None:
    maiores = resumir_semana(DADOS, SEGUNDA, HOJE).maiores_gastos

    assert maiores["valor"].tolist() == [131.0, 95.0, 42.0, 20.0]
    assert maiores["descricao"].tolist() == ["MERCADO", "RESTAURANTE", "UBER", "RESTAURANTE"]
    assert maiores["data"].tolist()[0] == date(2026, 11, 13)


def test_descricoes_sem_regra_da_semana() -> None:
    sem_regra = resumir_semana(DADOS, SEGUNDA, HOJE).descricoes_sem_regra

    assert sem_regra.to_dict("records")[0] == {
        "descricao": "RESTAURANTE",
        "vezes": 2,
        "categoria_atual": "Alimentação",
    }
    assert "UBER" not in sem_regra["descricao"].tolist()
    assert "PAGAMENTO RECEBIDO" not in sem_regra["descricao"].tolist()


def test_semana_em_andamento_conta_so_os_dias_que_ja_passaram() -> None:
    resumo = resumir_semana(DADOS, date(2026, 11, 16), date(2026, 11, 18))

    assert resumo.dias_decorridos == 3
    assert resumo.gasto == 9.0
    assert resumo.gasto_da_semana_anterior == 273.0


def test_semana_sem_transacoes_e_planilha_vazia() -> None:
    vazia = resumir_semana(DADOS, date(2026, 9, 14), HOJE)
    sem_dados = resumir_semana(_transacoes(), SEGUNDA, HOJE)

    for resumo in (vazia, sem_dados):
        assert (resumo.gasto, resumo.renda, resumo.transacoes, resumo.sem_regra) == (0.0, 0.0, 0, 0)
        assert resumo.por_dia["gasto"].tolist() == [0.0] * 7
        assert resumo.maiores_gastos.empty
    assert (sem_dados.dias_de_referencia, sem_dados.media_diaria_de_referencia) == (0, 0.0)
    assert sem_dados.por_categoria.empty


def test_formatos_de_periodo_e_dia_da_semana() -> None:
    assert periodo(date(2026, 11, 9), date(2026, 11, 15)) == "9 a 15 de novembro"
    assert periodo(date(2026, 11, 30), date(2026, 12, 6)) == "30 de novembro a 6 de dezembro"
    assert periodo(date(2026, 12, 28), date(2027, 1, 3)) == "28 de dezembro a 3 de janeiro"
    assert [dia_da_semana(date(2026, 11, dia)) for dia in (9, 14, 15)] == ["seg", "sáb", "dom"]
