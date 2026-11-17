"""Leitura e escrita na planilha do Google Sheets.

A lógica (conferir cabeçalho, não duplicar, converter números e datas) trabalha
sobre um "armazenamento" simples, que tem duas versões: a do Google, usada com os
dados reais, e uma em memória, usada nos testes e no modo demo.

Regras de escrita na aba `transacoes`: só acrescentar linhas novas. Nada é
apagado nem reescrito.
"""

from __future__ import annotations

import re

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Protocol

import google.auth
import gspread
import pandas as pd
from google.auth.exceptions import GoogleAuthError
from gspread.utils import DateTimeOption, InsertDataOption, ValueInputOption, ValueRenderOption

from bussola.categorias import (
    COLUNAS_DE_CATEGORIA,
    Classificacao,
    ErroRegra,
    normalizar,
    validar_regra,
)
from bussola.limpeza import COLUNAS_PLANILHA

ABA_TRANSACOES = "transacoes"
ABA_REGRAS = "regras"
ABA_CONTAS_FIXAS = "contas_fixas"
ABA_METAS = "metas"
ABA_RESUMO_MENSAL = "resumo_mensal"
ABA_PROJECAO = "projecao"
# Abas calculadas pelo script: são as únicas que ele pode apagar e reescrever.
ABAS_DERIVADAS = frozenset({ABA_RESUMO_MENSAL, ABA_PROJECAO})

# Aba de configuração, gravada pelo aplicativo e lida pelo robô. Uma linha por ajuste.
ABA_CONFIG = "config"
COLUNAS_CONFIG = ["chave", "valor"]
CHAVE_ATUALIZACAO_AUTOMATICA = "atualizacao_automatica"
_SIM, _NAO = "sim", "não"

COLUNAS_REGRAS = ["palavra_chave", "categoria", "prioridade"]
COLUNAS_CONTAS_FIXAS = [
    "nome",
    "valor_estimado",
    "dia_vencimento",
    "categoria",
    "prioridade",
    "parcelas_restantes",
]
# Coluna opcional no fim da aba contas_fixas: o mês (mm/aaaa) em que o número de
# parcelas restantes foi digitado. Com ela, o script desconta os meses que passaram.
COLUNA_REFERENCIA = "referencia"
COLUNAS_METAS = ["meta", "valor_alvo", "prazo", "observacao"]

_MES_E_ANO = re.compile(r"(\d{1,2})/(\d{4})")

_ESCOPO_PLANILHAS = "https://www.googleapis.com/auth/spreadsheets"

# O Google Sheets guarda datas como o número de dias desde 30/12/1899.
_DIA_ZERO = pd.Timestamp("1899-12-30")
_FORMATOS_DE_DATA = {"data": "dd/mm/yyyy", "importado_em": "dd/mm/yyyy hh:mm:ss"}
_COLUNAS_INTEIRAS = {"parcela", "total_parcelas"}

Celula = str | int | float


@dataclass(frozen=True)
class Formula:
    """Uma fórmula da planilha, como "=C2-D2". Só existe nas abas derivadas."""

    texto: str


LinhaDerivada = list[Celula | Formula]


class ErroPlanilha(RuntimeError):
    """Não deu para acessar a planilha, ou ela não está no formato esperado.

    A mensagem nunca inclui o conteúdo das células.
    """


class AbaInexistente(ErroPlanilha):
    """A aba pedida não existe na planilha."""


class Armazenamento(Protocol):
    def ler(self, aba: str) -> list[list[Celula]]:
        """Todas as linhas da aba, cabeçalho incluído, com os valores sem formatação."""
        ...

    def acrescentar(self, aba: str, linhas: Sequence[Sequence[Celula]]) -> None:
        """Acrescenta linhas no fim da aba, gravando os valores literalmente."""
        ...

    def atualizar(
        self, aba: str, primeira_coluna: int, linhas: Mapping[int, Sequence[Celula]]
    ) -> None:
        """Troca células de linhas existentes, gravando os valores literalmente.

        `linhas` leva do número da linha na planilha (o cabeçalho é a linha 1) aos
        valores, gravados a partir de `primeira_coluna` (contada a partir de 0).
        """
        ...

    def formatar_como_data(self, aba: str, coluna: int, padrao: str) -> None:
        """Mostra os números da coluna (contada a partir de 0) como data."""
        ...

    def remover_linha(self, aba: str, numero: int) -> None:
        """Apaga a linha `numero` da aba (o cabeçalho é a linha 1). As de baixo sobem."""
        ...

    def reescrever(self, aba: str, linhas: Sequence[Sequence[Celula | Formula]]) -> None:
        """Apaga a aba (criando-a se não existir) e grava as linhas a partir de A1.

        Valores são gravados literalmente; só as células `Formula` são interpretadas.
        """
        ...


