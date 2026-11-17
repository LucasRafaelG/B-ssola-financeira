"""Tela "Mês": a projeção do mês corrente, lida da aba `projecao`."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import dados
from bussola.formatos import mes_por_extenso, reais
from bussola.projecoes import (
    ITEM_FATURA,
    ITEM_GASTO,
    ITEM_MES,
    ITEM_META,
    ITEM_META_NO_CAMINHO,
    ITEM_METODO,
    ITEM_RENDA,
    ITEM_SOBRA,
    SECAO_CATEGORIAS,
    SECAO_CONTAS_FIXAS,
    SECAO_INTERNOS,
    SECAO_PARCELAS,
    SECAO_PARCELAS_POR_MES,
    SECAO_REFERENCIA,
    SECAO_RESUMO,
    LinhaDeProjecao,
)

COR_ATE_HOJE = "#1F5FBF"
COR_PROJETADO = "#C5D4EC"

projecao = dados.projecao()


def _resumo(item: str) -> LinhaDeProjecao | None:
    return projecao.item(SECAO_RESUMO, item)


def _numero(valor: object) -> float | None:
    return float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None


mes = projecao.item(SECAO_REFERENCIA, ITEM_MES)
st.title(mes_por_extenso(mes.ate_hoje) if mes else "Mês")
if mes:
    st.caption(mes.observacao)

gasto, renda, sobra, meta = _resumo(ITEM_GASTO), _resumo(ITEM_RENDA), _resumo(ITEM_SOBRA), _resumo(ITEM_META)

colunas = st.columns(4)
with colunas[0]:
    st.metric(
        "Gasto até hoje",
        reais(gasto.ate_hoje) if gasto else "–",
        border=True,
        help="Tudo o que saiu neste mês, na conta e no cartão. Pagar a fatura, transferir "
        "entre contas suas e investir não contam: o dinheiro só mudou de lugar.",
    )
    st.caption(f"Projetado no mês: {reais(gasto.projetado) if gasto else '–'}")
with colunas[1]:
    st.metric(
        "Entradas até hoje",
        reais(renda.ate_hoje) if renda else "–",
        border=True,
        help="O que já entrou na conta corrente neste mês. A estimativa do mês é o maior "
        "valor entre isso e a sua média dos últimos 3 meses.",
    )
    st.caption(f"Estimada no mês: {reais(renda.projetado) if renda else '–'}")
with colunas[2]:
    st.metric(
        "Sobra provável",
        reais(sobra.projetado) if sobra else "–",
        border=True,
        help="Renda estimada do mês menos o gasto projetado. É o que deve sobrar se a "
        "renda vier como de costume.",
    )
    st.caption("Com a renda estimada.")
with colunas[3]:
    st.metric(
        "Sobra segura",
        reais(sobra.ate_hoje) if sobra else "–",
        border=True,
        help="O que já entrou menos o gasto projetado do mês inteiro. Responde: e se não "
        "entrar mais nada? No começo do mês costuma ser negativa e sobe a cada pagamento.",
    )
    st.caption("Só com o que já entrou.")

valor_da_meta = _numero(meta.ate_hoje) if meta else None
if meta is not None and valor_da_meta is not None and sobra is not None:
    with st.container(border=True):
        st.subheader(f"Meta: {meta.observacao} ({reais(valor_da_meta)})")
        no_caminho = _resumo(ITEM_META_NO_CAMINHO)
        seguro = no_caminho is not None and no_caminho.ate_hoje == "sim"
        provavel = no_caminho is not None and no_caminho.projetado == "sim"
        if seguro:
            st.success("No caminho: o que já entrou cobre o gasto projetado e a meta.")
        elif provavel:
            st.info("No caminho, se a renda estimada entrar até o fim do mês.")
        else:
            st.warning("Fora do caminho: nem a renda estimada cobre o gasto projetado e a meta.")
        sobra_provavel = _numero(sobra.projetado) or 0.0
        alcance = min(max(sobra_provavel / valor_da_meta, 0.0), 1.0) if valor_da_meta > 0 else 1.0
        st.progress(
            alcance,
            text=f"Sobra provável de {reais(sobra_provavel)} frente à meta de {reais(valor_da_meta)}.",
        )
elif meta is not None:
    st.info(meta.observacao)

esquerda, direita = st.columns([3, 2])

with esquerda, st.container(border=True):
    st.subheader("Gasto por categoria")
    categorias = pd.DataFrame(
        [
            {"categoria": linha.item, "tipo": tipo, "valor": _numero(valor) or 0.0}
            for linha in projecao.da_secao(SECAO_CATEGORIAS)
            for tipo, valor in (("Projetado", linha.projetado), ("Até hoje", linha.ate_hoje))
        ]
    )
    if categorias.empty:
        st.caption("Ainda não há gastos neste mês nem histórico para projetar.")
    else:
        ordem = list(dict.fromkeys(categorias["categoria"]))  # a aba já vem da maior para a menor
        categorias["texto"] = categorias["valor"].map(reais)
        grafico = (
            alt.Chart(categorias)
            .mark_bar()
            .encode(
                y=alt.Y("categoria:N", sort=ordem, title=None),
                x=alt.X("valor:Q", title="R$", stack=None),
                color=alt.Color(
                    "tipo:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["Até hoje", "Projetado"], range=[COR_ATE_HOJE, COR_PROJETADO]
                    ),
                    legend=alt.Legend(orient="top"),
                ),
                order=alt.Order("tipo:N", sort="descending"),  # "Projetado" atrás, "Até hoje" na frente
                tooltip=[
                    alt.Tooltip("categoria:N", title="Categoria"),
                    alt.Tooltip("tipo:N", title="Valor"),
                    alt.Tooltip("texto:N", title="R$"),
                ],
            )
            .properties(height=max(38 * len(ordem), 160))
        )
        st.altair_chart(grafico, width="stretch")

with direita:
    fatura = _resumo(ITEM_FATURA)
    with st.container(border=True):
        st.subheader("Fatura do cartão")
        if fatura is None:
            st.caption("Sem dados da fatura.")
        else:
            aberta, fechada = st.columns(2)
            aberta.metric("Aberta até hoje", reais(fatura.ate_hoje))
            fechada.metric("Deve fechar em", reais(fatura.projetado))
            st.caption(fatura.observacao)

    parcelas = projecao.da_secao(SECAO_PARCELAS)
    with st.container(border=True):
        st.subheader("Parcelas que ainda vão cair")
        if not parcelas:
            st.caption("Nenhuma compra parcelada em aberto no cartão.")
        else:
            st.dataframe(
                pd.DataFrame(
                    {
                        "Compra": [linha.item for linha in parcelas],
                        "Parcela": [reais(linha.ate_hoje) for linha in parcelas],
                        "Faltam": [linha.projetado for linha in parcelas],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            por_mes = projecao.da_secao(SECAO_PARCELAS_POR_MES)
            if por_mes:
                proximo = por_mes[0]
                st.caption(
                    f"Em {mes_por_extenso(proximo.item).lower()} caem {reais(proximo.ate_hoje)} em parcelas."
                )

with st.expander("Contas fixas, movimentos internos e como a projeção é calculada"):
    metodo = projecao.item(SECAO_REFERENCIA, ITEM_METODO)
    if metodo:
        st.write(metodo.observacao)
    if renda:
        st.write(f"**Renda.** {renda.observacao}")
    if sobra:
        st.write(f"**Sobra.** {sobra.observacao}")

    contas_fixas = projecao.da_secao(SECAO_CONTAS_FIXAS)
    if contas_fixas:
        st.markdown("**Contas fixas**")
        st.dataframe(
            pd.DataFrame(
                {
                    "Conta": [linha.item for linha in contas_fixas],
                    "Valor": [reais(linha.ate_hoje) for linha in contas_fixas],
                    "Parcelas restantes": [linha.projetado for linha in contas_fixas],
                    "Situação": [linha.observacao for linha in contas_fixas],
                }
            ),
            hide_index=True,
            width="stretch",
        )

    internos = projecao.da_secao(SECAO_INTERNOS)
    if internos:
        st.markdown("**Movimentos internos do mês** (não contam como gasto nem como renda)")
        st.dataframe(
            pd.DataFrame(
                {
                    "Movimento": [linha.item for linha in internos],
                    "Saídas": [reais(linha.ate_hoje) for linha in internos],
                }
            ),
            hide_index=True,
            width="stretch",
        )
