"""Tela "Regras": criar regras de categoria e ver o que cada uma cobre."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import dados
from bussola.categorias import (
    PRIORIDADES,
    ErroRegra,
    cobertura_das_regras,
    descricoes_sem_regra,
    previa_da_regra,
)
from bussola.config import ErroConfiguracao
from bussola.formatos import reais
from bussola.lancamentos import ErroLancamento, corrigir_categoria
from bussola.limpeza import ErroLimpeza
from bussola.planilha import ErroPlanilha, acrescentar_regra, apagar_regra, editar_regra
from bussola.pluggy import ErroPluggy

SEM_PRIORIDADE = "sem prioridade"
DESCRICOES_SUGERIDAS = 8
TRANSACOES_PARA_CORRIGIR = 50

# O número no fim das chaves dos campos muda para esvaziar ou preencher o formulário.
st.session_state.setdefault("regras_versao", 0)
st.session_state.setdefault("regras_sugestao", "")
versao = st.session_state["regras_versao"]


def _usar_como_regra(descricao: str) -> None:
    st.session_state["regras_sugestao"] = descricao
    st.session_state["regras_versao"] += 1


transacoes = dados.transacoes()
regras = dados.regras()

st.title("Regras e categorias")
st.caption(
    "Uma regra procura a palavra-chave na descrição da transação, sem ligar para maiúsculas, "
    "acentos ou espaços. Ela vale para as transações novas e para as antigas que ainda não têm regra."
)

for chave in ("regras_aviso", "correcao_aviso"):
    aviso = st.session_state.pop(chave, None)
    if aviso:
        st.success(aviso)

with st.container(border=True):
    st.subheader("Nova regra")
    campos = st.columns([3, 3, 2])
    palavra_chave = campos[0].text_input(
        "Palavra-chave",
        value=st.session_state["regras_sugestao"],
        key=f"regras_palavra_{versao}",
        help="Um trecho da descrição. Quanto mais curto, mais transações pega: "
        "IFOOD cobre todas as compras do iFood.",
    )
    categorias_conhecidas = sorted(
        {str(categoria) for categoria in [*regras["categoria"], *transacoes["categoria"]] if categoria}
    )
    categoria = campos[1].selectbox(
        "Categoria",
        categorias_conhecidas,
        index=None,
        accept_new_options=True,
        placeholder="Escolha ou digite uma nova",
        key=f"regras_categoria_{versao}",
    )
    prioridade = campos[2].selectbox(
        "Prioridade", [*PRIORIDADES, SEM_PRIORIDADE], key=f"regras_prioridade_{versao}"
    )

    previa = previa_da_regra(palavra_chave, transacoes)
    if palavra_chave.strip():
        if previa.encontradas == 0:
            st.caption("Nenhuma transação atual tem essa palavra-chave. A regra valeria para as próximas.")
        else:
            partes = [
                f"{previa.encontradas} transações têm essa palavra-chave: {previa.mudariam} passariam "
                "a usar a regra"
            ]
            if previa.ja_com_regra:
                partes.append(f"{previa.ja_com_regra} já têm outra regra e ficam como estão")
            if previa.manuais:
                partes.append(f"{previa.manuais} foram marcadas à mão e não mudam")
            st.caption("; ".join(partes) + ".")

    if st.button("Criar regra", type="primary"):
        try:
            acrescentar_regra(
                dados.armazenamento(),
                palavra_chave,
                categoria or "",
                "" if prioridade == SEM_PRIORIDADE else prioridade,
            )
        except (ErroRegra, ErroPlanilha) as erro:
            st.error(str(erro))
        else:
            try:
                with st.spinner("Regra criada. Aplicando às transações..."):
                    resultado, _ = dados.atualizar_planilha()
            except (ErroConfiguracao, ErroPluggy, ErroLimpeza, ErroPlanilha) as erro:
                st.session_state["regras_aviso"] = (
                    f'Regra "{palavra_chave.strip()}" criada, mas a atualização falhou ({erro}). '
                    "Ela será aplicada na próxima atualização."
                )
            else:
                st.session_state["regras_aviso"] = (
                    f'Regra "{palavra_chave.strip()}" criada. '
                    f"{resultado.recategorizadas} transações recategorizadas."
                )
            st.session_state["regras_sugestao"] = ""
            st.session_state["regras_versao"] += 1
            st.rerun()

esquerda, direita = st.columns(2)

with esquerda, st.container(border=True):
    st.subheader("Regras em uso")
    cobertura = cobertura_das_regras(regras, transacoes)
    if cobertura.empty:
        st.caption("Nenhuma regra ainda.")
    else:
        st.dataframe(
            pd.DataFrame(
                {
                    "Palavra-chave": cobertura["palavra_chave"],
                    "Categoria": cobertura["categoria"],
                    "Prioridade": cobertura["prioridade"].replace("", SEM_PRIORIDADE),
                    "Cobre": cobertura["cobre"],
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "“Cobre” é quantas transações da planilha têm a palavra-chave e ficariam com essa regra. "
            "Para mudar ou apagar uma regra, use “Editar uma regra”, logo abaixo."
        )

with direita, st.container(border=True):
    st.subheader("Descrições mais frequentes sem regra")
    sem_regra = descricoes_sem_regra(transacoes, DESCRICOES_SUGERIDAS)
    if sem_regra.empty:
        st.caption("Todas as transações já são cobertas por uma regra ou foram marcadas à mão.")
    linhas = zip(
        sem_regra["descricao"].astype(str),
        sem_regra["vezes"].astype(int),
        sem_regra["categoria_atual"].astype(str),
        strict=True,
    )
    for posicao, (descricao, vezes, categoria_atual) in enumerate(linhas):
        texto, botao = st.columns([3, 2], vertical_alignment="center")
        texto.markdown(
            f"**{descricao}**  \n{vezes} {'vez' if vezes == 1 else 'vezes'} · "
            f"hoje em “{categoria_atual}”"
        )
        botao.button(
            "Usar como regra",
            key=f"regras_usar_{posicao}",
            on_click=_usar_como_regra,
            args=(descricao,),
            width="stretch",
        )



def _reaplicar_regras(mensagem: str) -> None:
    """Depois de editar ou apagar uma regra: reaplica as regras a todas as transações."""
    try:
        with st.spinner("Reaplicando as regras às transações..."):
            resultado, _ = dados.atualizar_planilha()
    except (ErroConfiguracao, ErroPluggy, ErroLimpeza, ErroPlanilha) as erro:
        st.session_state["regras_aviso"] = (
            f"{mensagem} A atualização falhou ({erro}); a mudança será aplicada às "
            "transações na próxima atualização."
        )
    else:
        st.session_state["regras_aviso"] = (
            f"{mensagem} {resultado.recategorizadas} transações recategorizadas."
        )
    st.session_state["edicao_versao"] += 1
    st.rerun()


with st.container(border=True):
    st.subheader("Editar uma regra")
    st.caption(
        "Ao salvar ou apagar, as transações categorizadas por regra são reavaliadas pelas "
        "regras como ficarem: pegam a regra nova, outra regra que as cubra, a categoria da "
        "Pluggy ou ficam sem categoria. As marcadas à mão não mudam."
    )
    st.session_state.setdefault("edicao_versao", 0)
    versao_da_edicao = st.session_state["edicao_versao"]
    palavras = [str(palavra) for palavra in cobertura["palavra_chave"]]
    if not palavras:
        st.caption("Nenhuma regra para editar.")
    else:
        escolhida = st.selectbox("Regra", palavras, key=f"edicao_regra_{versao_da_edicao}")
        atual = cobertura[cobertura["palavra_chave"].astype(str) == escolhida].iloc[0]
        sufixo = f"{versao_da_edicao}_{escolhida}"
        campos = st.columns([3, 3, 2])
        nova_palavra = campos[0].text_input(
            "Palavra-chave", value=escolhida, key=f"edicao_palavra_{sufixo}"
        )
        categoria_atual = str(atual["categoria"])
        nova_categoria = campos[1].selectbox(
            "Categoria",
            categorias_conhecidas,
            index=categorias_conhecidas.index(categoria_atual)
            if categoria_atual in categorias_conhecidas
            else None,
            accept_new_options=True,
            placeholder="Escolha ou digite uma nova",
            key=f"edicao_categoria_{sufixo}",
        )
        opcoes_de_prioridade = [*PRIORIDADES, SEM_PRIORIDADE]
        prioridade_atual = str(atual["prioridade"])
        nova_prioridade = campos[2].selectbox(
            "Prioridade",
            opcoes_de_prioridade,
            index=opcoes_de_prioridade.index(prioridade_atual)
            if prioridade_atual in PRIORIDADES
            else len(PRIORIDADES),
            key=f"edicao_prioridade_{sufixo}",
        )
        salvar, apagar = st.columns(2)
        if salvar.button("Salvar alterações", key=f"edicao_salvar_{sufixo}"):
            try:
                editar_regra(
                    dados.armazenamento(),
                    escolhida,
                    nova_palavra,
                    nova_categoria or "",
                    "" if nova_prioridade == SEM_PRIORIDADE else nova_prioridade,
                )
            except (ErroRegra, ErroPlanilha) as erro:
                st.error(str(erro))
            else:
                _reaplicar_regras(f'Regra "{nova_palavra.strip()}" atualizada.')
        confirmado = apagar.checkbox(
            "Quero apagar esta regra", key=f"edicao_confirmar_{sufixo}"
        )
        if apagar.button("Apagar regra", disabled=not confirmado, key=f"edicao_apagar_{sufixo}"):
            try:
                apagar_regra(dados.armazenamento(), escolhida)
            except (ErroRegra, ErroPlanilha) as erro:
                st.error(str(erro))
            else:
                _reaplicar_regras(f'Regra "{escolhida}" apagada.')

with st.container(border=True):
    st.subheader("Corrigir uma transação")
    st.caption(
        "Para um caso isolado, sem criar regra. A transação fica marcada como manual "
        "e não é mais recategorizada pelo robô."
    )
    st.session_state.setdefault("correcao_versao", 0)
    versao_da_correcao = st.session_state["correcao_versao"]
    busca = st.text_input(
        "Procurar na descrição",
        key=f"correcao_busca_{versao_da_correcao}",
        placeholder="Deixe vazio para ver as mais recentes",
    )
    recentes = transacoes.sort_values("data", ascending=False, kind="stable")
    if busca.strip():
        recentes = recentes[
            recentes["descricao"].astype(str).str.contains(busca.strip(), case=False, regex=False)
        ]
    recentes = recentes.head(TRANSACOES_PARA_CORRIGIR)
    if recentes.empty:
        st.caption("Nenhuma transação encontrada.")
    else:
        rotulos = {
            identificador: f"{data:%d/%m/%Y} · {descricao} · {reais(valor)} · {categoria_atual}"
            for identificador, data, descricao, valor, categoria_atual in zip(
                recentes["id"].astype(str),
                recentes["data"],
                recentes["descricao"].astype(str),
                recentes["valor"].astype(float),
                recentes["categoria"].astype(str),
                strict=True,
            )
        }
        escolhida = st.selectbox(
            "Transação",
            list(rotulos),
            format_func=rotulos.__getitem__,
            key=f"correcao_transacao_{versao_da_correcao}",
        )
        atual = recentes[recentes["id"].astype(str) == escolhida].iloc[0]
        campos = st.columns([3, 2])
        nova_categoria = campos[0].selectbox(
            "Nova categoria",
            categorias_conhecidas,
            index=categorias_conhecidas.index(str(atual["categoria"]))
            if str(atual["categoria"]) in categorias_conhecidas
            else None,
            accept_new_options=True,
            placeholder="Escolha ou digite uma nova",
            key=f"correcao_categoria_{versao_da_correcao}_{escolhida}",
        )
        opcoes_de_prioridade = [*PRIORIDADES, SEM_PRIORIDADE]
        nova_prioridade = campos[1].selectbox(
            "Nova prioridade",
            opcoes_de_prioridade,
            index=opcoes_de_prioridade.index(str(atual["prioridade"]))
            if str(atual["prioridade"]) in PRIORIDADES
            else len(PRIORIDADES),
            key=f"correcao_prioridade_{versao_da_correcao}_{escolhida}",
        )
        if st.button("Salvar correção"):
            try:
                corrigir_categoria(
                    dados.armazenamento(),
                    escolhida,
                    nova_categoria or "",
                    "" if nova_prioridade == SEM_PRIORIDADE else nova_prioridade,
                )
            except (ErroLancamento, ErroPlanilha) as erro:
                st.error(str(erro))
            else:
                try:
                    with st.spinner("Correção salva. Refazendo as projeções..."):
                        dados.atualizar_planilha()
                except (ErroConfiguracao, ErroPluggy, ErroLimpeza, ErroPlanilha) as erro:
                    st.session_state["correcao_aviso"] = (
                        f"Correção salva, mas a atualização falhou ({erro}). "
                        "As projeções serão refeitas na próxima atualização."
                    )
                else:
                    st.session_state["correcao_aviso"] = (
                        f"Correção salva: a transação agora está em “{(nova_categoria or '').strip()}”."
                    )
                st.session_state["correcao_versao"] += 1
                st.rerun()
