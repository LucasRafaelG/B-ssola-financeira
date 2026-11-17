"""Lista as descrições mais frequentes que nenhuma regra cobre.

Rode no seu computador com: python -m bussola.sugestoes

Serve para decidir que regras novas criar na aba `regras`. Mostra descrições de
transações, então só funciona no terminal: recusa-se a rodar no GitHub Actions,
onde o log fica guardado.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from bussola import demo
from bussola.categorias import categorizar, descricoes_sem_regra, montar_regras
from bussola.config import FUSO_HORARIO, ErroConfiguracao, carregar
from bussola.limpeza import limpar
from bussola.planilha import (
    ABA_REGRAS,
    COLUNAS_REGRAS,
    ErroPlanilha,
    conectar,
    ler_tabela,
    ler_transacoes,
)

QUANTAS = 30


def executar() -> int:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("Este comando mostra descrições de transações e não roda no GitHub Actions.")
        return 1

    try:
        configuracao = carregar()
        if configuracao.acesso is None:
            agora = datetime.now(FUSO_HORARIO)
            fonte = demo.FonteDemo(agora.date())
            regras = montar_regras(ler_tabela(demo.planilha_ficticia(), ABA_REGRAS, COLUNAS_REGRAS))
            transacoes = fonte.do_periodo(agora.date() - timedelta(days=365), agora.date())
            tabela = categorizar(limpar(transacoes, fonte.contas, importado_em=agora), regras)
        else:
            tabela = ler_transacoes(conectar(configuracao.acesso.sheet_id))
    except (ErroConfiguracao, ErroPlanilha) as erro:
        print(erro)
        return 1

    resumo = descricoes_sem_regra(tabela, QUANTAS)
    if resumo.empty:
        print("Todas as transações já são cobertas por uma regra ou foram marcadas como manual.")
        return 0

    print(f"As {len(resumo)} descrições mais frequentes sem regra:\n")
    print(f"{'vezes':>5}  {'categoria atual':<28}  descrição")
    for linha in resumo.itertuples(index=False):
        print(f"{linha.vezes:>5}  {str(linha.categoria_atual):<28}  {linha.descricao}")
    print("\nPara criar uma regra, acrescente uma linha na aba 'regras' da planilha.")
    return 0


if __name__ == "__main__":
    sys.exit(executar())
