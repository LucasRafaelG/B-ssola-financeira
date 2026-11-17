"""Cálculos do mês: resumo por categoria e projeção até o fim do mês.

Método, de propósito simples:
- gasto projetado = gasto até hoje + média diária dos últimos 3 meses × dias que faltam;
- renda estimada = o maior entre o que já entrou e a média mensal dos últimos 3 meses;
- sobra prevista = renda − gasto projetado, comparada com a meta de economia.

Movimentos internos (pagar a fatura do cartão, transferir entre contas próprias,
investir) não são gasto nem renda: o dinheiro só mudou de lugar.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from numbers import Real

import pandas as pd

from bussola.limpeza import (
    CARTAO_DE_CREDITO,
    COLUNAS_PLANILHA,
    CONTA_CORRENTE,
    DINHEIRO,
    TIPO_CREDITO,
    TIPO_DEBITO,
)
from bussola.planilha import (
    ABA_PROJECAO,
    ABA_TRANSACOES,
    Armazenamento,
    Celula,
    ErroPlanilha,
    Formula,
    LinhaDerivada,
    letra_da_coluna,
)
from bussola.pluggy import Fatura

# Nomes como a Pluggy traduz (tabela oficial) ou como uma regra da planilha define.
CATEGORIAS_INTERNAS = frozenset(
    {
        "Pagamento de cartão de crédito",
        "Transferência mesma titularidade",
        "Transferência mesma titularidade - Dinheiro",
        "Transferência mesma titularidade - PIX",
        "Transferência mesma titularidade - TED",
        "Investimentos",
        "Investimento automático",
    }
)
# Categoria usada numa regra para entradas que não são renda (ex.: amigo devolvendo dinheiro).
NAO_E_RENDA = "Não é renda"

MESES_DE_BASE = 3

CABECALHO_RESUMO = [
    "mes",
    "categoria",
    "total_gasto",
    "media_3_meses_anteriores",
    "diferenca",
    "observacao",
]
CABECALHO_PROJECAO = ["secao", "item", "ate_hoje", "projetado", "observacao"]

# Nomes das seções e dos itens da aba projecao: quem escreve e quem lê usa os mesmos.
SECAO_REFERENCIA = "Referência"
SECAO_RESUMO = "Resumo"
SECAO_CATEGORIAS = "Gasto por categoria"
SECAO_INTERNOS = "Movimento interno"
SECAO_PARCELAS = "Parcela futura"
SECAO_PARCELAS_POR_MES = "Parcelas por mês"
SECAO_CONTAS_FIXAS = "Conta fixa"
ITEM_MES = "Mês"
ITEM_METODO = "Método"
ITEM_GASTO = "Gasto total"
ITEM_FATURA = "Fatura do cartão"
ITEM_RENDA = "Entradas (renda)"
ITEM_SOBRA = "Sobra prevista"
ITEM_META = "Meta de economia"
ITEM_META_NO_CAMINHO = "Meta no caminho?"

_PADRAO_DE_PARCELA = re.compile(r"\s*\d+\s*/\s*\d+\s*")


@dataclass(frozen=True)
class Periodo:
    """As datas que a projeção usa, todas derivadas do dia de hoje e do histórico."""

    hoje: pd.Timestamp
    inicio_do_mes: pd.Timestamp
    dias_no_mes: int
    dias_restantes: int
    inicio_da_base: pd.Timestamp
    fim_da_base: pd.Timestamp
    dias_de_base: int


@dataclass(frozen=True)
class LinhaDeProjecao:
    secao: str
    item: str
    ate_hoje: Celula
    projetado: Celula
    observacao: str


@dataclass(frozen=True)
class Projecao:
    """A aba `projecao` como foi gravada, para quem só quer mostrar os números."""

    linhas: tuple[LinhaDeProjecao, ...]

    def da_secao(self, secao: str) -> list[LinhaDeProjecao]:
        return [linha for linha in self.linhas if linha.secao == secao]

    def item(self, secao: str, item: str) -> LinhaDeProjecao | None:
        return next((linha for linha in self.da_secao(secao) if linha.item == item), None)


def ler_projecao(armazenamento: Armazenamento) -> Projecao:
    """Lê a aba `projecao` já calculada. Não refaz nenhum cálculo nem consulta o banco."""
    linhas = armazenamento.ler(ABA_PROJECAO)
    if not linhas or [str(celula).strip() for celula in linhas[0]] != CABECALHO_PROJECAO:
        raise ErroPlanilha(
            f'A aba "{ABA_PROJECAO}" não está no formato esperado. Rode a atualização para refazê-la.'
        )
    largura = len(CABECALHO_PROJECAO)
    completas = [(list(linha) + [""] * largura)[:largura] for linha in linhas[1:]]
    return Projecao(
        tuple(
            LinhaDeProjecao(str(secao), str(item), ate_hoje, projetado, str(observacao))
            for secao, item, ate_hoje, projetado, observacao in completas
        )
    )


def montar_periodo(hoje: date, primeira_data: pd.Timestamp | None) -> Periodo:
    """A base da média são os 3 meses anteriores, ou o que houver de histórico dentro deles."""
    dia = pd.Timestamp(hoje)
    inicio_do_mes = dia.replace(day=1)
    fim_da_base = inicio_do_mes - pd.Timedelta(days=1)
    inicio_da_base = inicio_do_mes - pd.DateOffset(months=MESES_DE_BASE)
    if primeira_data is not None and primeira_data > inicio_da_base:
        inicio_da_base = primeira_data
    return Periodo(
        hoje=dia,
        inicio_do_mes=inicio_do_mes,
        dias_no_mes=dia.days_in_month,
        dias_restantes=dia.days_in_month - dia.day,
        inicio_da_base=inicio_da_base,
        fim_da_base=fim_da_base,
        dias_de_base=max((fim_da_base - inicio_da_base).days + 1, 0),
    )


def com_gasto_e_renda(transacoes: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta as colunas `gasto` e `renda` (números positivos) e `interno`.

    Gasto: débitos, menos os estornos no cartão. Renda: entradas na conta corrente ou em dinheiro,
    fora as marcadas como "Não é renda". Movimentos internos ficam zerados nos dois.
    """
    interno = transacoes["categoria"].isin(CATEGORIAS_INTERNAS)
    debito = transacoes["tipo"] == TIPO_DEBITO
    credito = transacoes["tipo"] == TIPO_CREDITO
    estorno_no_cartao = credito & (transacoes["conta"] == CARTAO_DE_CREDITO)
    entrada = (
        credito
        & transacoes["conta"].isin([CONTA_CORRENTE, DINHEIRO])
        & (transacoes["categoria"] != NAO_E_RENDA)
    )
    return transacoes.assign(
        interno=interno,
        gasto=(-transacoes["valor"]).where(~interno & (debito | estorno_no_cartao), 0.0),
        renda=transacoes["valor"].where(~interno & entrada, 0.0),
    )


