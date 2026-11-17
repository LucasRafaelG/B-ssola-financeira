"""Tela "Lançar": gravar à mão o que não passa pelo banco."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import dados
from bussola.categorias import PRIORIDADES
from bussola.config import FUSO_HORARIO, ErroConfiguracao
from bussola.formatos import reais
from bussola.lancamentos import (
    CONTAS,
    ENTRADA,
    GASTO,
    ErroLancamento,
    lancamentos_manuais,
    lancar,
)
from bussola.limpeza import DINHEIRO, ErroLimpeza
from bussola.planilha import ErroPlanilha
from bussola.pluggy import ErroPluggy
from bussola.projecoes import NAO_E_RENDA

SEM_PRIORIDADE = "sem prioridade"
ULTIMOS_LANCAMENTOS = 10

# O número no fim das chaves dos campos muda para esvaziar o formulário depois de lançar.
st.session_state.setdefault("lancar_versao", 0)
versao = st.session_state["lancar_versao"]

transacoes = dados.transacoes()
hoje = dados.hoje()

st.title("Lançar à mão")
st.caption(
    "Para o que não passa pelo banco, como um gasto em dinheiro. O lançamento entra na "
    "planilha marcado como manual, e o robô nunca o altera."
)

aviso = st.session_state.pop("lancar_aviso", None)
if aviso:
    st.success(aviso)

with st.container(border=True):
    st.subheader("Novo lançamento")
    tipo = st.radio("Tipo", [GASTO, ENTRADA], horizontal=True, key=f"lancar_tipo_{versao}")
    eh_gasto = tipo == GASTO

    linha = st.columns(3)
    valor = linha[0].number_input(
        "Valor (R$)", min_value=0.0, value=None, step=1.0, format="%.2f", key=f"lancar_valor_{versao}"
    )
    data = linha[1].date_input(
        "Data", value=hoje, max_value=hoje, format="DD/MM/YYYY", key=f"lancar_data_{versao}"
    )
    conta = linha[2].selectbox(
        "De onde saiu" if eh_gasto else "Onde entrou", CONTAS, key=f"lancar_conta_{versao}"
    )
    if conta != DINHEIRO:
        st.warning(
            "O que passa pela conta ou pelo cartão já chega sozinho do banco. "
            "Lançar aqui também faria a mesma transação contar duas vezes."
        )

    descricao = st.text_input("Descrição", key=f"lancar_descricao_{versao}")

    categorias_conhecidas = sorted(
        {str(categoria) for categoria in transacoes["categoria"] if categoria} | {NAO_E_RENDA}
    )
    campos = st.columns(2)
    categoria = campos[0].selectbox(
        "Categoria",
        categorias_conhecidas,
        index=None,
        accept_new_options=True,
        placeholder="Escolha ou digite uma nova",
        key=f"lancar_categoria_{versao}",
        help=None
        if eh_gasto
        else f"Use “{NAO_E_RENDA}” para dinheiro que só voltou, como um amigo devolvendo.",
    )
    prioridade = (
        campos[1].selectbox(
            "Prioridade", [*PRIORIDADES, SEM_PRIORIDADE], key=f"lancar_prioridade_{versao}"
        )
        if eh_gasto
        else SEM_PRIORIDADE
    )

    if valor:
        st.caption(
            f"Vai para a planilha como {'gasto' if eh_gasto else 'entrada'} de {reais(valor)} "
            f"em {data:%d/%m/%Y}."
        )

    if st.button("Lançar", type="primary"):
        try:
            lancar(
                dados.armazenamento(),
                tipo=tipo,
                valor=valor or 0.0,
                data=data,
                conta=conta,
                descricao=descricao,
                categoria=categoria or "",
                prioridade="" if prioridade == SEM_PRIORIDADE else prioridade,
                agora=datetime.now(FUSO_HORARIO),
            )
        except (ErroLancamento, ErroPlanilha) as erro:
            st.error(str(erro))
        else:
            resumo = f"{tipo} de {reais(valor)} lançado."
            try:
                with st.spinner("Lançamento gravado. Refazendo as projeções..."):
                    dados.atualizar_planilha()
            except (ErroConfiguracao, ErroPluggy, ErroLimpeza, ErroPlanilha) as erro:
                st.session_state["lancar_aviso"] = (
                    f"{resumo} A atualização falhou ({erro}); as projeções serão refeitas "
                    "na próxima atualização."
                )
            else:
                st.session_state["lancar_aviso"] = resumo
            st.session_state["lancar_versao"] += 1
            st.rerun()

with st.container(border=True):
    st.subheader("Últimos lançamentos manuais")
    manuais = lancamentos_manuais(transacoes).head(ULTIMOS_LANCAMENTOS)
    if manuais.empty:
        st.caption("Nenhum lançamento manual ainda.")
    else:
        st.dataframe(
            pd.DataFrame(
                {
                    "Data": [f"{momento:%d/%m/%Y}" for momento in manuais["data"]],
                    "Descrição": manuais["descricao"].astype(str).tolist(),
                    "Conta": manuais["conta"].astype(str).tolist(),
                    "Categoria": manuais["categoria"].astype(str).tolist(),
                    "Valor": [reais(valor) for valor in manuais["valor"].astype(float)],
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Para trocar a categoria de um lançamento, use “Corrigir uma transação” na tela "
            "Regras. Para mudar o valor ou apagar, edite a aba transacoes da planilha."
        )