class ArmazenamentoMemoria:
    """Planilha de mentira, guardada na memória. Usada nos testes e no modo demo."""

    def __init__(self, abas: dict[str, list[list[Celula]]]) -> None:
        self.abas = abas
        self.derivadas: dict[str, list[LinhaDerivada]] = {}

    def ler(self, aba: str) -> list[list[Celula]]:
        if aba in self.abas:
            return [list(linha) for linha in self.abas[aba]]
        if aba in self.derivadas:
            # Como no Google, quem lê recebe valores; a fórmula fica só como texto.
            return [
                [celula.texto if isinstance(celula, Formula) else celula for celula in linha]
                for linha in self.derivadas[aba]
            ]
        raise AbaInexistente(f'A aba "{aba}" não existe na planilha.')

    def acrescentar(self, aba: str, linhas: Sequence[Sequence[Celula]]) -> None:
        self.abas[aba].extend(list(linha) for linha in linhas)

    def atualizar(
        self, aba: str, primeira_coluna: int, linhas: Mapping[int, Sequence[Celula]]
    ) -> None:
        for numero, valores in linhas.items():
            linha = self.abas[aba][numero - 1]
            linha[primeira_coluna : primeira_coluna + len(valores)] = valores

    def formatar_como_data(self, aba: str, coluna: int, padrao: str) -> None:
        pass  # formatação é só aparência; não há o que guardar em memória

    def remover_linha(self, aba: str, numero: int) -> None:
        del self.abas[aba][numero - 1]

    def reescrever(self, aba: str, linhas: Sequence[Sequence[Celula | Formula]]) -> None:
        self.derivadas[aba] = [list(linha) for linha in linhas]


class ArmazenamentoGoogle:
    def __init__(self, planilha: gspread.Spreadsheet) -> None:
        self._planilha = planilha

    def ler(self, aba: str) -> list[list[Celula]]:
        try:
            return self._aba(aba).get_values(
                value_render_option=ValueRenderOption.unformatted,
                date_time_render_option=DateTimeOption.serial_number,
            )
        except gspread.exceptions.APIError as erro:
            raise _erro_da_api(erro, f'ler a aba "{aba}"') from None

    def acrescentar(self, aba: str, linhas: Sequence[Sequence[Celula]]) -> None:
        try:
            # "raw": o valor é gravado como veio. Um texto começando com "=" ou "+"
            # continua sendo texto, nunca vira fórmula.
            self._aba(aba).append_rows(
                [list(linha) for linha in linhas],
                value_input_option=ValueInputOption.raw,
                insert_data_option=InsertDataOption.insert_rows,
                table_range="A1",
            )
        except gspread.exceptions.APIError as erro:
            raise _erro_da_api(erro, f'gravar na aba "{aba}"') from None

    def atualizar(
        self, aba: str, primeira_coluna: int, linhas: Mapping[int, Sequence[Celula]]
    ) -> None:
        intervalos = [
            {
                "range": letra_da_coluna(primeira_coluna)
                + f"{numero}:"
                + letra_da_coluna(primeira_coluna + len(valores) - 1)
                + str(numero),
                "values": [list(valores)],
            }
            for numero, valores in linhas.items()
        ]
        try:
            self._aba(aba).batch_update(intervalos, value_input_option=ValueInputOption.raw)
        except gspread.exceptions.APIError as erro:
            raise _erro_da_api(erro, f'atualizar a aba "{aba}"') from None

    def formatar_como_data(self, aba: str, coluna: int, padrao: str) -> None:
        letra = letra_da_coluna(coluna)
        tipo = "DATE_TIME" if "hh" in padrao else "DATE"
        try:
            self._aba(aba).format(
                f"{letra}2:{letra}", {"numberFormat": {"type": tipo, "pattern": padrao}}
            )
        except gspread.exceptions.APIError as erro:
            raise _erro_da_api(erro, f'formatar a aba "{aba}"') from None

    def remover_linha(self, aba: str, numero: int) -> None:
        try:
            self._aba(aba).delete_rows(numero)
        except gspread.exceptions.APIError as erro:
            raise _erro_da_api(erro, f'apagar uma linha da aba "{aba}"') from None

    def reescrever(self, aba: str, linhas: Sequence[Sequence[Celula | Formula]]) -> None:
        largura = max((len(linha) for linha in linhas), default=1)
        valores = [
            ["" if isinstance(celula, Formula) else celula for celula in linha] for linha in linhas
        ]
        formulas = [
            {"range": f"{letra_da_coluna(coluna)}{numero}", "values": [[celula.texto]]}
            for numero, linha in enumerate(linhas, start=1)
            for coluna, celula in enumerate(linha)
            if isinstance(celula, Formula)
        ]
        try:
            try:
                folha = self._planilha.worksheet(aba)
            except gspread.exceptions.WorksheetNotFound:
                folha = self._planilha.add_worksheet(aba, rows=max(len(linhas), 1), cols=largura)
            folha.clear()
            if valores:
                # Textos vindos das transações entram como texto puro ("raw")...
                folha.update(valores, "A1", value_input_option=ValueInputOption.raw)
            if formulas:
                # ...e só as fórmulas montadas pelo script são interpretadas.
                folha.batch_update(formulas, value_input_option=ValueInputOption.user_entered)
        except gspread.exceptions.APIError as erro:
            raise _erro_da_api(erro, f'reescrever a aba "{aba}"') from None

    def _aba(self, aba: str) -> gspread.Worksheet:
        try:
            return self._planilha.worksheet(aba)
        except gspread.exceptions.WorksheetNotFound:
            raise AbaInexistente(f'A aba "{aba}" não existe na planilha.') from None


