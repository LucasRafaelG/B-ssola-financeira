"""Ponto de entrada do projeto. Rode com: python -m bussola.main

Etapas: buscar as transações (Pluggy ou dados fictícios), limpar, categorizar
pelas regras da planilha, gravar as novas sem duplicar e recalcular as abas
de resumo e projeção.

Para buscar mais histórico numa execução: python -m bussola.main --dias 180
O que aparece na tela são só contagens: nenhuma descrição, valor ou saldo.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bussola import demo
from bussola.categorias import categorizar, montar_regras, precisam_da_pluggy, recategorizar
from bussola.config import FUSO_HORARIO, Configuracao, ErroConfiguracao, carregar
from bussola.limpeza import ErroLimpeza, limpar
from bussola.planilha import (
    ABA_METAS,
    ABA_PROJECAO,
    ABA_REGRAS,
    ABA_RESUMO_MENSAL,
    COLUNAS_METAS,
    COLUNAS_REGRAS,
    Armazenamento,
    ErroPlanilha,
    aplicar_recategorizacao,
    atualizacao_automatica_ligada,
    conectar,
    gravar_novas,
    ler_contas_fixas,
    ler_tabela,
    ler_transacoes,
    reescrever_derivada,
)
from bussola.pluggy import (
    DIAS_DE_AVISO_DO_CONSENTIMENTO,
    ClientePluggy,
    ErroPluggy,
    Fonte,
    FontePluggy,
)
from bussola.projecoes import montar_projecao, montar_resumo_mensal

# Execução diária: compras do cartão podem aparecer com atraso, então olhamos uma semana.
DIAS_DE_BUSCA_DIARIA = 7

registro = logging.getLogger("bussola")


@dataclass(frozen=True)
class Resultado:
    """O que uma atualização mudou na aba `transacoes`."""

    novas: int
    recategorizadas: int


def abrir_armazenamento(configuracao: Configuracao) -> Armazenamento:
    """A planilha real ou, no modo demo, uma fictícia em memória."""
    if configuracao.acesso is None:
        return demo.planilha_ficticia()
    return conectar(configuracao.acesso.sheet_id)


def abrir_fonte(configuracao: Configuracao, hoje: date) -> Fonte:
    """De onde vêm as transações: a Pluggy ou, no modo demo, os dados fictícios."""
    if configuracao.acesso is None:
        return demo.FonteDemo(hoje)
    credenciais = configuracao.acesso.pluggy
    return FontePluggy(
        ClientePluggy(credenciais.client_id, credenciais.client_secret), credenciais.item_id
    )


def atualizar(
    armazenamento: Armazenamento,
    fonte: Fonte,
    configuracao: Configuracao,
    agora: datetime,
    dias_pedidos: int | None = None,
) -> Resultado:
    """Busca, limpa, categoriza, grava as transações novas e refaz as abas calculadas.

    É o mesmo caminho para o robô diário e para o aplicativo. `dias_pedidos`
    troca a janela de busca só nesta execução.
    """
    hoje = agora.date()
    regras = montar_regras(ler_tabela(armazenamento, ABA_REGRAS, COLUNAS_REGRAS))
    contas_fixas = ler_contas_fixas(armazenamento)
    metas = ler_tabela(armazenamento, ABA_METAS, COLUNAS_METAS)
    registro.info(
        "Planilha lida: %d regras, %d contas fixas, %d metas.",
        len(regras),
        len(contas_fixas),
        len(metas),
    )

    gravadas = ler_transacoes(armazenamento)
    ja_gravados = set(gravadas["id"].astype(str))
    dias = dias_pedidos or (DIAS_DE_BUSCA_DIARIA if ja_gravados else configuracao.dias_historico)
    registro.info(
        "%d transações já na planilha. Buscando os últimos %d dias.", len(ja_gravados), dias
    )

    transacoes = fonte.do_periodo(hoje - timedelta(days=dias), hoje)
    registro.info("%d contas, %d transações encontradas.", len(fonte.contas), len(transacoes))

    # Linhas antigas sem categoria, ou que perderam a regra: a sugestão da Pluggy não
    # fica guardada na planilha, então é pedida pelo id quando a busca do período não a trouxe.
    fora_do_periodo = precisam_da_pluggy(gravadas, regras) - {transacao.id for transacao in transacoes}
    extras = fonte.por_ids(fora_do_periodo) if fora_do_periodo else []
    categorias_pluggy = {t.id: t.categoria for t in [*transacoes, *extras] if t.categoria}

    mudancas = recategorizar(gravadas, regras, categorias_pluggy, fonte.traducoes)
    aplicar_recategorizacao(armazenamento, mudancas)

    tabela = categorizar(limpar(transacoes, fonte.contas, importado_em=agora), regras)
    novas = gravar_novas(armazenamento, tabela, ja_gravados)

    # As abas calculadas são refeitas a partir do que está gravado na planilha.
    atuais = ler_transacoes(armazenamento)
    resumo = montar_resumo_mensal(atuais)
    projecao = montar_projecao(atuais, contas_fixas, metas, hoje, fonte.ultima_fatura)
    reescrever_derivada(armazenamento, ABA_RESUMO_MENSAL, resumo)
    reescrever_derivada(armazenamento, ABA_PROJECAO, projecao)

    registro.info(
        "%d transações novas gravadas, %d já estavam na planilha.",
        len(novas),
        tabela["id"].nunique() - len(novas),
    )
    _registrar_contagem("  novas", Counter(novas["categorizado_por"]))
    registro.info("%d linhas antigas recategorizadas.", len(mudancas))
    _registrar_contagem("  recategorizadas", Counter(m.categorizado_por for m in mudancas.values()))

    situacao = Counter(gravadas["categorizado_por"].astype(str))
    for posicao, nova in mudancas.items():
        situacao[str(gravadas["categorizado_por"].iloc[posicao])] -= 1
        situacao[nova.categorizado_por] += 1
    situacao.update(novas["categorizado_por"])
    _registrar_contagem("Planilha agora", +situacao)
    registro.info(
        "Abas calculadas: resumo_mensal com %d linhas, projecao com %d linhas.",
        len(resumo) - 1,
        len(projecao) - 1,
    )
    return Resultado(novas=len(novas), recategorizadas=len(mudancas))


def executar(dias_pedidos: int | None = None, agendada: bool = False) -> int:
    """Roda a atualização e devolve o código de saída (0 = tudo certo, 1 = houve erro).

    `agendada` indica a execução diária do robô: ela só acontece se a atualização
    automática estiver ligada na planilha. Desligada, a execução termina antes de
    consultar o banco.
    """
    agora = datetime.now(FUSO_HORARIO)
    try:
        configuracao = carregar()
        if configuracao.acesso is None:
            registro.info("Modo demo: dados fictícios, sem acessar a Pluggy nem a planilha real.")
        armazenamento = abrir_armazenamento(configuracao)
        if agendada and not atualizacao_automatica_ligada(armazenamento):
            registro.info(
                "Atualização automática desligada na planilha: nada foi buscado nem gravado."
            )
            return 0
        fonte = abrir_fonte(configuracao, agora.date())
        atualizar(armazenamento, fonte, configuracao, agora, dias_pedidos)
    except (ErroConfiguracao, ErroPluggy, ErroLimpeza, ErroPlanilha) as erro:
        registro.error("%s", erro)
        return 1

    problemas = problemas_da_fonte(fonte, agora)
    for problema in problemas:
        registro.error("%s", problema)
    return 1 if problemas else 0


def problemas_da_fonte(fonte: Fonte, agora: datetime) -> list[str]:
    """O que precisa de atenção depois de uma atualização: conexão com o banco e contas que falharam.

    A atualização não é interrompida por esses problemas: o que já estava na
    Pluggy é gravado e as projeções são refeitas. No robô, eles fazem a execução
    terminar com erro, e é isso que faz o GitHub avisar por e-mail.
    """
    if not isinstance(fonte, FontePluggy):
        return []
    dias = fonte.item.dias_ate_o_consentimento_expirar(agora)
    if dias is not None and 0 <= dias <= DIAS_DE_AVISO_DO_CONSENTIMENTO:
        registro.warning(
            "Aviso: o consentimento do Open Finance expira em %d dias. Renove em meu.pluggy.ai.",
            dias,
        )
    problemas = fonte.item.problemas(agora)
    if fonte.contas_com_erro:
        problemas.append(f"{len(fonte.contas_com_erro)} conta(s) falharam.")
    return problemas


def _registrar_contagem(titulo: str, contagem: Counter[str]) -> None:
    if contagem:
        partes = ", ".join(f"{quantidade} {nome}" for nome, quantidade in sorted(contagem.items()))
        registro.info("%s: %s.", titulo, partes)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    argumentos = argparse.ArgumentParser(description="Atualiza a planilha Bússola.")
    argumentos.add_argument(
        "--dias",
        type=int,
        choices=range(1, 366),
        metavar="N",
        help="quantos dias buscar nesta execução (1 a 365), em vez da janela normal",
    )
    argumentos.add_argument(
        "--agendada",
        action="store_true",
        help="execução diária do robô: só roda se a atualização automática estiver ligada",
    )
    opcoes = argumentos.parse_args()
    sys.exit(executar(opcoes.dias, opcoes.agendada))
