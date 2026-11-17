"""Aplicativo da Bússola. Abra com: streamlit run app/Bussola.py

Roda no seu computador e lê a mesma planilha que o robô diário atualiza.
"""

from __future__ import annotations

import streamlit as st

import dados
from bussola.config import ErroConfiguracao
from bussola.limpeza import ErroLimpeza
from bussola.planilha import ErroPlanilha
from bussola.pluggy import ErroPluggy
from bussola.projecoes import ITEM_MES, SECAO_REFERENCIA

st.set_page_config(page_title="Bússola", layout="wide")

pagina = st.navigation(
    [
        st.Page("paginas/mes.py", title="Mês", default=True),
        st.Page("paginas/semana.py", title="Semana"),
        st.Page("paginas/lancar.py", title="Lançar"),
        st.Page("paginas/regras.py", title="Regras"),
    ]
)


def _trocar_atualizacao_automatica() -> None:
    ligada = bool(st.session_state["atualizacao_automatica"])
    try:
        dados.definir_automatica(ligada)
    except ErroPlanilha as erro:
        st.session_state["barra_erro"] = f"Não foi possível gravar a escolha: {erro}"
    else:
        st.session_state["barra_aviso"] = (
            "Atualização automática ligada: o robô volta a rodar todo dia às 07:00."
            if ligada
            else "Atualização automática desligada: os dados só são buscados quando você "
            "apertar “Atualizar agora”."
        )


def _atualizar_agora() -> None:
    try:
        with st.spinner("Buscando as transações e refazendo as projeções..."):
            resultado, problemas = dados.atualizar_planilha()
    except (ErroConfiguracao, ErroPluggy, ErroLimpeza, ErroPlanilha) as erro:
        st.session_state["barra_erro"] = f"A atualização falhou: {erro}"
        return
    st.session_state["barra_aviso"] = (
        f"Atualizado: {resultado.novas} transações novas, "
        f"{resultado.recategorizadas} recategorizadas."
    )
    if problemas:
        st.session_state["barra_erro"] = " ".join(problemas)


with st.sidebar:
    st.title("Bússola")
    if dados.modo_demo():
        st.caption("Modo demo: dados fictícios.")

    st.subheader("Atualização")
    automatica = st.toggle(
        "Automática",
        value=dados.atualizacao_automatica(),
        key="atualizacao_automatica",
        on_change=_trocar_atualizacao_automatica,
        help="Ligada: o robô busca as transações no banco todo dia às 07:00. "
        "Desligada: o robô não consulta o banco, e os dados só chegam quando você "
        "apertar “Atualizar agora”.",
    )
    st.caption(
        "O robô atualiza todo dia às 07:00."
        if automatica
        else "O robô está parado. Atualize quando quiser, pelo botão."
    )
    if st.button("Atualizar agora", type="primary", width="stretch"):
        _atualizar_agora()
        st.rerun()
    if st.button("Recarregar da planilha", width="stretch"):
        dados.recarregar()
        st.rerun()

    referencia = dados.projecao().item(SECAO_REFERENCIA, ITEM_MES)
    if referencia:
        # A observação começa com "Calculado em dd/mm/aaaa."
        st.caption("Projeções: " + referencia.observacao.split(".")[0].lower() + ".")

    aviso = st.session_state.pop("barra_aviso", None)
    if aviso:
        st.success(aviso)
    erro = st.session_state.pop("barra_erro", None)
    if erro:
        st.error(erro)

pagina.run()
