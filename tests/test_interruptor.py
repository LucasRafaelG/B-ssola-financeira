"""Testes do interruptor de atualização automática: a aba config e a execução agendada."""

from __future__ import annotations

from pathlib import Path

import pytest

from bussola import main
from bussola.limpeza import COLUNAS_PLANILHA
from bussola.planilha import (
    ABA_CONFIG,
    ABA_PROJECAO,
    ABA_TRANSACOES,
    CHAVE_ATUALIZACAO_AUTOMATICA,
    COLUNAS_CONFIG,
    AbaInexistente,
    Armazenamento,
    ArmazenamentoMemoria,
    Celula,
    ErroPlanilha,
    atualizacao_automatica_ligada,
    definir_atualizacao_automatica,
)
from bussola.pluggy import Fonte

RAIZ = Path(__file__).parent.parent


def _planilha(*linhas_de_config: list[Celula]) -> ArmazenamentoMemoria:
    abas: dict[str, list[list[Celula]]] = {ABA_TRANSACOES: [list(COLUNAS_PLANILHA)]}
    if linhas_de_config:
        abas[ABA_CONFIG] = [list(COLUNAS_CONFIG), *linhas_de_config]
    return ArmazenamentoMemoria(abas)


def test_sem_a_aba_config_a_atualizacao_automatica_vale_ligada() -> None:
    assert atualizacao_automatica_ligada(_planilha()) is True


def test_aba_config_sem_a_linha_tambem_vale_ligada() -> None:
    assert atualizacao_automatica_ligada(_planilha(["outra_chave", "x"])) is True


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("sim", True), ("Sim", True), (" SIM ", True), ("não", False), ("nao", False), ("Não", False)],
)
def test_le_sim_e_nao_sem_ligar_para_maiusculas_e_acento(valor: str, esperado: bool) -> None:
    planilha = _planilha([CHAVE_ATUALIZACAO_AUTOMATICA, valor])

    assert atualizacao_automatica_ligada(planilha) is esperado


@pytest.mark.parametrize("valor", ["", "talvez", "0", "desligada"])
def test_valor_estranho_para_com_mensagem_clara(valor: str) -> None:
    planilha = _planilha([CHAVE_ATUALIZACAO_AUTOMATICA, valor])

    with pytest.raises(ErroPlanilha, match="sim ou não"):
        atualizacao_automatica_ligada(planilha)


def test_cabecalho_errado_na_aba_config_e_recusado() -> None:
    planilha = ArmazenamentoMemoria({ABA_CONFIG: [["chave", "outro"], ["x", "y"]]})

    with pytest.raises(ErroPlanilha, match="cabeçalho"):
        atualizacao_automatica_ligada(planilha)


def test_definir_cria_a_aba_e_a_escolha_e_lida_de_volta() -> None:
    planilha = _planilha()

    definir_atualizacao_automatica(planilha, False)
    assert atualizacao_automatica_ligada(planilha) is False
    assert planilha.ler(ABA_CONFIG) == [COLUNAS_CONFIG, [CHAVE_ATUALIZACAO_AUTOMATICA, "não"]]

    definir_atualizacao_automatica(planilha, True)
    assert atualizacao_automatica_ligada(planilha) is True


def test_definir_nao_toca_nas_outras_abas() -> None:
    planilha = _planilha()
    antes = planilha.ler(ABA_TRANSACOES)

    definir_atualizacao_automatica(planilha, False)

    assert planilha.ler(ABA_TRANSACOES) == antes
    assert set(planilha.abas) == {ABA_TRANSACOES}


def test_aba_que_nao_existe_tem_erro_proprio() -> None:
    with pytest.raises(AbaInexistente):
        _planilha().ler("nao_existe")


class _FonteProibida:
    """Se a execução agendada chegar a abrir a fonte com o interruptor desligado, o teste falha."""

    def __call__(self, *argumentos: object) -> Fonte:
        raise AssertionError("a fonte (o banco) não deveria ter sido consultada")


def _rodar(
    monkeypatch: pytest.MonkeyPatch, planilha: Armazenamento, agendada: bool, proibir_fonte: bool
) -> int:
    monkeypatch.setenv("DATA_MODE", "demo")
    monkeypatch.setattr(main, "abrir_armazenamento", lambda configuracao: planilha)
    if proibir_fonte:
        monkeypatch.setattr(main, "abrir_fonte", _FonteProibida())
    return main.executar(agendada=agendada)


def _planilha_demo(ligada: bool | None) -> ArmazenamentoMemoria:
    from bussola import demo

    planilha = demo.planilha_ficticia()
    if ligada is not None:
        definir_atualizacao_automatica(planilha, ligada)
    return planilha


def test_agendada_com_interruptor_desligado_nao_consulta_o_banco_nem_grava(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planilha = _planilha_demo(ligada=False)
    antes = planilha.ler(ABA_TRANSACOES)

    saida = _rodar(monkeypatch, planilha, agendada=True, proibir_fonte=True)

    assert saida == 0
    assert planilha.ler(ABA_TRANSACOES) == antes
    assert ABA_PROJECAO not in planilha.derivadas


@pytest.mark.parametrize("ligada", [True, None])
def test_agendada_com_interruptor_ligado_ou_sem_a_aba_roda_normalmente(
    monkeypatch: pytest.MonkeyPatch, ligada: bool | None
) -> None:
    planilha = _planilha_demo(ligada)

    saida = _rodar(monkeypatch, planilha, agendada=True, proibir_fonte=False)

    assert saida == 0
    assert len(planilha.ler(ABA_TRANSACOES)) > 1
    assert ABA_PROJECAO in planilha.derivadas


def test_execucao_pedida_a_mao_roda_mesmo_com_o_interruptor_desligado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planilha = _planilha_demo(ligada=False)

    saida = _rodar(monkeypatch, planilha, agendada=False, proibir_fonte=False)

    assert saida == 0
    assert len(planilha.ler(ABA_TRANSACOES)) > 1


def test_workflow_so_passa_agendada_na_execucao_do_agendamento() -> None:
    workflow = (RAIZ / ".github" / "workflows" / "atualizar.yml").read_text(encoding="utf-8")

    assert 'if [ "$EVENTO" = "schedule" ]; then set -- --agendada; fi' in workflow
    assert "EVENTO: ${{ github.event_name }}" in workflow
    assert 'python -m bussola.main "$@"' in workflow
