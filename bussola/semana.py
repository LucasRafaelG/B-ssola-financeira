"""Resumo de uma semana (segunda a domingo), para a tela "Semana" do aplicativo.

Usa as mesmas definições de gasto e renda da projeção do mês. A comparação
"frente à sua média" usa as 12 semanas anteriores, ou o que houver de histórico.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from bussola.categorias import descricoes_sem_regra, linhas_sem_regra
from bussola.projecoes import com_gasto_e_renda

SEMANAS_DE_BASE = 12
MAIORES_GASTOS = 5
DESCRICOES_SEM_REGRA = 5


@dataclass(frozen=True)
class ResumoDaSemana:
    inicio: date  # segunda-feira
    fim: date  # domingo
    dias_decorridos: int  # 7, ou menos se a semana ainda não acabou
    gasto: float
    gasto_da_semana_anterior: float
    renda: float
    entradas: int  # quantas transações de renda
    transacoes: int
    sem_regra: int
    media_diaria_de_referencia: float
    dias_de_referencia: int  # sobre quantos dias a média foi calculada (0 = sem histórico)
    por_dia: pd.DataFrame  # colunas: data, gasto (sempre 7 linhas)
    por_categoria: pd.DataFrame  # colunas: categoria, semana, media_semanal, diferenca
    maiores_gastos: pd.DataFrame  # colunas: data, descricao, categoria, valor
    descricoes_sem_regra: pd.DataFrame  # colunas: descricao, vezes, categoria_atual


def inicio_da_semana(dia: date) -> date:
    """A segunda-feira da semana do dia."""
    return dia - timedelta(days=dia.weekday())


def semanas_disponiveis(transacoes: pd.DataFrame, hoje: date) -> list[date]:
    """As segundas-feiras das semanas com histórico, da semana de hoje para trás."""
    atual = inicio_da_semana(hoje)
    if transacoes.empty:
        return [atual]
    primeira = inicio_da_semana(transacoes["data"].min().date())
    quantas = (atual - primeira).days // 7 + 1
    return [atual - timedelta(weeks=passo) for passo in range(max(quantas, 1))]


def resumir_semana(transacoes: pd.DataFrame, inicio: date, hoje: date) -> ResumoDaSemana:
    """Resume a semana que começa em `inicio` (uma segunda-feira)."""
    fim = inicio + timedelta(days=6)
    dados = com_gasto_e_renda(transacoes)
    contam = dados[~dados["interno"]]  # movimentos internos não são gasto nem renda

    def entre(tabela: pd.DataFrame, de: date, ate: date) -> pd.DataFrame:
        # As datas da planilha não têm hora, então basta comparar com o dia.
        return tabela[(tabela["data"] >= pd.Timestamp(de)) & (tabela["data"] <= pd.Timestamp(ate))]

    da_semana = entre(contam, inicio, fim)
    anterior = entre(contam, inicio - timedelta(days=7), inicio - timedelta(days=1))

    # Base da média: as 12 semanas anteriores, ou só o trecho delas que houver no histórico.
    fim_da_base = inicio - timedelta(days=1)
    if dados.empty:
        inicio_da_base, dias_de_referencia = inicio, 0
    else:
        inicio_da_base = max(inicio - timedelta(weeks=SEMANAS_DE_BASE), dados["data"].min().date())
        dias_de_referencia = max((fim_da_base - inicio_da_base).days + 1, 0)
    base = entre(contam, inicio_da_base, fim_da_base)

    gasto_por_dia = da_semana.groupby(da_semana["data"].dt.date)["gasto"].sum()
    por_dia = pd.DataFrame(
        {
            "data": [inicio + timedelta(days=passo) for passo in range(7)],
            "gasto": [float(gasto_por_dia.get(inicio + timedelta(days=passo), 0.0)) for passo in range(7)],
        }
    )

    gastos = da_semana[da_semana["gasto"] > 0]
    maiores = gastos.sort_values(["gasto", "data"], ascending=[False, True], kind="stable").head(
        MAIORES_GASTOS
    )

    return ResumoDaSemana(
        inicio=inicio,
        fim=fim,
        dias_decorridos=min(max((hoje - inicio).days + 1, 1), 7),
        gasto=float(da_semana["gasto"].sum()),
        gasto_da_semana_anterior=float(anterior["gasto"].sum()),
        renda=float(da_semana["renda"].sum()),
        entradas=int((da_semana["renda"] > 0).sum()),
        transacoes=len(da_semana),
        sem_regra=len(linhas_sem_regra(da_semana)),
        media_diaria_de_referencia=(
            float(base["gasto"].sum()) / dias_de_referencia if dias_de_referencia else 0.0
        ),
        dias_de_referencia=dias_de_referencia,
        por_dia=por_dia,
        por_categoria=_por_categoria(da_semana, base, dias_de_referencia),
        maiores_gastos=pd.DataFrame(
            {
                "data": [momento.date() for momento in maiores["data"]],
                "descricao": maiores["descricao"].astype(str).tolist(),
                "categoria": maiores["categoria"].astype(str).tolist(),
                "valor": maiores["gasto"].astype(float).tolist(),
            }
        ),
        descricoes_sem_regra=descricoes_sem_regra(da_semana, DESCRICOES_SEM_REGRA),
    )


def _por_categoria(
    da_semana: pd.DataFrame, base: pd.DataFrame, dias_de_referencia: int
) -> pd.DataFrame:
    """Gasto de cada categoria na semana frente à média semanal, da maior diferença para a menor."""
    semana = da_semana.groupby("categoria")["gasto"].sum()
    media = (
        base.groupby("categoria")["gasto"].sum() / dias_de_referencia * 7
        if dias_de_referencia
        else pd.Series(dtype="float64")
    )
    linhas = [
        {
            "categoria": str(categoria),
            "semana": float(semana.get(categoria, 0.0)),
            "media_semanal": float(media.get(categoria, 0.0)),
        }
        for categoria in sorted(set(semana.index) | set(media.index))
    ]
    tabela = pd.DataFrame(linhas, columns=["categoria", "semana", "media_semanal"])
    tabela["diferenca"] = tabela["semana"] - tabela["media_semanal"]
    com_movimento = tabela[(tabela["semana"].round(2) != 0) | (tabela["media_semanal"].round(2) != 0)]
    return com_movimento.sort_values(
        ["diferenca", "categoria"], ascending=[False, True], kind="stable"
    ).reset_index(drop=True)
