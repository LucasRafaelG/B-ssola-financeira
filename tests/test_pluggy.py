"""Testes do cliente da Pluggy com respostas falsas (nenhuma chamada real à API)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import requests
import responses
from responses import matchers

from bussola.pluggy import URL_BASE, ClientePluggy, Conta, ErroPluggy, Fatura, FontePluggy, Item

INICIO = date(2026, 10, 1)
FIM = date(2026, 10, 31)


def _transacao_bruta(identificador: str, **extras: object) -> dict[str, object]:
    return {
        "id": identificador,
        "accountId": "conta-1",
        "date": "2026-10-15T03:00:00.000Z",
        "description": "COMPRA FICTICIA",
        "amount": -10.5,
        "type": "DEBIT",
        "status": "POSTED",
        "category": None,
        **extras,
    }


def _cliente_autenticado() -> ClientePluggy:
    responses.post(f"{URL_BASE}/auth", json={"apiKey": "chave-ficticia"})
    cliente = ClientePluggy("id-ficticio", "segredo-ficticio")
    cliente.autenticar()
    return cliente


@responses.activate
def test_autenticar_envia_credenciais_e_usa_a_chave_nas_buscas() -> None:
    responses.post(
        f"{URL_BASE}/auth",
        json={"apiKey": "chave-ficticia"},
        match=[matchers.json_params_matcher({"clientId": "id", "clientSecret": "segredo"})],
    )
    responses.get(
        f"{URL_BASE}/accounts",
        json={"results": [], "page": 1, "total": 0, "totalPages": 1},
        match=[matchers.header_matcher({"X-API-KEY": "chave-ficticia"})],
    )
    cliente = ClientePluggy("id", "segredo")

    cliente.autenticar()

    assert cliente.listar_contas("item-1") == []


def test_buscar_sem_autenticar_da_erro() -> None:
    with pytest.raises(ErroPluggy, match="autenticar"):
        ClientePluggy("id", "segredo").listar_contas("item-1")


@responses.activate
def test_listar_contas_le_tipo_e_subtipo() -> None:
    cliente = _cliente_autenticado()
    responses.get(
        f"{URL_BASE}/accounts",
        json={
            "results": [
                {"id": "c1", "type": "BANK", "subtype": "CHECKING_ACCOUNT", "balance": 1.0},
                {"id": "c2", "type": "CREDIT", "subtype": "CREDIT_CARD", "balance": 2.0},
            ],
            "page": 1,
            "total": 2,
            "totalPages": 1,
        },
        match=[matchers.query_param_matcher({"itemId": "item-1"})],
    )

    assert cliente.listar_contas("item-1") == [
        Conta(id="c1", tipo="BANK", subtipo="CHECKING_ACCOUNT"),
        Conta(id="c2", tipo="CREDIT", subtipo="CREDIT_CARD"),
    ]


@responses.activate
def test_listar_transacoes_segue_o_cursor_ate_a_ultima_pagina() -> None:
    cliente = _cliente_autenticado()
    periodo = {"accountId": "conta-1", "dateFrom": "2026-10-01", "dateTo": "2026-10-31"}
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={
            "results": [_transacao_bruta("t1"), _transacao_bruta("t2")],
            "next": "?accountId=conta-1&after=Y3Vyc29yLTE%3D",
        },
        match=[matchers.query_param_matcher(periodo)],
    )
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={"results": [_transacao_bruta("t3")], "next": None},
        match=[matchers.query_param_matcher(periodo | {"after": "Y3Vyc29yLTE="})],
    )

    transacoes = cliente.listar_transacoes("conta-1", INICIO, FIM)

    assert [t.id for t in transacoes] == ["t1", "t2", "t3"]


@responses.activate
def test_transacao_e_convertida_com_parcelas_e_data_em_utc() -> None:
    cliente = _cliente_autenticado()
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={
            "results": [
                _transacao_bruta(
                    "t1",
                    amount=119.9,
                    category="Shopping",
                    creditCardMetadata={"installmentNumber": 2, "totalInstallments": 3},
                ),
                _transacao_bruta("t2", creditCardMetadata=None),
            ],
            "next": None,
        },
    )

    parcelada, simples = cliente.listar_transacoes("conta-1", INICIO, FIM)

    assert parcelada.valor == 119.9
    assert parcelada.data == datetime(2026, 10, 15, 3, 0, tzinfo=UTC)
    assert parcelada.categoria == "Shopping"
    assert (parcelada.parcela, parcelada.total_parcelas) == (2, 3)
    assert simples.categoria is None
    assert (simples.parcela, simples.total_parcelas) == (None, None)


@responses.activate
def test_cursor_repetido_interrompe_em_vez_de_rodar_para_sempre() -> None:
    cliente = _cliente_autenticado()
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={"results": [_transacao_bruta("t1")], "next": "?accountId=conta-1&after=igual"},
    )

    with pytest.raises(ErroPluggy, match="repetição"):
        cliente.listar_transacoes("conta-1", INICIO, FIM)


@responses.activate
def test_erro_da_api_nao_vaza_o_corpo_da_resposta() -> None:
    cliente = _cliente_autenticado()
    responses.get(
        f"{URL_BASE}/accounts", json={"message": "detalhe-que-nao-deve-aparecer"}, status=403
    )

    with pytest.raises(ErroPluggy) as erro:
        cliente.listar_contas("item-1")

    assert "403" in str(erro.value)
    assert "detalhe-que-nao-deve-aparecer" not in str(erro.value)


@responses.activate
def test_credenciais_erradas_dao_erro_claro() -> None:
    responses.post(f"{URL_BASE}/auth", json={"message": "invalido"}, status=401)

    with pytest.raises(ErroPluggy, match="401"):
        ClientePluggy("id", "errado").autenticar()


@responses.activate
def test_busca_por_ids_manda_os_ids_em_lotes() -> None:
    cliente = _cliente_autenticado()
    ids = [f"id-{numero:03d}" for numero in range(150)]
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={"results": [_transacao_bruta("id-000")], "next": None},
        match=[matchers.query_param_matcher({"accountId": "conta-1", "ids": ",".join(ids[:100])})],
    )
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={"results": [_transacao_bruta("id-100")], "next": None},
        match=[matchers.query_param_matcher({"accountId": "conta-1", "ids": ",".join(ids[100:])})],
    )

    transacoes = cliente.listar_transacoes_por_ids("conta-1", set(ids))

    assert [t.id for t in transacoes] == ["id-000", "id-100"]


_ITEM = {
    "id": "item-1",
    "status": "UPDATED",
    "lastUpdatedAt": "2026-11-13T09:00:00.000Z",
    "consentExpiresAt": "2027-11-10T12:00:00.000Z",
}


_CATEGORIAS = {
    "results": [
        {"id": "1", "description": "Groceries", "descriptionTranslated": "Supermercado"},
        {"id": "2", "description": "Sem tradução", "descriptionTranslated": None},
    ],
    "page": 1,
    "total": 2,
    "totalPages": 1,
}


def _contas(*identificadores: str) -> dict[str, object]:
    return {
        "results": [
            {"id": identificador, "type": "BANK", "subtype": "CHECKING_ACCOUNT"}
            for identificador in identificadores
        ],
        "page": 1,
        "total": len(identificadores),
        "totalPages": 1,
    }


@responses.activate
def test_fonte_junta_as_transacoes_de_todas_as_contas() -> None:
    responses.post(f"{URL_BASE}/auth", json={"apiKey": "chave-ficticia"})
    responses.get(f"{URL_BASE}/items/item-1", json=_ITEM)
    responses.get(f"{URL_BASE}/accounts", json=_contas("conta-1", "conta-2"))
    responses.get(f"{URL_BASE}/categories", json=_CATEGORIAS)
    for conta, transacao in (("conta-1", "t1"), ("conta-2", "t2")):
        responses.get(
            f"{URL_BASE}/v2/transactions",
            json={"results": [_transacao_bruta(transacao, accountId=conta)], "next": None},
            match=[matchers.query_param_matcher({"accountId": conta}, strict_match=False)],
        )

    fonte = FontePluggy(ClientePluggy("id", "segredo"), "item-1")
    transacoes = fonte.do_periodo(INICIO, FIM)

    assert [conta.id for conta in fonte.contas] == ["conta-1", "conta-2"]
    assert [t.id for t in transacoes] == ["t1", "t2"]
    assert fonte.contas_com_erro == set()


@responses.activate
def test_erro_numa_conta_nao_impede_as_outras_e_fica_registrado() -> None:
    responses.post(f"{URL_BASE}/auth", json={"apiKey": "chave-ficticia"})
    responses.get(f"{URL_BASE}/items/item-1", json=_ITEM)
    responses.get(f"{URL_BASE}/accounts", json=_contas("conta-1", "conta-2"))
    responses.get(f"{URL_BASE}/categories", json=_CATEGORIAS)
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={"message": "falhou"},
        status=500,
        match=[matchers.query_param_matcher({"accountId": "conta-1"}, strict_match=False)],
    )
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={"results": [_transacao_bruta("t2", accountId="conta-2")], "next": None},
        match=[matchers.query_param_matcher({"accountId": "conta-2"}, strict_match=False)],
    )

    fonte = FontePluggy(ClientePluggy("id", "segredo"), "item-1")
    transacoes = fonte.do_periodo(INICIO, FIM)

    assert [t.id for t in transacoes] == ["t2"]
    assert fonte.contas_com_erro == {"conta-1"}


@responses.activate
def test_falha_de_rede_vira_erro_da_pluggy_sem_detalhes() -> None:
    cliente = _cliente_autenticado()
    responses.get(
        f"{URL_BASE}/accounts",
        body=requests.ConnectionError("detalhe-que-nao-deve-aparecer"),
    )

    with pytest.raises(ErroPluggy) as erro:
        cliente.listar_contas("item-1")

    assert "ConnectionError" in str(erro.value)
    assert "detalhe-que-nao-deve-aparecer" not in str(erro.value)


@responses.activate
def test_resposta_que_nao_e_json_vira_erro_da_pluggy() -> None:
    cliente = _cliente_autenticado()
    responses.get(f"{URL_BASE}/accounts", body="<html>fora do ar</html>")

    with pytest.raises(ErroPluggy, match="/accounts"):
        cliente.listar_contas("item-1")


@responses.activate
def test_fonte_entrega_as_categorias_em_portugues() -> None:
    responses.post(f"{URL_BASE}/auth", json={"apiKey": "chave-ficticia"})
    responses.get(f"{URL_BASE}/items/item-1", json=_ITEM)
    responses.get(f"{URL_BASE}/accounts", json=_contas("conta-1"))
    responses.get(f"{URL_BASE}/categories", json=_CATEGORIAS)
    responses.get(
        f"{URL_BASE}/v2/transactions",
        json={
            "results": [
                _transacao_bruta("t1", category="Groceries"),
                _transacao_bruta("t2", category="Sem tradução"),
                _transacao_bruta("t3", category="Categoria nova"),
                _transacao_bruta("t4", category=None),
            ],
            "next": None,
        },
    )

    fonte = FontePluggy(ClientePluggy("id", "segredo"), "item-1")
    transacoes = fonte.do_periodo(INICIO, FIM)

    assert fonte.traducoes == {"Groceries": "Supermercado"}
    assert [t.categoria for t in transacoes] == [
        "Supermercado",
        "Sem tradução",
        "Categoria nova",
        None,
    ]


AGORA = datetime(2026, 11, 13, 13, 0, tzinfo=UTC)
ITEM_SAUDAVEL = Item(
    status="UPDATED",
    sincronizado_em=AGORA - timedelta(hours=4),
    consentimento_expira_em=AGORA + timedelta(days=360),
)


@responses.activate
def test_consultar_item_le_status_e_datas() -> None:
    cliente = _cliente_autenticado()
    responses.get(f"{URL_BASE}/items/item-1", json=_ITEM)

    item = cliente.consultar_item("item-1")

    assert item == Item(
        status="UPDATED",
        sincronizado_em=datetime(2026, 11, 13, 9, 0, tzinfo=UTC),
        consentimento_expira_em=datetime(2027, 11, 10, 12, 0, tzinfo=UTC),
    )


@responses.activate
def test_erro_ao_consultar_item_nao_mostra_o_id() -> None:
    cliente = _cliente_autenticado()
    responses.get(f"{URL_BASE}/items/id-que-nao-deve-aparecer", json={}, status=404)

    with pytest.raises(ErroPluggy) as erro:
        cliente.consultar_item("id-que-nao-deve-aparecer")

    assert "404" in str(erro.value)
    assert "id-que-nao-deve-aparecer" not in str(erro.value)


def test_item_saudavel_nao_tem_problemas() -> None:
    assert ITEM_SAUDAVEL.problemas(AGORA) == []
    assert Item("UPDATING", AGORA, None).problemas(AGORA) == []
    assert ITEM_SAUDAVEL.dias_ate_o_consentimento_expirar(AGORA) == 360


@pytest.mark.parametrize(
    ("item", "trecho"),
    [
        (Item("LOGIN_ERROR", AGORA, AGORA + timedelta(days=90)), "status LOGIN_ERROR"),
        (Item("OUTDATED", AGORA, AGORA + timedelta(days=90)), "status OUTDATED"),
        (Item("UPDATED", AGORA, AGORA - timedelta(hours=1)), "consentimento"),
        (Item("UPDATED", AGORA - timedelta(days=4), AGORA + timedelta(days=90)), "não sincroniza"),
        (Item("UPDATED", None, AGORA + timedelta(days=90)), "não sincroniza"),
    ],
)
def test_item_com_problema_explica_o_que_fazer(item: Item, trecho: str) -> None:
    problemas = item.problemas(AGORA)

    assert len(problemas) == 1
    assert trecho in problemas[0]
    assert "meu.pluggy.ai" in problemas[0]


def test_item_pode_ter_varios_problemas_ao_mesmo_tempo() -> None:
    item = Item("LOGIN_ERROR", AGORA - timedelta(days=10), AGORA - timedelta(days=1))

    assert len(item.problemas(AGORA)) == 3


_FATURAS = {
    "results": [
        {"id": "f1", "billClosingDate": "2026-10-05T00:00:00.000Z", "dueDate": "2026-10-13T00:00:00.000Z"},
        {"id": "f2", "billClosingDate": "2026-11-05T00:00:00.000Z", "dueDate": "2026-11-12T00:00:00.000Z"},
        {"id": "f3", "billClosingDate": None, "dueDate": "2026-12-12T00:00:00.000Z"},
    ],
    "page": 1,
    "total": 3,
    "totalPages": 1,
}

_CONTA_E_CARTAO = {
    "results": [
        {"id": "conta-1", "type": "BANK", "subtype": "CHECKING_ACCOUNT"},
        {"id": "cartao-1", "type": "CREDIT", "subtype": "CREDIT_CARD"},
    ],
    "page": 1,
    "total": 2,
    "totalPages": 1,
}


@responses.activate
def test_listar_faturas_le_as_datas_sem_mudar_o_dia() -> None:
    cliente = _cliente_autenticado()
    responses.get(
        f"{URL_BASE}/bills",
        json=_FATURAS,
        match=[matchers.query_param_matcher({"accountId": "cartao-1"})],
    )

    assert cliente.listar_faturas("cartao-1") == [
        Fatura(date(2026, 10, 5), date(2026, 10, 13)),
        Fatura(date(2026, 11, 5), date(2026, 11, 12)),
    ]


def _fonte_com_cartao() -> FontePluggy:
    responses.post(f"{URL_BASE}/auth", json={"apiKey": "chave-ficticia"})
    responses.get(f"{URL_BASE}/items/item-1", json=_ITEM)
    responses.get(f"{URL_BASE}/accounts", json=_CONTA_E_CARTAO)
    responses.get(f"{URL_BASE}/categories", json=_CATEGORIAS)
    return FontePluggy(ClientePluggy("id", "segredo"), "item-1")


@responses.activate
def test_fonte_guarda_a_fatura_fechada_mais_recente_do_cartao() -> None:
    responses.get(
        f"{URL_BASE}/bills",
        json=_FATURAS,
        match=[matchers.query_param_matcher({"accountId": "cartao-1"})],
    )

    assert _fonte_com_cartao().ultima_fatura == Fatura(date(2026, 11, 5), date(2026, 11, 12))


@responses.activate
def test_erro_ao_ler_faturas_nao_derruba_a_execucao() -> None:
    responses.get(f"{URL_BASE}/bills", json={"message": "indisponível"}, status=403)

    fonte = _fonte_com_cartao()

    assert fonte.ultima_fatura is None
    assert fonte.contas_com_erro == set()


@responses.activate
def test_fonte_sem_cartao_nao_tem_fatura() -> None:
    responses.post(f"{URL_BASE}/auth", json={"apiKey": "chave-ficticia"})
    responses.get(f"{URL_BASE}/items/item-1", json=_ITEM)
    responses.get(f"{URL_BASE}/accounts", json=_contas("conta-1"))
    responses.get(f"{URL_BASE}/categories", json=_CATEGORIAS)

    assert FontePluggy(ClientePluggy("id", "segredo"), "item-1").ultima_fatura is None