def conectar(sheet_id: str) -> ArmazenamentoGoogle:
    """Abre a planilha com a credencial do ambiente (sem arquivo de chave).

    No computador é a credencial do gcloud com impersonação da conta de serviço;
    no GitHub Actions, a identidade federada do workflow.
    """
    try:
        credencial, _ = google.auth.default(scopes=[_ESCOPO_PLANILHAS])
        return ArmazenamentoGoogle(gspread.authorize(credencial).open_by_key(sheet_id))
    except GoogleAuthError:
        raise ErroPlanilha(
            "Credencial do Google não encontrada ou recusada. No computador, rode de novo: "
            "gcloud auth application-default login "
            "--impersonate-service-account=<e-mail da conta de serviço>"
        ) from None
    except (gspread.exceptions.SpreadsheetNotFound, PermissionError):
        raise ErroPlanilha(
            "Planilha não encontrada ou sem permissão. Confira o SHEET_ID e se ela está "
            "compartilhada com a conta de serviço como Editor."
        ) from None
    except gspread.exceptions.APIError as erro:
        raise _erro_da_api(erro, "abrir a planilha") from None


def ler_tabela(
    armazenamento: Armazenamento,
    aba: str,
    colunas: Sequence[str],
    opcionais: Sequence[str] = (),
) -> pd.DataFrame:
    """Lê uma aba como tabela, conferindo se o cabeçalho é o esperado.

    `opcionais` são colunas que podem existir depois das obrigatórias. A tabela
    devolvida sempre as tem; se a aba não as tiver, vêm vazias.
    """
    linhas = armazenamento.ler(aba)
    todas = [*colunas, *opcionais]
    cabecalho = [str(celula).strip() for celula in linhas[0]] if linhas else []
    if cabecalho not in (list(colunas), todas):
        raise ErroPlanilha(
            f'O cabeçalho da aba "{aba}" não é o esperado ({", ".join(todas)}). '
            "Nada foi gravado."
        )
    largura = len(cabecalho)
    # O Google omite as células vazias do fim da linha; aqui elas voltam como "".
    dados = [(list(linha) + [""] * len(todas))[:largura] + [""] * (len(todas) - largura) for linha in linhas[1:]]
    return pd.DataFrame(dados, columns=todas)


def acrescentar_regra(
    armazenamento: Armazenamento, palavra_chave: str, categoria: str, prioridade: str
) -> None:
    """Acrescenta uma regra no fim da aba `regras`. As regras existentes não são tocadas.

    Levanta `ErroRegra` se a regra não for válida ou se a palavra-chave já existir.
    """
    existentes = ler_tabela(armazenamento, ABA_REGRAS, COLUNAS_REGRAS)
    armazenamento.acrescentar(
        ABA_REGRAS, [list(validar_regra(palavra_chave, categoria, prioridade, existentes))]
    )