def montar_resumo_mensal(transacoes: pd.DataFrame) -> list[LinhaDerivada]:
    """Linhas da aba `resumo_mensal`: uma por mês e categoria, com fórmulas conferíveis."""
    linhas: list[LinhaDerivada] = [list(CABECALHO_RESUMO)]
    if transacoes.empty:
        return linhas
    dados = com_gasto_e_renda(transacoes)
    movimentos = dados[(dados["tipo"] == TIPO_DEBITO) | (dados["gasto"] != 0)]
    primeira_data = dados["data"].min()
    pares = (
        movimentos.assign(mes=movimentos["data"].dt.to_period("M"))[["mes", "categoria"]]
        .drop_duplicates()
        .sort_values(["mes", "categoria"], ascending=[False, True])
    )
    for mes, categoria in pares.itertuples(index=False, name=None):
        numero = len(linhas) + 1  # linha na planilha; o cabeçalho é a 1
        inicio = mes.start_time
        fim = (mes + 1).start_time
        inicio_da_media = (mes - MESES_DE_BASE).start_time
        observacoes = []
        if categoria in CATEGORIAS_INTERNAS:
            observacoes.append("Movimento interno: não é gasto.")
        if primeira_data > inicio_da_media:
            observacoes.append(
                f"Histórico começa em {primeira_data:%d/%m/%Y}: média com meses incompletos."
            )
        linhas.append(
            [
                str(mes),
                str(categoria),
                Formula("=" + _soma_de_gastos(numero, inicio, fim)),
                Formula(f"=({_soma_de_gastos(numero, inicio_da_media, inicio)})/{MESES_DE_BASE}"),
                Formula(f"=C{numero}-D{numero}"),
                " ".join(observacoes),
            ]
        )
    return linhas


