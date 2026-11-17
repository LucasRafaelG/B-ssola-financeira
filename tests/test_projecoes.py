"""Testes dos cálculos de resumo e projeção, só com dados fictícios."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from bussola.limpeza import CARTAO_DE_CREDITO, COLUNAS_PLANILHA, CONTA_CORRENTE
from bussola.planilha import (
    ABA_PROJECAO,
    ABA_REGRAS,
    ABA_RESUMO_MENSAL,
    ABA_CONTAS_FIXAS,
    ABA_TRANSACOES,
    COLUNA_REFERENCIA,
    COLUNAS_CONTAS_FIXAS,
    COLUNAS_METAS,
    ArmazenamentoMemoria,
    Celula,
    ErroPlanilha,
    Formula,
    LinhaDerivada,
    ler_contas_fixas,
    ler_transacoes,
    reescrever_derivada,
)
from bussola.pluggy import Fatura
from bussola.projecoes import (
    CABECALHO_PROJECAO,
    CABECALHO_RESUMO,
    NAO_E_RENDA,
    com_gasto_e_renda,
    montar_periodo,
    montar_projecao,
    montar_resumo_mensal,
)

HOJE = date(2026, 11, 13)
PAGAMENTO = "Pagamento de cartão de crédito"

# (data, descrição, valor, conta, categoria, parcela, total de parcelas)
Linha = tuple[str, str, float, str, str, int | None, int | None]


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
            "categorizado_por": "pluggy",
            "parcela": pd.array([linha[5] for linha in linhas], dtype="Int64"),
            "total_parcelas": pd.array([linha[6] for linha in linhas], dtype="Int64"),
            "importado_em": pd.Timestamp("2026-11-13 10:00"),
        }
    )[COLUNAS_PLANILHA]


def _contas_fixas(*linhas: tuple[str, Celula, Celula, Celula, str]) -> pd.DataFrame:
    """Cada linha: nome, valor estimado, dia de vencimento, parcelas restantes, referência."""
    planilha = ArmazenamentoMemoria(
        {
            ABA_CONTAS_FIXAS: [
                [*COLUNAS_CONTAS_FIXAS, COLUNA_REFERENCIA],
                *(
                    [nome, valor, dia, "Assinaturas", "Essencial", restantes, referencia]
                    for nome, valor, dia, restantes, referencia in linhas
                ),
            ]
        }
    )
    return ler_contas_fixas(planilha)


def _metas(*linhas: tuple[str, Celula]) -> pd.DataFrame:
    return pd.DataFrame([[meta, valor, "", ""] for meta, valor in linhas], columns=COLUNAS_METAS)


SEM_CONTAS_FIXAS = _contas_fixas()
META_DE_200 = _metas(("Guardar no fim do mês", 200))

# Histórico desde 01/08: a base da média são os 92 dias de agosto a outubro.
HISTORICO = _transacoes(
    ("2026-08-01", "CLIENTE A", 3000.0, CONTA_CORRENTE, "Renda", None, None),
    ("2026-09-10", "CLIENTE B", 3000.0, CONTA_CORRENTE, "Renda", None, None),
    ("2026-10-10", "CLIENTE A", 3000.0, CONTA_CORRENTE, "Renda", None, None),
    ("2026-09-15", "MERCADO", -460.0, CONTA_CORRENTE, "Supermercado", None, None),
    ("2026-10-15", "MERCADO", -460.0, CARTAO_DE_CREDITO, "Supermercado", None, None),
    ("2026-11-05", "MERCADO", -100.0, CARTAO_DE_CREDITO, "Supermercado", None, None),
    ("2026-11-06", "CLIENTE B", 500.0, CONTA_CORRENTE, "Renda", None, None),
)


def _linha(linhas: list[LinhaDerivada], secao: str, item: str) -> LinhaDerivada:
    achadas = [linha for linha in linhas if linha[0] == secao and linha[1] == item]
    assert len(achadas) == 1, (secao, item, len(achadas))
    return achadas[0]


def _itens(linhas: list[LinhaDerivada], secao: str) -> list[Celula | Formula]:
    return [linha[1] for linha in linhas if linha[0] == secao]


def test_gasto_e_renda_de_cada_tipo_de_transacao() -> None:
    dados = com_gasto_e_renda(
        _transacoes(
            ("2026-11-01", "MERCADO", -100.0, CONTA_CORRENTE, "Supermercado", None, None),
            ("2026-11-02", "LOJA", -80.0, CARTAO_DE_CREDITO, "Compras", None, None),
            ("2026-11-03", "ESTORNO LOJA", 30.0, CARTAO_DE_CREDITO, "Compras", None, None),
            ("2026-11-04", "CLIENTE", 900.0, CONTA_CORRENTE, "Renda", None, None),
            ("2026-11-05", "AMIGO DEVOLVEU", 50.0, CONTA_CORRENTE, NAO_E_RENDA, None, None),
            ("2026-11-06", "PAGAMENTO DE FATURA", -500.0, CONTA_CORRENTE, PAGAMENTO, None, None),
            ("2026-11-06", "PAGAMENTO RECEBIDO", 500.0, CARTAO_DE_CREDITO, PAGAMENTO, None, None),
            ("2026-11-07", "CAIXINHA", -200.0, CONTA_CORRENTE, "Investimentos", None, None),
        )
    )

    assert dados["gasto"].tolist() == [100.0, 80.0, -30.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert dados["renda"].tolist() == [0.0, 0.0, 0.0, 900.0, 0.0, 0.0, 0.0, 0.0]
    assert dados["interno"].tolist() == [False] * 5 + [True] * 3


def test_periodo_usa_os_tres_meses_anteriores_como_base() -> None:
    periodo = montar_periodo(HOJE, None)

    assert (periodo.dias_no_mes, periodo.dias_restantes) == (30, 17)
    assert periodo.inicio_da_base == pd.Timestamp("2026-08-01")
    assert periodo.fim_da_base == pd.Timestamp("2026-10-31")
    assert periodo.dias_de_base == 92


def test_periodo_encolhe_a_base_quando_o_historico_e_curto() -> None:
    assert montar_periodo(HOJE, pd.Timestamp("2026-08-15")).dias_de_base == 78
    assert montar_periodo(HOJE, pd.Timestamp("2026-11-03")).dias_de_base == 0


def test_cabecalhos_das_abas() -> None:
    assert montar_resumo_mensal(HISTORICO)[0] == CABECALHO_RESUMO
    assert montar_projecao(HISTORICO, SEM_CONTAS_FIXAS, META_DE_200, HOJE)[0] == CABECALHO_PROJECAO


def test_gasto_projetado_soma_a_media_diaria_pelos_dias_que_faltam() -> None:
    projecao = montar_projecao(HISTORICO, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    # base: 920 em 92 dias = 10 por dia; faltam 17 dias; 100 até hoje + 170 = 270
    assert _linha(projecao, "Resumo", "Gasto total")[2:4] == [100.0, 270.0]
    assert _linha(projecao, "Gasto por categoria", "Supermercado")[2:4] == [100.0, 270.0]
    # no cartão: 460 em 92 dias = 5 por dia; 100 + 85 = 185
    assert _linha(projecao, "Resumo", "Fatura do cartão")[2:4] == [100.0, 185.0]


# Fecha todo dia 5: a fatura aberta em 13/11 vai de 05/11 a 04/12.
FATURA_DE_NOVEMBRO = Fatura(fechamento=date(2026, 11, 5), vencimento=date(2026, 11, 12))

COMPRAS_NO_CARTAO = _transacoes(
    ("2026-08-01", "CLIENTE", 3000.0, CONTA_CORRENTE, "Renda", None, None),
    # base (ago a out, 92 dias): 184 à vista + 100 em parcelas
    ("2026-09-20", "LOJA", -184.0, CARTAO_DE_CREDITO, "Compras", None, None),
    ("2026-10-05", "CURSO 1/3", -100.0, CARTAO_DE_CREDITO, "Educação", 1, 3),
    # antes do fechamento de 05/11: ficou na fatura anterior
    ("2026-11-04", "PADARIA", -30.0, CARTAO_DE_CREDITO, "Padaria", None, None),
    # do dia do fechamento em diante: fatura aberta
    ("2026-11-05", "CURSO 2/3", -100.0, CARTAO_DE_CREDITO, "Educação", 2, 3),
    ("2026-11-10", "MERCADO", -40.0, CARTAO_DE_CREDITO, "Supermercado", None, None),
    ("2026-11-11", "ESTORNO LOJA", 15.0, CARTAO_DE_CREDITO, "Compras", None, None),
    ("2026-11-06", "PAGAMENTO RECEBIDO", 500.0, CARTAO_DE_CREDITO, PAGAMENTO, None, None),
    ("2026-11-12", "MERCADO", -70.0, CONTA_CORRENTE, "Supermercado", None, None),
)


def test_fatura_aberta_vai_do_ultimo_fechamento_ate_hoje() -> None:
    projecao = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, HOJE, FATURA_DE_NOVEMBRO)

    fatura = _linha(projecao, "Resumo", "Fatura do cartão")
    # aberta: 100 + 40 - 15 = 125 (a padaria de 04/11, o pagamento e a conta corrente ficam fora)
    # à vista na base: 184 em 92 dias = 2 por dia; de 14/11 a 04/12 são 21 dias: 125 + 42 = 167
    assert fatura[2:4] == [125.0, 167.0]
    assert "Compras de 05/11/2026 até hoje" in str(fatura[4])
    assert "Fecha em 05/12/2026" in str(fatura[4])
    assert "vence por volta de 12/12/2026" in str(fatura[4])
    assert "21 dias" in str(fatura[4])


def test_fatura_avanca_o_ciclo_quando_a_lista_de_faturas_esta_atrasada() -> None:
    fatura_antiga = Fatura(fechamento=date(2026, 9, 5), vencimento=date(2026, 9, 14))

    projecao = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, HOJE, fatura_antiga)

    fatura = _linha(projecao, "Resumo", "Fatura do cartão")
    assert fatura[2:4] == [125.0, 167.0]
    assert "Fecha em 05/12/2026" in str(fatura[4])


def test_no_dia_do_fechamento_comeca_uma_fatura_nova() -> None:
    na_vespera = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, date(2026, 12, 4), FATURA_DE_NOVEMBRO)
    no_dia = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, date(2026, 12, 5), FATURA_DE_NOVEMBRO)

    vespera = _linha(na_vespera, "Resumo", "Fatura do cartão")
    assert vespera[2] == 125.0
    assert vespera[2] == vespera[3]  # não falta nenhum dia para projetar
    assert "Fecha em 05/12/2026" in str(vespera[4])
    novo = _linha(no_dia, "Resumo", "Fatura do cartão")
    assert novo[2] == 0.0
    assert "Compras de 05/12/2026 até hoje" in str(novo[4])
    assert "Fecha em 05/01/2027" in str(novo[4])


def test_sem_datas_da_fatura_vale_o_mes_do_calendario() -> None:
    projecao = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, HOJE, None)

    fatura = _linha(projecao, "Resumo", "Fatura do cartão")
    # mês de novembro até hoje: 30 + 100 + 40 - 15 = 155; base do cartão: 284 em 92 dias, 17 dias restantes
    assert fatura[2:4] == [155.0, round(155 + 284 / 92 * 17, 2)]
    assert "mês do calendário" in str(fatura[4])


def test_fatura_nao_muda_o_gasto_total_nem_a_sobra() -> None:
    com = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, HOJE, FATURA_DE_NOVEMBRO)
    sem = montar_projecao(COMPRAS_NO_CARTAO, SEM_CONTAS_FIXAS, META_DE_200, HOJE, None)

    for item in ("Gasto total", "Entradas (renda)", "Sobra prevista"):
        assert _linha(com, "Resumo", item) == _linha(sem, "Resumo", item)


def test_renda_estimada_e_o_maior_entre_o_que_entrou_e_a_media_mensal() -> None:
    projecao = montar_projecao(HISTORICO, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    # base: 9000 em 92 dias, levado para um mês de 30 dias
    media_mensal = round(9000 / 92 * 30, 2)
    assert _linha(projecao, "Resumo", "Entradas (renda)")[2:4] == [500.0, media_mensal]
    assert _linha(projecao, "Resumo", "Sobra prevista")[2:4] == [230.0, round(media_mensal - 270, 2)]


def test_renda_que_ja_passou_da_media_vale_como_estimativa() -> None:
    transacoes = pd.concat(
        [HISTORICO, _transacoes(("2026-11-10", "CLIENTE C", 9000.0, CONTA_CORRENTE, "Renda", None, None))],
        ignore_index=True,
    )

    projecao = montar_projecao(transacoes, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    assert _linha(projecao, "Resumo", "Entradas (renda)")[2:4] == [9500.0, 9500.0]


def test_meta_e_comparada_nos_dois_cenarios() -> None:
    projecao = montar_projecao(HISTORICO, SEM_CONTAS_FIXAS, _metas(("Guardar", 250)), HOJE)

    # sobra segura 230 (abaixo de 250); sobra provável bem acima
    assert _linha(projecao, "Resumo", "Meta de economia")[2:4] == [250.0, 250.0]
    assert _linha(projecao, "Resumo", "Meta no caminho?")[2:4] == ["não", "sim"]


def test_sem_meta_com_valor_a_projecao_avisa() -> None:
    projecao = montar_projecao(HISTORICO, SEM_CONTAS_FIXAS, _metas(("Só texto", "")), HOJE)

    assert "Nenhuma meta" in str(_linha(projecao, "Resumo", "Meta de economia")[4])
    assert "Meta no caminho?" not in _itens(projecao, "Resumo")


def test_sem_historico_o_projetado_e_igual_ao_ate_hoje() -> None:
    transacoes = _transacoes(("2026-11-05", "MERCADO", -100.0, CONTA_CORRENTE, "Supermercado", None, None))

    projecao = montar_projecao(transacoes, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    assert _linha(projecao, "Resumo", "Gasto total")[2:4] == [100.0, 100.0]
    assert "Ainda não há histórico" in str(_linha(projecao, "Referência", "Método")[4])


def test_planilha_sem_transacoes_gera_projecao_zerada() -> None:
    projecao = montar_projecao(_transacoes(), SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    assert _linha(projecao, "Resumo", "Gasto total")[2:4] == [0.0, 0.0]
    assert montar_resumo_mensal(_transacoes()) == [CABECALHO_RESUMO]


def test_pagamento_da_fatura_nao_conta_como_gasto_nem_como_renda() -> None:
    transacoes = pd.concat(
        [
            HISTORICO,
            _transacoes(
                ("2026-11-08", "PAGAMENTO DE FATURA", -460.0, CONTA_CORRENTE, PAGAMENTO, None, None),
                ("2026-11-08", "PAGAMENTO RECEBIDO", 460.0, CARTAO_DE_CREDITO, PAGAMENTO, None, None),
            ),
        ],
        ignore_index=True,
    )

    projecao = montar_projecao(transacoes, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    assert _linha(projecao, "Resumo", "Gasto total")[2:4] == [100.0, 270.0]
    assert _linha(projecao, "Resumo", "Entradas (renda)")[2] == 500.0
    assert _linha(projecao, "Movimento interno", PAGAMENTO)[2] == 460.0
    assert PAGAMENTO not in _itens(projecao, "Gasto por categoria")


def test_parcelas_futuras_usam_a_parcela_mais_recente_de_cada_compra() -> None:
    transacoes = _transacoes(
        ("2026-10-10", "LOJA X 2/12", -50.0, CARTAO_DE_CREDITO, "Compras", 2, 12),
        ("2026-11-10", "LOJA X 3/12", -50.0, CARTAO_DE_CREDITO, "Compras", 3, 12),
        ("2026-11-02", "JOGO 4/4", -119.9, CARTAO_DE_CREDITO, "Jogos", 4, 4),
        ("2026-06-02", "CURSO 1/3", -90.0, CARTAO_DE_CREDITO, "Educação", 1, 3),
        ("2026-11-03", "PADARIA", -9.0, CARTAO_DE_CREDITO, "Padaria", None, None),
    )

    projecao = montar_projecao(transacoes, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    # JOGO já terminou; as parcelas que faltavam do CURSO caíam em julho e agosto, já passados
    assert _itens(projecao, "Parcela futura") == ["LOJA X"]
    loja = _linha(projecao, "Parcela futura", "LOJA X")
    assert loja[2:4] == [50.0, 9]
    assert "3 de 12" in str(loja[4])
    assert "Termina em 08/2027" in str(loja[4])
    assert _itens(projecao, "Parcelas por mês") == [
        "2026-12",
        "2027-01",
        "2027-02",
        "2027-03",
        "2027-04",
        "2027-05",
        "2027-06",
        "2027-07",
        "2027-08",
    ]
    assert _linha(projecao, "Parcelas por mês", "2026-12")[2] == 50.0


def test_parcelas_de_compras_diferentes_somam_no_mesmo_mes() -> None:
    transacoes = _transacoes(
        ("2026-11-10", "LOJA X 3/12", -50.0, CARTAO_DE_CREDITO, "Compras", 3, 12),
        ("2026-11-11", "LOJA Y 1/2", -20.0, CARTAO_DE_CREDITO, "Compras", 1, 2),
    )

    projecao = montar_projecao(transacoes, SEM_CONTAS_FIXAS, META_DE_200, HOJE)

    assert _linha(projecao, "Parcelas por mês", "2026-12")[2] == 70.0
    assert _linha(projecao, "Parcelas por mês", "2027-01")[2] == 50.0


def test_contas_fixas_sem_referencia_usam_o_numero_digitado() -> None:
    contas = _contas_fixas(
        ("Assinatura em 12x", 29.9, "", 6, ""),
        ("Parcela de jogo", 119.9, "", 1, ""),
        ("Internet", 99.9, 10, "", ""),
    )

    projecao = montar_projecao(HISTORICO, contas, META_DE_200, HOJE)

    assinatura = _linha(projecao, "Conta fixa", "Assinatura em 12x")
    assert assinatura[2:4] == [29.9, 6]
    assert "Termina em 05/2027" in str(assinatura[4])
    assert "Preencha a coluna referencia" in str(assinatura[4])
    assert "Termina em 12/2026" in str(_linha(projecao, "Conta fixa", "Parcela de jogo")[4])
    internet = _linha(projecao, "Conta fixa", "Internet")
    assert internet[3] == ""
    assert "Recorrente" in str(internet[4])
    assert "dia 10" in str(internet[4])


def test_contas_fixas_com_referencia_descontam_os_meses_que_passaram() -> None:
    contas = _contas_fixas(("Assinatura em 12x", 29.9, "", 6, "11/2026"))

    em_novembro = montar_projecao(HISTORICO, contas, META_DE_200, date(2026, 11, 13))
    em_fevereiro = montar_projecao(HISTORICO, contas, META_DE_200, date(2027, 2, 3))

    assert _linha(em_novembro, "Conta fixa", "Assinatura em 12x")[3] == 6
    depois = _linha(em_fevereiro, "Conta fixa", "Assinatura em 12x")
    assert depois[3] == 3
    # o mês de término não muda com o passar do tempo
    assert "Termina em 05/2027" in str(_linha(em_novembro, "Conta fixa", "Assinatura em 12x")[4])
    assert "Termina em 05/2027" in str(depois[4])
    assert "Eram 6 parcelas em 11/2026" in str(depois[4])


def test_conta_fixa_que_ja_terminou_avisa_e_fica_com_zero() -> None:
    contas = _contas_fixas(("Parcela de jogo", 119.9, "", 1, "11/2026"))

    for hoje in (date(2026, 12, 5), date(2027, 6, 5)):
        linha = _linha(montar_projecao(HISTORICO, contas, META_DE_200, hoje), "Conta fixa", "Parcela de jogo")
        assert linha[3] == 0
        assert "Terminou em 12/2026" in str(linha[4])


def test_conta_fixa_aponta_a_mesma_compra_detectada_no_cartao() -> None:
    transacoes = _transacoes(
        ("2026-11-10", "LOJA X 3/12", -50.0, CARTAO_DE_CREDITO, "Compras", 3, 12),
    )
    contas = _contas_fixas(
        ("Loja X em 12x", 50.0, "", 9, "11/2026"),
        ("Outra conta", 77.0, "", 9, "11/2026"),
    )

    projecao = montar_projecao(transacoes, contas, META_DE_200, HOJE)

    assert 'mesma compra de "LOJA X"' in str(_linha(projecao, "Conta fixa", "Loja X em 12x")[4])
    assert "mesma compra" not in str(_linha(projecao, "Conta fixa", "Outra conta")[4])


def test_referencia_aceita_texto_ou_data_da_planilha() -> None:
    dia_15_de_novembro = (date(2026, 11, 15) - date(1899, 12, 30)).days
    contas = _contas_fixas(
        ("texto", 1.0, "", 1, "11/2026"),
        ("texto curto", 1.0, "", 1, " 3/2027 "),
        ("data", 1.0, "", 1, ""),
    )
    planilha = ArmazenamentoMemoria(
        {ABA_CONTAS_FIXAS: [[*COLUNAS_CONTAS_FIXAS, COLUNA_REFERENCIA], ["data", 1.0, "", "", "", 1, dia_15_de_novembro]]}
    )

    assert contas[COLUNA_REFERENCIA].tolist() == [pd.Period("2026-11"), pd.Period("2027-03"), None]
    assert ler_contas_fixas(planilha)[COLUNA_REFERENCIA].tolist() == [pd.Period("2026-11")]


@pytest.mark.parametrize("valor", ["novembro", "13/2026", "11/26", "2026-11"])
def test_referencia_em_formato_errado_para_com_mensagem_clara(valor: str) -> None:
    with pytest.raises(ErroPlanilha, match="mm/aaaa"):
        _contas_fixas(("conta", 1.0, "", 1, valor))


def test_aba_de_contas_fixas_funciona_sem_a_coluna_de_referencia() -> None:
    planilha = ArmazenamentoMemoria(
        {ABA_CONTAS_FIXAS: [list(COLUNAS_CONTAS_FIXAS), ["Internet", 99.9, 10, "Casa", "Essencial"]]}
    )

    contas = ler_contas_fixas(planilha)

    assert list(contas.columns) == [*COLUNAS_CONTAS_FIXAS, COLUNA_REFERENCIA]
    assert contas.iloc[0].tolist() == ["Internet", 99.9, 10, "Casa", "Essencial", "", None]


def test_cabecalho_de_contas_fixas_com_coluna_estranha_e_recusado() -> None:
    planilha = ArmazenamentoMemoria({ABA_CONTAS_FIXAS: [[*COLUNAS_CONTAS_FIXAS, "outra_coluna"]]})

    with pytest.raises(ErroPlanilha, match="cabeçalho"):
        ler_contas_fixas(planilha)


def test_resumo_tem_uma_linha_por_mes_e_categoria_do_mais_recente_para_o_mais_antigo() -> None:
    resumo = montar_resumo_mensal(HISTORICO)

    assert [linha[:2] for linha in resumo[1:]] == [
        ["2026-11", "Supermercado"],
        ["2026-10", "Supermercado"],
        ["2026-09", "Supermercado"],
    ]


def test_resumo_usa_formulas_que_apontam_para_a_aba_de_transacoes() -> None:
    linha = montar_resumo_mensal(HISTORICO)[1]  # novembro, linha 2 da planilha
    total, media, diferenca = linha[2], linha[3], linha[4]

    assert isinstance(total, Formula) and isinstance(media, Formula)
    # categoria na coluna G, data na B, valor na D, tipo na E, conta na F
    assert total.texto == (
        "=-SUMIFS(transacoes!$D:$D;transacoes!$G:$G;$B2;"
        'transacoes!$B:$B;">="&DATE(2026;11;1);transacoes!$B:$B;"<"&DATE(2026;12;1);'
        'transacoes!$E:$E;"DEBITO")'
        "-SUMIFS(transacoes!$D:$D;transacoes!$G:$G;$B2;"
        'transacoes!$B:$B;">="&DATE(2026;11;1);transacoes!$B:$B;"<"&DATE(2026;12;1);'
        'transacoes!$E:$E;"CREDITO";transacoes!$F:$F;"Cartão de crédito")'
    )
    assert media.texto.startswith("=(-SUMIFS(") and media.texto.endswith(")/3")
    assert '">="&DATE(2026;8;1)' in media.texto and '"<"&DATE(2026;11;1)' in media.texto
    assert diferenca == Formula("=C2-D2")


def test_resumo_avisa_quando_a_media_usa_meses_incompletos_e_marca_movimento_interno() -> None:
    transacoes = _transacoes(
        ("2026-08-15", "MERCADO", -10.0, CONTA_CORRENTE, "Supermercado", None, None),
        ("2026-12-02", "MERCADO", -10.0, CONTA_CORRENTE, "Supermercado", None, None),
        ("2026-12-03", "PAGAMENTO DE FATURA", -10.0, CONTA_CORRENTE, PAGAMENTO, None, None),
    )

    resumo = {(str(linha[0]), str(linha[1])): str(linha[5]) for linha in montar_resumo_mensal(transacoes)[1:]}

    # dezembro olha setembro a novembro, que estão inteiros dentro do histórico
    assert resumo[("2026-12", "Supermercado")] == ""
    assert "Movimento interno" in resumo[("2026-12", PAGAMENTO)]
    # agosto olharia maio a julho, antes do começo do histórico
    assert "15/08/2026" in resumo[("2026-08", "Supermercado")]


def test_so_abas_calculadas_podem_ser_reescritas() -> None:
    planilha = ArmazenamentoMemoria({ABA_TRANSACOES: [list(COLUNAS_PLANILHA)], ABA_REGRAS: [["x"]]})

    for aba in (ABA_TRANSACOES, ABA_REGRAS, "metas", "contas_fixas", "outra"):
        with pytest.raises(ErroPlanilha, match="não é uma aba calculada"):
            reescrever_derivada(planilha, aba, [["apagaria tudo"]])

    reescrever_derivada(planilha, ABA_RESUMO_MENSAL, [["a", Formula("=1+1")]])
    reescrever_derivada(planilha, ABA_PROJECAO, [["b"]])
    reescrever_derivada(planilha, ABA_PROJECAO, [["c"]])

    assert planilha.derivadas == {ABA_RESUMO_MENSAL: [["a", Formula("=1+1")]], ABA_PROJECAO: [["c"]]}
    assert planilha.abas == {ABA_TRANSACOES: [list(COLUNAS_PLANILHA)], ABA_REGRAS: [["x"]]}


def _planilha_com(*linhas: list[Celula]) -> ArmazenamentoMemoria:
    return ArmazenamentoMemoria({ABA_TRANSACOES: [list(COLUNAS_PLANILHA), *linhas]})


def test_ler_transacoes_converte_data_valor_e_parcelas() -> None:
    dia = (date(2026, 11, 10) - date(1899, 12, 30)).days
    planilha = _planilha_com(
        ["a", dia, "LOJA 2/3", -50, "DEBITO", CARTAO_DE_CREDITO, "Compras", "", "pluggy", 2, 3, dia + 0.5],
        ["b", dia, "MERCADO", -10.5, "DEBITO", CONTA_CORRENTE, "Mercado", "", "pluggy"],
    )

    transacoes = ler_transacoes(planilha)

    assert transacoes["data"].tolist() == [pd.Timestamp("2026-11-10")] * 2
    assert transacoes["valor"].tolist() == [-50.0, -10.5]
    assert transacoes["valor"].dtype == "float64"
    assert transacoes["parcela"].dtype == "Int64"
    assert transacoes["parcela"].tolist()[0] == 2
    assert pd.isna(transacoes["parcela"].tolist()[1])
    assert pd.isna(transacoes["total_parcelas"].tolist()[1])


@pytest.mark.parametrize("coluna", ["data", "valor", "parcela"])
def test_ler_transacoes_para_quando_uma_celula_numerica_tem_texto(coluna: str) -> None:
    linha: list[Celula] = ["a", 46336, "LOJA", -50, "DEBITO", CONTA_CORRENTE, "Compras", "", "pluggy", 1, 2, 46336.5]
    linha[COLUNAS_PLANILHA.index(coluna)] = "texto digitado à mão"

    with pytest.raises(ErroPlanilha, match="não são números"):
        ler_transacoes(_planilha_com(linha))