def editar_regra(
    armazenamento: Armazenamento,
    palavra_chave_atual: str,
    palavra_chave: str,
    categoria: str,
    prioridade: str,
) -> None:
    """Troca a palavra-chave, a categoria e a prioridade de uma regra, no mesmo lugar da aba.

    As outras regras não são tocadas. Levanta `ErroRegra` se a regra não for
    encontrada, se a nova versão não for válida ou se repetir outra palavra-chave.
    """
    numero, regras = _linha_da_regra(armazenamento, palavra_chave_atual)
    nova = validar_regra(palavra_chave, categoria, prioridade, regras, editando=palavra_chave_atual)
    armazenamento.atualizar(ABA_REGRAS, 0, {numero: list(nova)})


def apagar_regra(armazenamento: Armazenamento, palavra_chave: str) -> None:
    """Apaga a linha da regra na aba `regras`. As outras regras não são tocadas."""
    numero, _ = _linha_da_regra(armazenamento, palavra_chave)
    armazenamento.remover_linha(ABA_REGRAS, numero)


def _linha_da_regra(armazenamento: Armazenamento, palavra_chave: str) -> tuple[int, pd.DataFrame]:
    """O número da linha da regra na planilha, procurado agora (e não guardado de antes).

    Assim, se a aba tiver sido editada à mão nesse meio-tempo, a linha certa é a alterada.
    """
    regras = ler_tabela(armazenamento, ABA_REGRAS, COLUNAS_REGRAS)
    chave = normalizar(palavra_chave)
    posicoes = [
        posicao
        for posicao, palavra in enumerate(regras["palavra_chave"])
        if chave and normalizar(str(palavra)) == chave
    ]
    if not posicoes:
        raise ErroRegra("A regra não foi encontrada na planilha. Recarregue e tente de novo.")
    if len(posicoes) > 1:
        raise ErroRegra(
            "Há mais de uma regra com essa palavra-chave na planilha. Corrija direto na aba regras."
        )
    return posicoes[0] + 2, regras  # o cabeçalho é a linha 1


def atualizacao_automatica_ligada(armazenamento: Armazenamento) -> bool:
    """Se o robô diário deve rodar. Sem a aba `config` ou sem a linha, vale ligada."""
    try:
        config = ler_tabela(armazenamento, ABA_CONFIG, COLUNAS_CONFIG)
    except AbaInexistente:
        return True
    valores = [
        str(valor).strip().lower()
        for chave, valor in zip(config["chave"], config["valor"], strict=True)
        if str(chave).strip() == CHAVE_ATUALIZACAO_AUTOMATICA
    ]
    if not valores:
        return True
    if valores[-1] in (_SIM, _NAO, "nao"):
        return valores[-1] == _SIM
    raise ErroPlanilha(
        f'Na aba "{ABA_CONFIG}", o valor de {CHAVE_ATUALIZACAO_AUTOMATICA} deve ser sim ou não.'
    )


def definir_atualizacao_automatica(armazenamento: Armazenamento, ligada: bool) -> None:
    """Grava a escolha na aba `config`, criando a aba se ela não existir."""
    armazenamento.reescrever(
        ABA_CONFIG,
        [list(COLUNAS_CONFIG), [CHAVE_ATUALIZACAO_AUTOMATICA, _SIM if ligada else _NAO]],
    )


def ler_contas_fixas(armazenamento: Armazenamento) -> pd.DataFrame:
    """A aba `contas_fixas`, com a coluna `referencia` já convertida em mês (ou None)."""
    tabela = ler_tabela(
        armazenamento, ABA_CONTAS_FIXAS, COLUNAS_CONTAS_FIXAS, opcionais=[COLUNA_REFERENCIA]
    )
    meses = pd.Series(
        [_mes_de_referencia(celula) for celula in tabela[COLUNA_REFERENCIA]],
        index=tabela.index,
        dtype="object",
    )
    return tabela.assign(**{COLUNA_REFERENCIA: meses})


def _mes_de_referencia(celula: object) -> pd.Period | None:
    """Aceita "11/2026" como texto ou uma data da planilha (número de série)."""
    if celula == "":
        return None
    if isinstance(celula, Real) and not isinstance(celula, bool):
        return (_DIA_ZERO + pd.Timedelta(days=float(celula))).to_period("M")
    encontrado = _MES_E_ANO.fullmatch(str(celula).strip())
    if encontrado is None or not 1 <= int(encontrado.group(1)) <= 12:
        raise ErroPlanilha(
            f'Na aba "{ABA_CONTAS_FIXAS}", a coluna "{COLUNA_REFERENCIA}" deve ter o mês '
            "no formato mm/aaaa (por exemplo 11/2026) ou ficar vazia."
        )
    return pd.Period(year=int(encontrado.group(2)), month=int(encontrado.group(1)), freq="M")


