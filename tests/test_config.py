from __future__ import annotations

import pytest

from bussola.config import DIAS_HISTORICO_PADRAO, ErroConfiguracao, carregar

AMBIENTE_COMPLETO = {
    "PLUGGY_CLIENT_ID": "id-ficticio",
    "PLUGGY_CLIENT_SECRET": "segredo-ficticio",
    "PLUGGY_ITEM_ID": "item-ficticio",
    "SHEET_ID": "planilha-ficticia",
}


def test_carrega_quando_todas_as_variaveis_existem() -> None:
    configuracao = carregar(AMBIENTE_COMPLETO)

    assert configuracao.acesso is not None
    assert configuracao.acesso.pluggy.client_id == "id-ficticio"
    assert configuracao.acesso.pluggy.client_secret == "segredo-ficticio"
    assert configuracao.acesso.pluggy.item_id == "item-ficticio"
    assert configuracao.acesso.sheet_id == "planilha-ficticia"
    assert configuracao.dias_historico == DIAS_HISTORICO_PADRAO


def test_erro_lista_os_nomes_que_faltam() -> None:
    ambiente = {"PLUGGY_CLIENT_ID": "id-ficticio", "PLUGGY_CLIENT_SECRET": "   "}

    with pytest.raises(ErroConfiguracao) as erro:
        carregar(ambiente)

    mensagem = str(erro.value)
    assert "PLUGGY_CLIENT_SECRET" in mensagem
    assert "PLUGGY_ITEM_ID" in mensagem
    assert "SHEET_ID" in mensagem
    assert "PLUGGY_CLIENT_ID," not in mensagem


def test_imprimir_a_configuracao_nao_mostra_segredos() -> None:
    texto = repr(carregar(AMBIENTE_COMPLETO))

    for valor in AMBIENTE_COMPLETO.values():
        assert valor not in texto


def test_modo_demo_dispensa_as_credenciais() -> None:
    assert carregar({"DATA_MODE": "demo"}).acesso is None
    assert carregar({"DATA_MODE": " Demo "} | AMBIENTE_COMPLETO).acesso is None


def test_modo_desconhecido_da_erro() -> None:
    with pytest.raises(ErroConfiguracao, match="DATA_MODE"):
        carregar({"DATA_MODE": "teste"} | AMBIENTE_COMPLETO)


def test_dias_de_historico_pode_ser_configurado() -> None:
    assert carregar({"DIAS_HISTORICO": "30"} | AMBIENTE_COMPLETO).dias_historico == 30


@pytest.mark.parametrize("valor", ["0", "-5", "muitos", "1.5"])
def test_dias_de_historico_invalido_da_erro(valor: str) -> None:
    with pytest.raises(ErroConfiguracao, match="DIAS_HISTORICO"):
        carregar({"DIAS_HISTORICO": valor} | AMBIENTE_COMPLETO)
