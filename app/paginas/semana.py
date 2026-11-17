"""Tela "Semana": o resumo de uma semana, de segunda a domingo."""

from __future__ import annotations

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

import dados
from bussola.formatos import dia_da_semana, periodo, reais
from bussola.semana import SEMANAS_DE_BASE, resumir_semana, semanas_disponiveis

COR_DO_GASTO = "#1F5FBF"

transacoes = dados.transacoes()
hoje = dados.hoje()
semanas = semanas_disponiveis(transacoes, hoje)

inicio = st.selectbox(
    "Semana",
    semanas,
    format_func=lambda segunda: periodo(segunda, segunda + timedelta(days=6))
    + (" (esta semana)" if segunda == semanas[0] else ""),
)
resumo = resumir_semana(transacoes, inicio, hoje)
em_andamento = resumo.dias_decorridos < 7

st.title(f"Semana de {periodo(resumo.inicio, resumo.fim)}")
if em_andamento:
    st.caption(f"Semana em andamento: {resumo.dias_decorridos} de 7 dias.")

diferenca = resumo.gasto - resumo.gasto_da_semana_anterior
media_por_dia = resumo.gasto / resumo.dias_decorridos

colunas = st.columns(4)
with colunas[0]:
    st.metric(
        "Gasto na semana",
        reais(resumo.gasto),
        border=True,
        help="Tudo o que saiu na semana, na conta e no cartão, fora os movimentos internos "
        "(pagar a fatura, transferir entre contas suas, investir).",
    )
    if abs(diferenca) < 0.005:
        st.caption("Igual à semana anterior.")
    else:
        st.caption(
            f"{reais(abs(diferenca))} a {'mais' if diferenca > 0 else 'menos'} que a semana anterior"
            + (" inteira." if em_andamento else ".")
        )
with colunas[1]:
    st.metric("Entradas na semana", reais(resumo.renda), border=True)
    st.caption(
        "Nenhum pagamento recebido."
        if resumo.entradas == 0
        else f"{resumo.entradas} pagamento{'s' if resumo.entradas > 1 else ''} "
        f"recebido{'s' if resumo.entradas > 1 else ''}."
    )
with colunas[2]:
    st.metric(
        "Média por dia",
        reais(media_por_dia),
        border=True,
        help=f"Gasto da semana dividido pelos dias já passados. A comparação usa as "
        f"{SEMANAS_DE_BASE} semanas anteriores, ou o que houver de histórico.",
    )
    st.caption(
        f"Sua média recente: {reais(resumo.media_diaria_de_referencia)} por dia."
        if resumo.dias_de_referencia
        else "Ainda sem histórico para comparar."
    )
with colunas[3]:
    st.metric("Transações", str(resumo.transacoes), border=True)
    st.caption(
        "Todas cobertas por regra."
        if resumo.sem_regra == 0
        else f"{resumo.sem_regra} ainda sem regra."
    )

esquerda, direita = st.columns(2)

with esquerda, st.container(border=True):
    st.subheader("Gasto por dia")
    por_dia = resumo.por_dia.assign(
        dia=[f"{dia_da_semana(data)} {data.day}" for data in resumo.por_dia["data"]],
        texto=resumo.por_dia["gasto"].map(reais),
    )
    grafico = (
        alt.Chart(por_dia)
        .mark_bar(color=COR_DO_GASTO, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("dia:N", sort=list(por_dia["dia"]), title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("gasto:Q", title="R$"),
            tooltip=[alt.Tooltip("dia:N", title="Dia"), alt.Tooltip("texto:N", title="Gasto")],
        )
        .properties(height=280)
    )
    st.altair_chart(grafico, width="stretch")

with direita, st.container(border=True):
    st.subheader("Categorias frente à sua média semanal")
    if resumo.por_categoria.empty:
        st.caption("Nenhum gasto nesta semana nem histórico para comparar.")
    else:
        categorias = resumo.por_categoria
        st.dataframe(
            pd.DataFrame(
                {
                    "Categoria": categorias["categoria"],
                    "Semana": categorias["semana"].map(reais),
                    "Média": categorias["media_semanal"].map(reais),
                    "Diferença": [
                        "igual"
                        if abs(valor) < 0.005
                        else f"{reais(abs(valor))} {'acima' if valor > 0 else 'abaixo'}"
                        for valor in categorias["diferenca"]
                    ],
                }
            ),
            hide_index=True,
            width="stretch",
        )
        if em_andamento:
            st.caption("A semana ainda não acabou; a média é de semanas inteiras.")

esquerda, direita = st.columns(2)

with esquerda, st.container(border=True):
    st.subheader("Maiores gastos da semana")
    maiores = resumo.maiores_gastos
    if maiores.empty:
        st.caption("Nenhum gasto nesta semana.")
    else:
        st.dataframe(
            pd.DataFrame(
                {
                    "Dia": [f"{dia_da_semana(data)} {data.day}" for data in maiores["data"]],
                    "Descrição": maiores["descricao"],
                    "Categoria": maiores["categoria"],
                    "Valor": maiores["valor"].map(reais),
                }
            ),
            hide_index=True,
            width="stretch",
        )

with direita, st.container(border=True):
    st.subheader("Ainda sem regra")
    sem_regra = resumo.descricoes_sem_regra
    if sem_regra.empty:
        st.caption("Todas as transações desta semana são cobertas por uma regra.")
    else:
        st.caption(
            "Descrições desta semana que nenhuma regra cobre. Uma regra define a categoria "
            "e a prioridade daqui para frente."
        )
        st.page_link("paginas/regras.py", label="Criar regra na tela Regras")
        st.dataframe(
            pd.DataFrame(
                {
                    "Descrição": sem_regra["descricao"],
                    "Vezes": sem_regra["vezes"],
                    "Categoria atual": sem_regra["categoria_atual"],
                }
            ),
            hide_index=True,
            width="stretch",
        )
