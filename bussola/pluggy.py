"""Cliente somente leitura da API da Pluggy.

Faz três coisas: pede a chave de acesso, lista as contas de um item e busca as
transações de uma conta. Não existe aqui nenhuma chamada que movimente dinheiro.

Referência: https://docs.pluggy.ai (conferida em 12/11/2026).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from itertools import batched
from typing import Any, Protocol
from urllib.parse import parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL_BASE = "https://api.pluggy.ai"
TEMPO_LIMITE_SEGUNDOS = 30
# A lista de ids vai no endereço da chamada; lotes pequenos evitam endereços longos demais.
IDS_POR_CHAMADA = 100

# Saúde da conexão com o banco (o "item" da Pluggy).
_STATUS_SAUDAVEIS = frozenset({"UPDATED", "UPDATING"})
# A Pluggy sincroniza sozinha todo dia; mais do que isso sem sincronizar é sinal de problema.
DIAS_SEM_SINCRONIZAR = 3
DIAS_DE_AVISO_DO_CONSENTIMENTO = 30

registro = logging.getLogger("bussola")


class ErroPluggy(RuntimeError):
    """A API da Pluggy respondeu com erro ou com um formato inesperado.

    A mensagem nunca inclui o corpo da resposta, para não vazar dados no log.
    """


@dataclass(frozen=True)
class Conta:
    id: str
    tipo: str  # BANK ou CREDIT
    subtipo: str  # por exemplo CHECKING_ACCOUNT ou CREDIT_CARD


@dataclass(frozen=True)
class Item:
    """A conexão com o banco, como a Pluggy a descreve."""

    status: str
    sincronizado_em: datetime | None
    consentimento_expira_em: datetime | None

    def problemas(self, agora: datetime) -> list[str]:
        """O que impede a conexão de trazer dados novos. Lista vazia = tudo certo."""
        problemas = []
        if self.status not in _STATUS_SAUDAVEIS:
            problemas.append(
                f"A conexão com o banco está com status {self.status}. "
                "Abra meu.pluggy.ai e reconecte a conta."
            )
        if self.consentimento_expira_em is not None and self.consentimento_expira_em <= agora:
            problemas.append(
                "O consentimento do Open Finance expirou. Abra meu.pluggy.ai e renove a conexão."
            )
        limite = agora - timedelta(days=DIAS_SEM_SINCRONIZAR)
        if self.sincronizado_em is None or self.sincronizado_em < limite:
            problemas.append(
                f"A Pluggy não sincroniza com o banco há mais de {DIAS_SEM_SINCRONIZAR} dias: "
                "não há dados novos. Confira a conexão em meu.pluggy.ai."
            )
        return problemas

    def dias_ate_o_consentimento_expirar(self, agora: datetime) -> int | None:
        if self.consentimento_expira_em is None:
            return None
        return (self.consentimento_expira_em - agora).days


@dataclass(frozen=True)
class Fatura:
    """Uma fatura do cartão já fechada."""

    fechamento: date  # compras a partir deste dia já entram na fatura seguinte
    vencimento: date


@dataclass(frozen=True)
class Transacao:
    id: str
    conta_id: str
    data: datetime  # em UTC, como a Pluggy envia
    descricao: str
    valor: float  # sinal original da Pluggy; a padronização é feita na limpeza
    tipo: str  # DEBIT (saída) ou CREDIT (entrada)
    status: str | None  # POSTED ou PENDING
    categoria: str | None
    parcela: int | None
    total_parcelas: int | None


def _criar_sessao() -> requests.Session:
    """Sessão que tenta de novo sozinha quando a API está fora do ar ou pede para esperar."""
    tentativas = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    sessao = requests.Session()
    sessao.mount("https://", HTTPAdapter(max_retries=tentativas))
    return sessao


class ClientePluggy:
    def __init__(
        self, client_id: str, client_secret: str, sessao: requests.Session | None = None
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._sessao = sessao if sessao is not None else _criar_sessao()

    def autenticar(self) -> None:
        """Pede uma chave de acesso nova (vale cerca de 2 horas)."""
        corpo = self._requisitar(
            "POST",
            "/auth",
            corpo={"clientId": self._client_id, "clientSecret": self._client_secret},
        )
        chave = corpo.get("apiKey")
        if not isinstance(chave, str) or not chave:
            raise ErroPluggy("A resposta de /auth veio sem a chave de acesso.")
        self._sessao.headers["X-API-KEY"] = chave

    def listar_contas(self, item_id: str) -> list[Conta]:
        return [_montar_conta(bruta) for bruta in self._pagina_unica("/accounts", {"itemId": item_id})]

    def consultar_item(self, item_id: str) -> Item:
        """Estado da conexão com o banco: status, última sincronização e validade."""
        caminho = "/items/{id}"  # o id não vai para mensagens de erro
        try:
            bruto = self._get(f"/items/{item_id}", {})
        except ErroPluggy as erro:
            raise ErroPluggy(str(erro).replace(f"/items/{item_id}", caminho)) from None
        status = bruto.get("status")
        if not isinstance(status, str):
            raise ErroPluggy(f"Resposta sem o status da conexão em {caminho}.")
        return Item(
            status=status,
            sincronizado_em=_data_ou_nada(bruto.get("lastUpdatedAt")),
            consentimento_expira_em=_data_ou_nada(bruto.get("consentExpiresAt")),
        )

    def listar_faturas(self, conta_id: str) -> list[Fatura]:
        """Faturas fechadas de um cartão, com as datas de fechamento e vencimento."""
        faturas = []
        for bruta in self._pagina_unica("/bills", {"accountId": conta_id}):
            fechamento, vencimento = bruta.get("billClosingDate"), bruta.get("dueDate")
            if isinstance(fechamento, str) and isinstance(vencimento, str):
                try:
                    # São datas sem hora, enviadas como meia-noite UTC: vale o dia como está.
                    faturas.append(
                        Fatura(date.fromisoformat(fechamento[:10]), date.fromisoformat(vencimento[:10]))
                    )
                except ValueError:
                    raise ErroPluggy("Data de fatura em formato inesperado em /bills.") from None
        return faturas

    def listar_traducoes_de_categoria(self) -> dict[str, str]:
        """Tabela oficial da Pluggy: nome da categoria em inglês -> nome em português."""
        traducoes: dict[str, str] = {}
        for bruta in self._pagina_unica("/categories", {}):
            original, traduzida = bruta.get("description"), bruta.get("descriptionTranslated")
            if isinstance(original, str) and isinstance(traduzida, str) and traduzida:
                traducoes[original] = traduzida
        return traducoes

    def _pagina_unica(self, caminho: str, parametros: dict[str, str]) -> list[dict[str, Any]]:
        """Resultados de uma lista que deve caber numa página só; se não couber, para com erro."""
        corpo = self._get(caminho, parametros)
        if corpo.get("totalPages", 1) > 1:
            raise ErroPluggy(f"A lista de {caminho} veio em mais de uma página.")
        return _resultados(corpo, caminho)

    def listar_transacoes(self, conta_id: str, inicio: date, fim: date) -> list[Transacao]:
        """Busca as transações da conta no período, seguindo todas as páginas."""
        return self._paginar(
            {"accountId": conta_id, "dateFrom": inicio.isoformat(), "dateTo": fim.isoformat()}
        )

    def listar_transacoes_por_ids(self, conta_id: str, ids: Collection[str]) -> list[Transacao]:
        """Busca transações específicas da conta, pelos ids."""
        transacoes: list[Transacao] = []
        for lote in batched(sorted(ids), IDS_POR_CHAMADA):
            transacoes += self._paginar({"accountId": conta_id, "ids": ",".join(lote)})
        return transacoes

    def _paginar(self, parametros: dict[str, str]) -> list[Transacao]:
        caminho = "/v2/transactions"
        transacoes: list[Transacao] = []
        cursores_vistos: set[str] = set()
        cursor: str | None = None
        while True:
            pagina = self._get(caminho, parametros | ({"after": cursor} if cursor else {}))
            transacoes.extend(_montar_transacao(bruta) for bruta in _resultados(pagina, caminho))
            cursor = _proximo_cursor(pagina.get("next"))
            if cursor is None:
                return transacoes
            if cursor in cursores_vistos:
                raise ErroPluggy("A paginação de transações entrou em repetição.")
            cursores_vistos.add(cursor)

    def _get(self, caminho: str, parametros: dict[str, str]) -> dict[str, Any]:
        if "X-API-KEY" not in self._sessao.headers:
            raise ErroPluggy("Chame autenticar() antes de buscar dados.")
        return self._requisitar("GET", caminho, parametros=parametros)

    def _requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        parametros: dict[str, str] | None = None,
        corpo: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Único ponto de saída para a API: toda falha vira ErroPluggy, sem dados na mensagem."""
        try:
            resposta = self._sessao.request(
                metodo,
                f"{URL_BASE}{caminho}",
                params=parametros,
                json=corpo,
                timeout=TEMPO_LIMITE_SEGUNDOS,
            )
            return _ler_json(resposta, caminho)
        except requests.RequestException as erro:
            # Rede fora do ar, tempo esgotado, erro repetido do servidor, resposta ilegível...
            raise ErroPluggy(
                f"Falha de comunicação com a Pluggy em {caminho} ({type(erro).__name__})."
            ) from None