def _soma_de_gastos(numero_da_linha: int, inicio: pd.Timestamp, fim: pd.Timestamp) -> str:
    """Trecho de fórmula: gasto da categoria da linha entre as datas (fim não incluído).

    Soma os débitos e desconta os estornos no cartão, igual a `com_gasto_e_renda`.
    """

    def coluna(nome: str) -> str:
        letra = letra_da_coluna(COLUNAS_PLANILHA.index(nome))
        return f"{ABA_TRANSACOES}!${letra}:${letra}"

    filtros = (
        f"{coluna('categoria')};$B{numero_da_linha};"
        f'{coluna("data")};">="&DATE({inicio.year};{inicio.month};1);'
        f'{coluna("data")};"<"&DATE({fim.year};{fim.month};1)'
    )
    debitos = f'SUMIFS({coluna("valor")};{filtros};{coluna("tipo")};"{TIPO_DEBITO}")'
    estornos = (
        f'SUMIFS({coluna("valor")};{filtros};{coluna("tipo")};"{TIPO_CREDITO}";'
        f'{coluna("conta")};"{CARTAO_DE_CREDITO}")'
    )
    return f"-{debitos}-{estornos}"


def montar_projecao(
    transacoes: pd.DataFrame,
    contas_fixas: pd.DataFrame,
    metas: pd.DataFrame,
    hoje: date,
    ultima_fatura: Fatura | None = None,
) -> list[LinhaDerivada]:
    """Linhas da aba `projecao` para o mês corrente.

    `ultima_fatura` é a fatura do cartão fechada mais recentemente. Sem ela, a
    fatura é aproximada pelo mês do calendário.
    """
    dados = com_gasto_e_renda(transacoes)
    periodo = montar_periodo(hoje, None if dados.empty else dados["data"].min())
    do_mes = dados[(dados["data"] >= periodo.inicio_do_mes) & (dados["data"] <= periodo.hoje)]
    da_base = dados[
        (dados["data"] >= periodo.inicio_da_base) & (dados["data"] <= periodo.fim_da_base)
    ]

    def projetar(ate_hoje: float, soma_da_base: float) -> float:
        media_diaria = soma_da_base / periodo.dias_de_base if periodo.dias_de_base else 0.0
        return ate_hoje + media_diaria * periodo.dias_restantes

    gasto_ate_hoje = float(do_mes["gasto"].sum())
    gasto_projetado = projetar(gasto_ate_hoje, float(da_base["gasto"].sum()))

    renda_ate_hoje = float(do_mes["renda"].sum())
    renda_media_mensal = (
        float(da_base["renda"].sum()) / periodo.dias_de_base * periodo.dias_no_mes
        if periodo.dias_de_base
        else 0.0
    )
    renda_estimada = max(renda_ate_hoje, renda_media_mensal)

    sobra_segura = renda_ate_hoje - gasto_projetado
    sobra_provavel = renda_estimada - gasto_projetado
    meta, texto_da_meta = _meta_de_economia(metas)

    base = (
        f"Média diária calculada sobre {periodo.dias_de_base} dias "
        f"({periodo.inicio_da_base:%d/%m/%Y} a {periodo.fim_da_base:%d/%m/%Y})."
        if periodo.dias_de_base
        else "Ainda não há histórico de meses anteriores: o projetado é igual ao até hoje."
    )
    linhas: list[LinhaDerivada] = [
        list(CABECALHO_PROJECAO),
        [
            SECAO_REFERENCIA,
            ITEM_MES,
            f"{periodo.hoje:%Y-%m}",
            "",
            f"Calculado em {periodo.hoje:%d/%m/%Y}. Faltam {periodo.dias_restantes} dias no mês.",
        ],
        [
            SECAO_REFERENCIA,
            ITEM_METODO,
            "",
            "",
            "Projetado = gasto até hoje + média diária dos últimos 3 meses × dias que faltam. "
            + base,
        ],
        [SECAO_RESUMO, ITEM_GASTO, _reais(gasto_ate_hoje), _reais(gasto_projetado), ""],
        _linha_da_fatura(dados, da_base, periodo, ultima_fatura),
        [
            SECAO_RESUMO,
            ITEM_RENDA,
            _reais(renda_ate_hoje),
            _reais(renda_estimada),
            "Projetado = o maior entre o que já entrou e a média mensal dos últimos 3 meses.",
        ],
        [
            SECAO_RESUMO,
            ITEM_SOBRA,
            _reais(sobra_segura),
            _reais(sobra_provavel),
            "Até hoje = cenário seguro (só o que já entrou). Projetado = cenário provável "
            "(renda estimada). Os dois descontam o gasto projetado.",
        ],
    ]
    if meta is None:
        linhas.append([SECAO_RESUMO, ITEM_META, "", "", "Nenhuma meta com valor na aba metas."])
    else:
        linhas.append([SECAO_RESUMO, ITEM_META, _reais(meta), _reais(meta), texto_da_meta])
        linhas.append(
            [
                SECAO_RESUMO,
                ITEM_META_NO_CAMINHO,
                "sim" if sobra_segura >= meta else "não",
                "sim" if sobra_provavel >= meta else "não",
                "Sobra prevista maior ou igual à meta.",
            ]
        )

    linhas += _linhas_por_categoria(do_mes, da_base, projetar)
    linhas += _linhas_de_movimento_interno(do_mes)
    linhas_de_parcelas = _linhas_de_parcelas(dados, periodo)
    linhas += linhas_de_parcelas
    linhas += _linhas_de_contas_fixas(contas_fixas, periodo, linhas_de_parcelas)
    return linhas