def ler_transacoes(armazenamento: Armazenamento) -> pd.DataFrame:
    """A aba `transacoes` como está gravada, com data, valor e parcelas já convertidos.

    A linha de posição 0 é a linha 2 da planilha.
    """
    tabela = ler_tabela(armazenamento, ABA_TRANSACOES, COLUNAS_PLANILHA)
    try:
        return tabela.assign(
            id=tabela["id"].astype(str),
            data=_DIA_ZERO + pd.to_timedelta(pd.to_numeric(tabela["data"]), unit="D"),
            valor=pd.to_numeric(tabela["valor"]).astype("float64"),
            parcela=_inteiros_ou_vazio(tabela["parcela"]),
            total_parcelas=_inteiros_ou_vazio(tabela["total_parcelas"]),
        )
    except (ValueError, TypeError):
        raise ErroPlanilha(
            'Há linhas na aba "transacoes" em que data, valor ou parcela não são números. '
            "Corrija na planilha e rode de novo."
        ) from None


def _inteiros_ou_vazio(coluna: pd.Series) -> pd.Series:
    return pd.to_numeric(coluna.replace("", pd.NA)).astype("Int64")


def reescrever_derivada(
    armazenamento: Armazenamento, aba: str, linhas: Sequence[Sequence[Celula | Formula]]
) -> None:
    """Reescreve uma aba calculada. Recusa qualquer aba editada à mão."""
    if aba not in ABAS_DERIVADAS:
        raise ErroPlanilha(f'A aba "{aba}" não é uma aba calculada e não pode ser reescrita.')
    armazenamento.reescrever(aba, linhas)


def aplicar_recategorizacao(
    armazenamento: Armazenamento, mudancas: Mapping[int, Classificacao]
) -> None:
    """Grava as mudanças de categoria em linhas existentes.

    Só as três colunas de categoria são tocadas. As chaves são posições na
    tabela devolvida por `ler_transacoes`.
    """
    if not mudancas:
        return
    armazenamento.atualizar(
        ABA_TRANSACOES,
        COLUNAS_PLANILHA.index(COLUNAS_DE_CATEGORIA[0]),
        {posicao + 2: nova.celulas() for posicao, nova in mudancas.items()},
    )


def gravar_novas(
    armazenamento: Armazenamento, tabela: pd.DataFrame, ja_gravados: set[str]
) -> pd.DataFrame:
    """Acrescenta à aba `transacoes` as linhas cujo id ainda não está lá.

    Devolve as linhas que foram gravadas.
    """
    novas = tabela[~tabela["id"].isin(ja_gravados)].drop_duplicates(subset="id")
    if novas.empty:
        return novas
    armazenamento.acrescentar(ABA_TRANSACOES, _para_celulas(novas))
    for nome, padrao in _FORMATOS_DE_DATA.items():
        armazenamento.formatar_como_data(ABA_TRANSACOES, COLUNAS_PLANILHA.index(nome), padrao)
    return novas


def _para_celulas(tabela: pd.DataFrame) -> list[list[Celula]]:
    """Converte a tabela para os valores que a planilha entende, na ordem das colunas."""
    return [
        [_celula(nome, valor) for nome, valor in zip(COLUNAS_PLANILHA, linha, strict=True)]
        for linha in tabela[COLUNAS_PLANILHA].itertuples(index=False, name=None)
    ]


def _celula(coluna: str, valor: object) -> Celula:
    if valor is None or valor is pd.NA or valor is pd.NaT or valor != valor:  # vazio ou NaN
        return ""
    if isinstance(valor, pd.Timestamp):
        dias = (valor - _DIA_ZERO) / pd.Timedelta(days=1)
        return int(dias) if coluna == "data" else float(dias)
    # Integral e Real cobrem também os números do pandas/numpy, não só int e float.
    if coluna in _COLUNAS_INTEIRAS and isinstance(valor, Integral):
        return int(valor)
    if isinstance(valor, Real):
        return float(valor)
    return str(valor)


def letra_da_coluna(coluna: int) -> str:
    """Letra da coluna na planilha: 0 vira "A", 1 vira "B"..."""
    return gspread.utils.rowcol_to_a1(1, coluna + 1).rstrip("1")


def _erro_da_api(erro: gspread.exceptions.APIError, acao: str) -> ErroPlanilha:
    return ErroPlanilha(f"O Google respondeu com erro {erro.code} ao {acao}.")
