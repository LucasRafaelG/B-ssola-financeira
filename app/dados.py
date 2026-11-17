"""Acesso aos dados para as telas do aplicativo.

As telas não calculam nada: leem o que o robô já gravou na planilha, pelas
mesmas funções da pasta `bussola/`. No modo demo (DATA_MODE=demo) a planilha é
fictícia e fica só na memória.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from bussola.config import FUSO_HORARIO, ErroConfiguracao, carregar
from bussola.limpeza import ErroLimpeza
from bussola.main import Resultado, abrir_armazenamento, abrir_fonte, atualizar, problemas_da_fonte
from bussola.planilha import (
    ABA_REGRAS,
    COLUNAS_REGRAS,
    Armazenamento,
    ErroPlanilha,
    atualizacao_automatica_ligada,
    definir_atualizacao_automatica,
    ler_tabela,
    ler_transacoes,
)
from bussola.pluggy import ErroPluggy
from bussola.projecoes import Projecao, ler_projecao

SEGUNDOS_DE_CACHE = 300


@st.cache_resource(show_spinner="Abrindo a planilha...")
def _armazenamento() -> tuple[Armazenamento, bool]:
    """A planilha aberta e se ela é a fictícia. Fica guardada enquanto o app estiver aberto."""
    configuracao = carregar()
    armazenamento = abrir_armazenamento(configuracao)
    if configuracao.acesso is None:
        # Modo demo: a planilha fictícia começa vazia; uma atualização a preenche, em memória.
        agora = datetime.now(FUSO_HORARIO)
        atualizar(armazenamento, abrir_fonte(configuracao, agora.date()), configuracao, agora)
    return armazenamento, configuracao.acesso is None


@st.cache_data(ttl=SEGUNDOS_DE_CACHE, show_spinner="Lendo a projeção...")
def _projecao() -> Projecao:
    return ler_projecao(_armazenamento()[0])


@st.cache_data(ttl=SEGUNDOS_DE_CACHE, show_spinner="Lendo as transações...")
def _transacoes() -> pd.DataFrame:
    return ler_transacoes(_armazenamento()[0])


@st.cache_data(ttl=SEGUNDOS_DE_CACHE, show_spinner="Lendo as regras...")
def _regras() -> pd.DataFrame:
    return ler_tabela(_armazenamento()[0], ABA_REGRAS, COLUNAS_REGRAS)


def modo_demo() -> bool:
    return _abrir_ou_parar()[1]


def projecao() -> Projecao:
    """A aba `projecao` da planilha. Se algo der errado, mostra o motivo e para a tela."""
    _abrir_ou_parar()
    try:
        return _projecao()
    except ErroPlanilha as erro:
        st.error(str(erro))
        st.stop()


def transacoes() -> pd.DataFrame:
    """A aba `transacoes` da planilha. Se algo der errado, mostra o motivo e para a tela."""
    _abrir_ou_parar()
    try:
        return _transacoes()
    except ErroPlanilha as erro:
        st.error(str(erro))
        st.stop()


def regras() -> pd.DataFrame:
    """A aba `regras` da planilha, como está escrita."""
    _abrir_ou_parar()
    try:
        return _regras()
    except ErroPlanilha as erro:
        st.error(str(erro))
        st.stop()


def armazenamento() -> Armazenamento:
    """A planilha aberta, para as telas que gravam."""
    return _abrir_ou_parar()[0]


def atualizar_planilha() -> tuple[Resultado, list[str]]:
    """Roda a mesma atualização do robô diário e descarta o que as telas tinham lido.

    Devolve o que mudou e os problemas que pedem atenção (conexão com o banco, por
    exemplo). Quem chama trata os erros (Pluggy fora do ar, planilha em formato inesperado...).
    """
    configuracao = carregar()
    agora = datetime.now(FUSO_HORARIO)
    try:
        fonte = abrir_fonte(configuracao, agora.date())
        resultado = atualizar(armazenamento(), fonte, configuracao, agora)
        return resultado, problemas_da_fonte(fonte, agora)
    finally:
        recarregar()


@st.cache_data(ttl=SEGUNDOS_DE_CACHE, show_spinner=False)
def _atualizacao_automatica() -> bool:
    return atualizacao_automatica_ligada(_armazenamento()[0])


def atualizacao_automatica() -> bool:
    """Se o robô diário está ligado, segundo a aba `config` da planilha."""
    _abrir_ou_parar()
    try:
        return _atualizacao_automatica()
    except ErroPlanilha as erro:
        st.error(str(erro))
        st.stop()


def definir_automatica(ligada: bool) -> None:
    """Liga ou desliga o robô diário, gravando a escolha na planilha."""
    definir_atualizacao_automatica(armazenamento(), ligada)
    _atualizacao_automatica.clear()


def hoje() -> date:
    return datetime.now(FUSO_HORARIO).date()


def recarregar() -> None:
    """Esquece o que foi lido, para a próxima tela buscar de novo na planilha."""
    _projecao.clear()
    _transacoes.clear()
    _regras.clear()
    _atualizacao_automatica.clear()


def _abrir_ou_parar() -> tuple[Armazenamento, bool]:
    try:
        return _armazenamento()
    except (ErroConfiguracao, ErroPlanilha, ErroPluggy, ErroLimpeza) as erro:
        st.error(str(erro))
        st.stop()