def _linha_da_fatura(
    dados: pd.DataFrame, da_base: pd.DataFrame, periodo: Periodo, ultima_fatura: Fatura | None
) -> LinhaDerivada:
    """A fatura aberta do cartão: o que já entrou nela e quanto deve fechar.

    Com as datas da última fatura, o ciclo é o real: do último fechamento ao
    próximo. As parcelas caem no dia do fechamento, ou seja, já no começo do
    ciclo; por isso o que falta projetar são só as compras à vista.
    """
    cartao = dados[dados["conta"] == CARTAO_DE_CREDITO]
    base = da_base[da_base["conta"] == CARTAO_DE_CREDITO]

    if ultima_fatura is None:
        inicio = periodo.inicio_do_mes
        dias_ate_fechar = periodo.dias_restantes
        base_diaria = base
        ciclo = (
            "Datas da fatura indisponíveis: aproximação pelo mês do calendário, "
            "com a média diária de todos os gastos no cartão."
        )
    else:
        inicio = pd.Timestamp(ultima_fatura.fechamento)
        vencimento = pd.Timestamp(ultima_fatura.vencimento)
        um_mes = pd.DateOffset(months=1)
        while inicio + um_mes <= periodo.hoje:  # a lista de faturas pode estar atrasada
            inicio, vencimento = inicio + um_mes, vencimento + um_mes
        fechamento = inicio + um_mes
        dias_ate_fechar = max((fechamento - periodo.hoje).days - 1, 0)
        base_diaria = base[base["parcela"].isna()]
        ciclo = (
            f"Compras de {inicio:%d/%m/%Y} até hoje. Fecha em {fechamento:%d/%m/%Y} e vence por "
            f"volta de {vencimento + um_mes:%d/%m/%Y}. Projetado = o que já entrou + média diária "
            f"das compras à vista no cartão × {dias_ate_fechar} dias até o fechamento."
        )

    aberta = float(cartao.loc[(cartao["data"] >= inicio) & (cartao["data"] <= periodo.hoje), "gasto"].sum())
    media_diaria = float(base_diaria["gasto"].sum()) / periodo.dias_de_base if periodo.dias_de_base else 0.0
    return [
        SECAO_RESUMO,
        ITEM_FATURA,
        _reais(aberta),
        _reais(aberta + media_diaria * dias_ate_fechar),
        ciclo,
    ]