class Fonte(Protocol):
    """De onde vêm as transações: a Pluggy ou os dados fictícios do modo demo."""

    @property
    def contas(self) -> list[Conta]: ...

    @property
    def traducoes(self) -> Mapping[str, str]:
        """Nome da categoria como a fonte envia -> nome em português."""
        ...

    @property
    def ultima_fatura(self) -> Fatura | None:
        """A fatura do cartão fechada mais recentemente, se a fonte souber."""
        ...

    def do_periodo(self, inicio: date, fim: date) -> list[Transacao]: ...

    def por_ids(self, ids: Collection[str]) -> list[Transacao]: ...


class FontePluggy:
    """Busca em todas as contas do item. Um erro numa conta não impede as outras."""

    def __init__(self, cliente: ClientePluggy, item_id: str) -> None:
        self._cliente = cliente
        cliente.autenticar()
        self.item = cliente.consultar_item(item_id)
        self._contas = cliente.listar_contas(item_id)
        self._traducoes = cliente.listar_traducoes_de_categoria()
        self.contas_com_erro: set[str] = set()
        self._ultima_fatura = self._buscar_ultima_fatura()

    def _buscar_ultima_fatura(self) -> Fatura | None:
        """Sem as faturas a projeção ainda funciona (pelo mês do calendário), então um erro aqui só avisa."""
        try:
            faturas = [
                fatura
                for conta in self._contas
                if conta.tipo == "CREDIT"
                for fatura in self._cliente.listar_faturas(conta.id)
            ]
        except ErroPluggy as erro:
            registro.warning("Aviso: não foi possível ler as faturas do cartão. %s", erro)
            return None
        return max(faturas, key=lambda fatura: fatura.fechamento, default=None)

    @property
    def ultima_fatura(self) -> Fatura | None:
        return self._ultima_fatura

    @property
    def contas(self) -> list[Conta]:
        return self._contas

    @property
    def traducoes(self) -> Mapping[str, str]:
        return self._traducoes

    def do_periodo(self, inicio: date, fim: date) -> list[Transacao]:
        return self._de_cada_conta(
            lambda conta: self._cliente.listar_transacoes(conta.id, inicio, fim)
        )

    def por_ids(self, ids: Collection[str]) -> list[Transacao]:
        return self._de_cada_conta(
            lambda conta: self._cliente.listar_transacoes_por_ids(conta.id, ids)
        )

    def _de_cada_conta(self, buscar: Callable[[Conta], list[Transacao]]) -> list[Transacao]:
        transacoes: list[Transacao] = []
        for conta in self._contas:
            try:
                transacoes += [traduzir_categoria(t, self._traducoes) for t in buscar(conta)]
            except ErroPluggy as erro:
                self.contas_com_erro.add(conta.id)
                registro.error("Conta %s/%s: %s", conta.tipo, conta.subtipo, erro)
        return transacoes


