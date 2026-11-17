"""Categorização das transações pelas regras da aba `regras`.

Ordem de decisão para cada transação:
1. regra da planilha (`regra`): a palavra-chave está contida na descrição,
   ignorando maiúsculas, acentos e espaços; se várias casarem, vence a mais longa;
2. categoria sugerida pela Pluggy (`pluggy`), quando existe;
3. "Sem categoria" (`sem_regra`).

Linhas já gravadas são reavaliadas a cada atualização, para acompanhar as regras
atuais: uma regra editada ou apagada vale também para as transações antigas.
Só as linhas `manual` (decisão de quem usa) nunca mudam.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from bussola.limpeza import COLUNA_CATEGORIA_PLUGGY

SEM_CATEGORIA = "Sem categoria"

REGRA = "regra"
PLUGGY = "pluggy"
MANUAL = "manual"
SEM_REGRA = "sem_regra"

# Linhas que nenhuma regra cobre: aparecem nas sugestões de regra nova.
_SEM_REGRA_DA_PLANILHA = {SEM_REGRA, PLUGGY}
# Linhas reavaliadas a cada atualização. `manual` fica de fora: é decisão de quem usa.
_REAVALIADAS = {SEM_REGRA, PLUGGY, REGRA}

COLUNAS_DE_CATEGORIA = ["categoria", "prioridade", "categorizado_por"]

PRIORIDADES = ("Essencial", "Importante", "Supérfluo")


class ErroRegra(ValueError):
    """A regra que se tentou criar não é válida. A mensagem diz o que corrigir."""


@dataclass(frozen=True)
class Regra:
    palavra_chave: str  # já normalizada
    categoria: str
    prioridade: str


@dataclass(frozen=True)
class Classificacao:
    categoria: str
    prioridade: str
    categorizado_por: str

    def celulas(self) -> tuple[str, str, str]:
        """Os valores na ordem das colunas da planilha."""
        return (self.categoria, self.prioridade, self.categorizado_por)


def normalizar(texto: str) -> str:
    """Tira acentos, espaços e diferença de maiúsculas: "Pão Quente" vira "paoquente"."""
    sem_acentos = "".join(
        letra
        for letra in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(letra)
    )
    return "".join(sem_acentos.casefold().split())


def montar_regras(tabela_de_regras: pd.DataFrame) -> list[Regra]:
    """Lê as regras da aba `regras`, da palavra-chave mais longa para a mais curta.

    Linhas sem palavra-chave são ignoradas. No empate de tamanho, fica na frente
    a regra que está mais acima na planilha (a ordenação preserva a ordem original).
    """
    regras = [
        Regra(
            palavra_chave=normalizar(str(linha.palavra_chave)),
            categoria=str(linha.categoria).strip(),
            prioridade=str(linha.prioridade).strip(),
        )
        for linha in tabela_de_regras.itertuples(index=False)
    ]
    validas = [regra for regra in regras if regra.palavra_chave]
    return sorted(validas, key=lambda regra: len(regra.palavra_chave), reverse=True)


def regra_que_casa(descricao: str, regras: Sequence[Regra]) -> Regra | None:
    """A primeira regra cuja palavra-chave está contida na descrição."""
    descricao_normalizada = normalizar(descricao)
    for regra in regras:
        if regra.palavra_chave in descricao_normalizada:
            return regra
    return None


def classificar(
    descricao: str, categoria_pluggy: str | None, regras: Sequence[Regra]
) -> Classificacao:
    regra = regra_que_casa(descricao, regras)
    if regra is not None:
        return Classificacao(regra.categoria, regra.prioridade, REGRA)
    if categoria_pluggy:
        return Classificacao(categoria_pluggy, "", PLUGGY)
    return Classificacao(SEM_CATEGORIA, "", SEM_REGRA)


def categorizar(tabela: pd.DataFrame, regras: Sequence[Regra]) -> pd.DataFrame:
    """Preenche categoria, prioridade e categorizado_por das transações novas."""
    classificacoes = [
        classificar(str(descricao), None if pd.isna(categoria_pluggy) else str(categoria_pluggy), regras)
        for descricao, categoria_pluggy in zip(
            tabela["descricao"], tabela[COLUNA_CATEGORIA_PLUGGY], strict=True
        )
    ]
    return tabela.assign(
        categoria=[c.categoria for c in classificacoes],
        prioridade=[c.prioridade for c in classificacoes],
        categorizado_por=[c.categorizado_por for c in classificacoes],
    )


def recategorizar(
    gravadas: pd.DataFrame,
    regras: Sequence[Regra],
    categorias_pluggy: Mapping[str, str],
    traducoes: Mapping[str, str],
) -> dict[int, Classificacao]:
    """Decide o que muda nas linhas já gravadas na planilha.

    `gravadas` é a aba `transacoes` como foi lida; `categorias_pluggy` leva do id
    da transação à categoria da Pluggy, para as transações em que ela é conhecida;
    `traducoes` leva do nome da categoria em inglês ao nome em português.
    Devolve só as linhas que mudam, pela posição na tabela (0 = primeira linha de dados).
    """
    mudancas: dict[int, Classificacao] = {}
    for posicao, linha in enumerate(gravadas.itertuples(index=False)):
        atual = Classificacao(str(linha.categoria), str(linha.prioridade), str(linha.categorizado_por))
        if atual.categorizado_por not in _REAVALIADAS:
            continue
        nova = _reavaliar(atual, str(linha.descricao), categorias_pluggy.get(str(linha.id)), regras, traducoes)
        if nova != atual:
            mudancas[posicao] = nova
    return mudancas


def _reavaliar(
    atual: Classificacao,
    descricao: str,
    categoria_pluggy: str | None,
    regras: Sequence[Regra],
    traducoes: Mapping[str, str],
) -> Classificacao:
    regra = regra_que_casa(descricao, regras)
    if regra is not None:
        return Classificacao(regra.categoria, regra.prioridade, REGRA)
    if atual.categorizado_por == PLUGGY:
        # Sem regra nova, a linha continua da Pluggy; só o nome passa para português.
        return Classificacao(traducoes.get(atual.categoria, atual.categoria), atual.prioridade, PLUGGY)
    if categoria_pluggy:
        return Classificacao(categoria_pluggy, "", PLUGGY)
    if atual.categorizado_por == REGRA:
        # A regra que cobria a linha foi editada ou apagada, e a Pluggy não tem sugestão.
        return Classificacao(SEM_CATEGORIA, "", SEM_REGRA)
    return atual


def precisam_da_pluggy(gravadas: pd.DataFrame, regras: Sequence[Regra]) -> set[str]:
    """Ids das linhas gravadas que podem precisar da categoria sugerida pela Pluggy.

    São as ainda sem categoria e as categorizadas por uma regra que deixou de
    cobri-las (regra editada ou apagada). A sugestão da Pluggy não fica guardada
    na planilha, então é pedida de novo pelo id.
    """
    return {
        str(identificador)
        for identificador, descricao, origem in zip(
            gravadas["id"], gravadas["descricao"], gravadas["categorizado_por"], strict=True
        )
        if origem == SEM_REGRA or (origem == REGRA and regra_que_casa(str(descricao), regras) is None)
    }


def linhas_sem_regra(tabela: pd.DataFrame) -> pd.DataFrame:
    """As transações que nenhuma regra cobre: categorizadas pela Pluggy ou sem categoria."""
    return tabela[tabela["categorizado_por"].isin(_SEM_REGRA_DA_PLANILHA)]


def descricoes_sem_regra(tabela: pd.DataFrame, quantas: int) -> pd.DataFrame:
    """As descrições mais frequentes que nenhuma regra cobre, para criar regras novas.

    Considera as linhas `sem_regra` e `pluggy`. Colunas: descricao, vezes, categoria_atual.
    """
    resumo = (
        linhas_sem_regra(tabela).groupby("descricao", sort=False)
        .agg(vezes=("descricao", "size"), categoria_atual=("categoria", "first"))
        .reset_index()
        .sort_values(["vezes", "descricao"], ascending=[False, True], kind="stable")
    )
    return resumo.head(quantas).reset_index(drop=True)


def validar_regra(
    palavra_chave: str,
    categoria: str,
    prioridade: str,
    tabela_de_regras: pd.DataFrame,
    editando: str | None = None,
) -> tuple[str, str, str]:
    """Confere uma regra e a devolve sem espaços sobrando. Prioridade vazia é aceita.

    `editando` é a palavra-chave atual da regra que está sendo editada: ela não
    conta como repetida.
    """
    palavra_chave, categoria, prioridade = palavra_chave.strip(), categoria.strip(), prioridade.strip()
    if not normalizar(palavra_chave):
        raise ErroRegra("Escreva a palavra-chave da regra.")
    if not categoria:
        raise ErroRegra("Escolha ou escreva a categoria da regra.")
    if prioridade and prioridade not in PRIORIDADES:
        raise ErroRegra(f"A prioridade deve ser {', '.join(PRIORIDADES)} ou ficar vazia.")
    existentes = {normalizar(str(palavra)) for palavra in tabela_de_regras["palavra_chave"]}
    if editando is not None:
        existentes.discard(normalizar(editando))
    if normalizar(palavra_chave) in existentes:
        raise ErroRegra(
            f'Já existe uma regra com a palavra-chave "{palavra_chave}". '
            "Para mudá-la, use “Editar uma regra”."
        )
    return palavra_chave, categoria, prioridade


def cobertura_das_regras(tabela_de_regras: pd.DataFrame, transacoes: pd.DataFrame) -> pd.DataFrame:
    """As regras como estão na planilha, com quantas transações cada uma cobre hoje.

    Uma transação conta para a regra que vence nela (a de palavra-chave mais longa).
    """
    regras = montar_regras(tabela_de_regras)
    vencedoras = [regra_que_casa(str(descricao), regras) for descricao in transacoes["descricao"]]
    contagem: dict[str, int] = {}
    for regra in vencedoras:
        if regra is not None:
            contagem[regra.palavra_chave] = contagem.get(regra.palavra_chave, 0) + 1
    tem_palavra_chave = pd.Series(
        [bool(normalizar(str(palavra))) for palavra in tabela_de_regras["palavra_chave"]],
        index=tabela_de_regras.index,
        dtype=bool,  # com a aba vazia, uma lista sem tipo seria lida como "nenhuma coluna"
    )
    validas = tabela_de_regras.loc[tem_palavra_chave]
    return pd.DataFrame(
        {
            "palavra_chave": validas["palavra_chave"].astype(str).tolist(),
            "categoria": validas["categoria"].astype(str).tolist(),
            "prioridade": validas["prioridade"].astype(str).tolist(),
            "cobre": [contagem.get(normalizar(str(p)), 0) for p in validas["palavra_chave"]],
        }
    )


@dataclass(frozen=True)
class PreviaDaRegra:
    """O que aconteceria com as transações atuais se a palavra-chave virasse regra."""

    encontradas: int  # transações cuja descrição contém a palavra-chave
    mudariam: int  # as que hoje estão sem regra (categoria da Pluggy ou sem categoria)
    manuais: int  # marcadas à mão: nunca mudam
    ja_com_regra: int  # já categorizadas por outra regra: não mudam


def previa_da_regra(palavra_chave: str, transacoes: pd.DataFrame) -> PreviaDaRegra:
    chave = normalizar(palavra_chave)
    if not chave:
        return PreviaDaRegra(0, 0, 0, 0)
    contem = transacoes[transacoes["descricao"].map(lambda descricao: chave in normalizar(str(descricao)))]
    return PreviaDaRegra(
        encontradas=len(contem),
        mudariam=len(linhas_sem_regra(contem)),
        manuais=int((contem["categorizado_por"] == MANUAL).sum()),
        ja_com_regra=int((contem["categorizado_por"] == REGRA).sum()),
    )