def _linhas_por_categoria(
    do_mes: pd.DataFrame, da_base: pd.DataFrame, projetar: Callable[[float, float], float]
) -> list[LinhaDerivada]:
    """Gasto até hoje e projetado de cada categoria, da maior projeção para a menor."""
    ate_hoje = do_mes[~do_mes["interno"]].groupby("categoria")["gasto"].sum()
    base = da_base[~da_base["interno"]].groupby("categoria")["gasto"].sum()
    categorias = sorted(set(ate_hoje.index) | set(base.index))
    valores = [
        (
            str(categoria),
            float(ate_hoje.get(categoria, 0.0)),
            projetar(float(ate_hoje.get(categoria, 0.0)), float(base.get(categoria, 0.0))),
        )
        for categoria in categorias
    ]
    return [
        [SECAO_CATEGORIAS, categoria, _reais(gasto), _reais(projetado), ""]
        for categoria, gasto, projetado in sorted(valores, key=lambda v: (-v[2], v[0]))
        if gasto or projetado
    ]


def _linhas_de_movimento_interno(do_mes: pd.DataFrame) -> list[LinhaDerivada]:
    """Quanto saiu no mês em movimentos internos, só para conferência."""
    saidas = do_mes[do_mes["interno"] & (do_mes["tipo"] == TIPO_DEBITO)]
    totais = (-saidas["valor"]).groupby(saidas["categoria"]).sum()
    return [
        [
            SECAO_INTERNOS,
            str(categoria),
            _reais(float(total)),
            "",
            "Saídas do mês. Não entra em gasto nem em renda.",
        ]
        for categoria, total in totais.sort_index().items()
    ]


def _linhas_de_parcelas(dados: pd.DataFrame, periodo: Periodo) -> list[LinhaDerivada]:
    """Parcelas do cartão que ainda vão cair, por compra e somadas por mês.

    As parcelas de uma mesma compra são reconhecidas pela descrição (sem o trecho
    "2/12") e pelo total de parcelas. Vale a parcela mais recente de cada compra.
    """
    parceladas = dados[
        dados["parcela"].notna() & dados["total_parcelas"].notna() & (dados["tipo"] == TIPO_DEBITO)
    ]
    if parceladas.empty:
        return []
    parceladas = parceladas.assign(
        compra=parceladas["descricao"].map(
            lambda descricao: _PADRAO_DE_PARCELA.sub(" ", str(descricao)).strip()
        )
    )
    ultimas = parceladas.sort_values("parcela").groupby(["compra", "total_parcelas"]).tail(1)

    linhas: list[LinhaDerivada] = []
    por_mes: dict[pd.Period, float] = {}
    mes_atual = periodo.hoje.to_period("M")
    ultimas = ultimas.sort_values("compra")
    colunas = zip(
        ultimas["compra"].astype(str),
        ultimas["parcela"].astype(int),
        ultimas["total_parcelas"].astype(int),
        ultimas["data"].dt.to_period("M"),
        (-ultimas["valor"]).astype(float),
        strict=True,
    )
    for compra, parcela, total, mes_da_ultima, valor in colunas:
        futuras = [
            mes
            for mes in (mes_da_ultima + passo for passo in range(1, total - parcela + 1))
            if mes > mes_atual
        ]
        if not futuras:
            continue
        for mes in futuras:
            por_mes[mes] = por_mes.get(mes, 0.0) + valor
        linhas.append(
            [
                SECAO_PARCELAS,
                compra,
                _reais(valor),
                len(futuras),
                f"Valor da parcela e quantas faltam. Última vista: {parcela} de {total}. "
                f"Termina em {futuras[-1]:%m/%Y}.",
            ]
        )
    linhas += [
        [SECAO_PARCELAS_POR_MES, str(mes), _reais(total), "", "Soma das parcelas futuras no mês."]
        for mes, total in sorted(por_mes.items())
    ]
    return linhas