def traduzir_categoria(transacao: Transacao, traducoes: Mapping[str, str]) -> Transacao:
    """A transação com a categoria em português. Sem tradução conhecida, fica como veio."""
    if transacao.categoria is None or transacao.categoria not in traducoes:
        return transacao
    return replace(transacao, categoria=traducoes[transacao.categoria])


def _ler_json(resposta: requests.Response, caminho: str) -> dict[str, Any]:
    if not resposta.ok:
        raise ErroPluggy(f"A Pluggy respondeu com erro {resposta.status_code} em {caminho}.")
    corpo = resposta.json()
    if not isinstance(corpo, dict):
        raise ErroPluggy(f"Resposta em formato inesperado em {caminho}.")
    return corpo


def _resultados(corpo: dict[str, Any], caminho: str) -> list[dict[str, Any]]:
    resultados = corpo.get("results")
    if not isinstance(resultados, list):
        raise ErroPluggy(f"Resposta sem a lista de resultados em {caminho}.")
    return resultados


def _proximo_cursor(proximo: object) -> str | None:
    """Extrai o cursor do campo `next`, que vem no formato "?accountId=...&after=...".

    `next` vazio significa que não há mais páginas.
    """
    if proximo is None:
        return None
    if not isinstance(proximo, str):
        raise ErroPluggy("Campo de paginação em formato inesperado.")
    valores = parse_qs(proximo.lstrip("?")).get("after")
    if not valores:
        raise ErroPluggy("Campo de paginação sem o cursor da próxima página.")
    return valores[0]


def _montar_conta(bruta: dict[str, Any]) -> Conta:
    try:
        return Conta(id=str(bruta["id"]), tipo=str(bruta["type"]), subtipo=str(bruta["subtype"]))
    except KeyError as erro:
        raise ErroPluggy(f"Conta sem o campo obrigatório {erro}.") from None


def _montar_transacao(bruta: dict[str, Any]) -> Transacao:
    cartao = bruta.get("creditCardMetadata") or {}
    try:
        return Transacao(
            id=str(bruta["id"]),
            conta_id=str(bruta["accountId"]),
            data=datetime.fromisoformat(bruta["date"]),
            descricao=str(bruta["description"]),
            valor=float(bruta["amount"]),
            tipo=str(bruta["type"]),
            status=bruta.get("status") or None,
            categoria=bruta.get("category") or None,
            parcela=_inteiro_ou_nada(cartao.get("installmentNumber")),
            total_parcelas=_inteiro_ou_nada(cartao.get("totalInstallments")),
        )
    except KeyError as erro:
        raise ErroPluggy(f"Transação sem o campo obrigatório {erro}.") from None


def _data_ou_nada(valor: object) -> datetime | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        data = datetime.fromisoformat(valor)
    except ValueError:
        raise ErroPluggy("Data da conexão em formato inesperado.") from None
    return data if data.tzinfo is not None else data.replace(tzinfo=UTC)


def _inteiro_ou_nada(valor: object) -> int | None:
    return int(valor) if isinstance(valor, (int, float)) else None