def _linhas_de_contas_fixas(
    contas_fixas: pd.DataFrame, periodo: Periodo, linhas_de_parcelas: Sequence[LinhaDerivada]
) -> list[LinhaDerivada]:
    """Contas da aba `contas_fixas`, com quantas parcelas faltam hoje e quando terminam.

    Com o mês de referência preenchido, as parcelas restantes são descontadas
    sozinhas a cada mês. Sem ele, vale o número digitado, que precisa ser mantido à mão.
    """
    mes_atual = periodo.hoje.to_period("M")
    # valor da parcela -> nome da compra, das parcelas que o script já detecta no cartão
    detectadas = {
        linha[2]: str(linha[1]) for linha in linhas_de_parcelas if linha[0] == SECAO_PARCELAS
    }
    linhas: list[LinhaDerivada] = []
    for conta in contas_fixas.itertuples(index=False):
        valor = _numero(conta.valor_estimado)
        digitadas = _numero(conta.parcelas_restantes)
        vencimento = _numero(conta.dia_vencimento)
        referencia = conta.referencia if isinstance(conta.referencia, pd.Period) else None

        restantes: int | None
        if digitadas is None:
            restantes = None
            situacao = "Recorrente, sem fim."
        elif referencia is None:
            restantes = int(digitadas)
            situacao = (
                f"Termina em {mes_atual + restantes:%m/%Y}, se o número de parcelas restantes "
                "estiver em dia. Preencha a coluna referencia (mm/aaaa) para o desconto "
                "passar a ser automático."
            )
        else:
            termino = referencia + int(digitadas)
            restantes = max((termino - mes_atual).n, 0)
            situacao = (
                f"Terminou em {termino:%m/%Y}. A linha pode ser apagada da aba contas_fixas."
                if restantes == 0
                else f"Termina em {termino:%m/%Y}. Eram {int(digitadas)} parcelas em "
                f"{referencia:%m/%Y}; o desconto mensal é automático."
            )

        partes = [situacao]
        partes.append(
            "Sem dia fixo de vencimento." if vencimento is None else f"Vence no dia {int(vencimento)}."
        )
        if valor is not None and restantes and _reais(valor) in detectadas:
            partes.append(
                f'Parece ser a mesma compra de "{detectadas[_reais(valor)]}" em Parcela futura.'
            )
        linhas.append(
            [
                SECAO_CONTAS_FIXAS,
                str(conta.nome),
                "" if valor is None else _reais(valor),
                "" if restantes is None else restantes,
                " ".join(partes),
            ]
        )
    return linhas


def _meta_de_economia(metas: pd.DataFrame) -> tuple[float | None, str]:
    """A primeira linha da aba `metas` que tem valor numérico."""
    for meta in metas.itertuples(index=False):
        valor = _numero(meta.valor_alvo)
        if valor is not None:
            return valor, str(meta.meta)
    return None, ""


def _numero(celula: object) -> float | None:
    """O valor da célula como número, ou None se estiver vazia ou tiver texto."""
    if isinstance(celula, bool) or not isinstance(celula, Real):
        return None
    return float(celula)


def _reais(valor: float) -> float:
    return round(valor, 2)
