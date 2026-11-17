"""Testes do aplicativo, sempre no modo demo: dados fictícios, nada de rede."""

from __future__ import annotations

import tomllib
from datetime import date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Button, Selectbox

from bussola.config import FUSO_HORARIO
from bussola.formatos import mes_por_extenso, reais

RAIZ = Path(__file__).parent.parent
APP = str(RAIZ / "app" / "Bussola.py")


# Rodado dentro do Streamlit: esquece a planilha fictícia guardada, para um teste que
# grava (criar regra, lançar) não deixar rastro para o seguinte.
LIMPAR_O_QUE_FICOU_GUARDADO = """
import streamlit as st

st.cache_resource.clear()
st.cache_data.clear()
"""


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("DATA_MODE", "demo")
    AppTest.from_string(LIMPAR_O_QUE_FICOU_GUARDADO, default_timeout=60).run()
    return AppTest.from_file(APP, default_timeout=60).run()


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (1240.5, "R$ 1.240,50"),
        (0, "R$ 0,00"),
        (-510, "-R$ 510,00"),
        (1234567.891, "R$ 1.234.567,89"),
        (-0.001, "R$ 0,00"),
        ("", "–"),
        ("sim", "–"),
        (True, "–"),
    ],
)
def test_reais(valor: object, esperado: str) -> None:
    assert reais(valor) == esperado


def test_reais_sem_centavos() -> None:
    assert reais(1240.5, centavos=False) == "R$ 1.240"
    assert reais(-0.4, centavos=False) == "R$ 0"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("2026-11", "Novembro de 2026"),
        ("2027-03", "Março de 2027"),
        ("2026-13", "2026-13"),
        ("novembro", "novembro"),
        ("", ""),
    ],
)
def test_mes_por_extenso(valor: str, esperado: str) -> None:
    assert mes_por_extenso(valor) == esperado


def test_app_abre_no_modo_demo_sem_erro(app: AppTest) -> None:
    assert not app.exception
    assert not app.error
    assert [aviso.value for aviso in app.sidebar.caption][0] == "Modo demo: dados fictícios."


def test_tela_do_mes_mostra_o_mes_corrente_e_os_quatro_numeros(app: AppTest) -> None:
    hoje: date = datetime.now(FUSO_HORARIO).date()

    assert app.main.title[0].value == mes_por_extenso(f"{hoje:%Y-%m}")
    rotulos = [metrica.label for metrica in app.metric]
    assert rotulos[:4] == ["Gasto até hoje", "Entradas até hoje", "Sobra provável", "Sobra segura"]
    assert all(metrica.value.startswith(("R$", "-R$")) for metrica in app.metric[:4])


def test_tela_do_mes_mostra_a_fatura_e_a_meta(app: AppTest) -> None:
    rotulos = [metrica.label for metrica in app.metric]
    assert "Aberta até hoje" in rotulos and "Deve fechar em" in rotulos
    subtitulos = [subtitulo.value for subtitulo in app.subheader]
    assert any(subtitulo.startswith("Meta:") for subtitulo in subtitulos)
    assert "Gasto por categoria" in subtitulos
    assert "Parcelas que ainda vão cair" in subtitulos


def test_recarregar_nao_quebra_a_tela(app: AppTest) -> None:
    next(botao for botao in app.sidebar.button if botao.label == "Recarregar da planilha").click().run()

    assert not app.exception
    assert len(app.metric) >= 4


def test_app_so_responde_ao_proprio_computador() -> None:
    """O app não tem login: se atendesse a rede, qualquer aparelho no Wi-Fi veria os dados."""
    configuracao = tomllib.loads((RAIZ / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    assert configuracao["server"]["address"] == "localhost"


def test_tela_da_semana_abre_na_semana_atual(app: AppTest) -> None:
    app.switch_page("paginas/semana.py").run()

    assert not app.exception
    assert app.main.title[0].value.startswith("Semana de ")
    assert app.selectbox[0].options[0].endswith("(esta semana)")
    assert [metrica.label for metrica in app.metric] == [
        "Gasto na semana",
        "Entradas na semana",
        "Média por dia",
        "Transações",
    ]
    assert [subtitulo.value for subtitulo in app.main.subheader] == [
        "Gasto por dia",
        "Categorias frente à sua média semanal",
        "Maiores gastos da semana",
        "Ainda sem regra",
    ]


def test_tela_da_semana_troca_de_semana(app: AppTest) -> None:
    app.switch_page("paginas/semana.py").run()
    opcoes = app.selectbox[0].options
    assert len(opcoes) >= 2

    app.selectbox[0].select_index(1).run()

    assert not app.exception
    assert app.main.title[0].value == f"Semana de {opcoes[1]}"
    assert not [legenda for legenda in app.main.caption if "em andamento" in legenda.value]


def _tela_de_regras(app: AppTest) -> AppTest:
    return app.switch_page("paginas/regras.py").run()


def _regras_em_uso(app: AppTest) -> list[str]:
    return list(app.dataframe[0].value["Palavra-chave"])


def test_tela_de_regras_mostra_as_regras_e_as_descricoes_sem_regra(app: AppTest) -> None:
    _tela_de_regras(app)

    assert not app.exception
    assert app.main.title[0].value == "Regras e categorias"
    assert _regras_em_uso(app) == ["ENTREGA", "MOTORISTA", "TAXI", "Lanchonete da Esquina", "StreamingMax"]
    assert list(app.dataframe[0].value["Cobre"]) == [1, 1, 1, 1, 1]
    assert len([botao for botao in app.button if botao.label == "Usar como regra"]) == 8


def test_usar_como_regra_preenche_a_palavra_chave(app: AppTest) -> None:
    _tela_de_regras(app)
    assert app.text_input[0].value == ""

    next(botao for botao in app.button if botao.label == "Usar como regra").click().run()

    assert not app.exception
    assert app.text_input[0].value == "FARMACIA FICTICIA"
    assert "1 transações têm essa palavra-chave: 1 passariam a usar a regra." in [
        legenda.value for legenda in app.main.caption
    ]


def test_criar_regra_grava_recategoriza_e_esvazia_o_formulario(app: AppTest) -> None:
    _tela_de_regras(app)
    app.text_input[0].set_value("mercado ficticio").run()
    app.selectbox[0].set_value("Supermercado").run()
    app.selectbox[1].set_value("Essencial").run()

    next(botao for botao in app.button if botao.label == "Criar regra").click().run()

    assert not app.exception and not app.error
    assert [aviso.value for aviso in app.success] == [
        'Regra "mercado ficticio" criada. 1 transações recategorizadas.'
    ]
    assert _regras_em_uso(app)[-1] == "mercado ficticio"
    assert list(app.dataframe[0].value["Cobre"])[-1] == 1
    assert app.text_input[0].value == ""
    assert len([botao for botao in app.button if botao.label == "Usar como regra"]) == 7


def test_regra_invalida_mostra_o_erro_e_nao_grava(app: AppTest) -> None:
    _tela_de_regras(app)
    app.text_input[0].set_value("entre ga").run()
    app.selectbox[0].set_value("Alimentação").run()

    next(botao for botao in app.button if botao.label == "Criar regra").click().run()

    assert [erro.value for erro in app.error] == [
        'Já existe uma regra com a palavra-chave "entre ga". Para mudá-la, use “Editar uma regra”.'
    ]
    assert len(_regras_em_uso(app)) == 5


def test_regra_criada_num_teste_nao_vaza_para_o_seguinte(app: AppTest) -> None:
    _tela_de_regras(app)

    assert len(_regras_em_uso(app)) == 5


def _tela_de_lancar(app: AppTest) -> AppTest:
    return app.switch_page("paginas/lancar.py").run()


def _botao(app: AppTest, rotulo: str) -> Button:
    return next(botao for botao in app.button if botao.label == rotulo)


def _preencher_lancamento(app: AppTest, valor: float, descricao: str, categoria: str) -> None:
    app.number_input[0].set_value(valor).run()
    app.text_input[0].set_value(descricao).run()
    app.selectbox[1].set_value(categoria).run()


def test_tela_de_lancar_abre_vazia_e_avisa_sobre_o_modo_de_uso(app: AppTest) -> None:
    _tela_de_lancar(app)

    assert not app.exception
    assert app.main.title[0].value == "Lançar à mão"
    assert app.radio[0].value == "Gasto"
    assert app.selectbox[0].value == "Dinheiro"
    assert app.number_input[0].value is None
    assert "Nenhum lançamento manual ainda." in [legenda.value for legenda in app.main.caption]
    assert not app.warning


def test_lancar_um_gasto_grava_aparece_na_lista_e_esvazia_o_formulario(app: AppTest) -> None:
    _tela_de_lancar(app)
    _preencher_lancamento(app, 25.0, "Feira de sábado", "Supermercado")
    assert "Vai para a planilha como gasto de R$ 25,00" in " ".join(
        legenda.value for legenda in app.main.caption
    )

    _botao(app, "Lançar").click().run()

    assert not app.exception and not app.error
    assert [aviso.value for aviso in app.success] == ["Gasto de R$ 25,00 lançado."]
    lista = app.dataframe[0].value
    assert lista[["Descrição", "Conta", "Categoria", "Valor"]].values.tolist() == [
        ["Feira de sábado", "Dinheiro", "Supermercado", "-R$ 25,00"]
    ]
    assert app.number_input[0].value is None and app.text_input[0].value == ""


def test_gasto_lancado_entra_na_projecao_do_mes(app: AppTest) -> None:
    def gasto_ate_hoje() -> str:
        app.switch_page("paginas/mes.py").run()
        return str(app.metric[0].value)

    antes = gasto_ate_hoje()
    _tela_de_lancar(app)
    _preencher_lancamento(app, 1000.0, "Conserto", "Supermercado")
    _botao(app, "Lançar").click().run()

    depois = gasto_ate_hoje()

    def numero(texto: str) -> float:
        return float(texto.replace("R$", "").replace(".", "").replace(",", ".").strip())

    assert numero(depois) == pytest.approx(numero(antes) + 1000.0)


def test_lancar_uma_entrada_nao_pede_prioridade(app: AppTest) -> None:
    _tela_de_lancar(app)
    app.radio[0].set_value("Entrada").run()
    assert [caixa.label for caixa in app.selectbox] == ["Onde entrou", "Categoria"]
    _preencher_lancamento(app, 40.0, "Amigo devolveu", "Não é renda")

    _botao(app, "Lançar").click().run()

    assert [aviso.value for aviso in app.success] == ["Entrada de R$ 40,00 lançado."]
    assert app.dataframe[0].value["Valor"].tolist() == ["R$ 40,00"]


def test_lancamento_sem_valor_mostra_o_erro_e_nao_grava(app: AppTest) -> None:
    _tela_de_lancar(app)
    app.text_input[0].set_value("Sem valor").run()
    app.selectbox[1].set_value("Supermercado").run()

    _botao(app, "Lançar").click().run()

    assert [erro.value for erro in app.error] == ["O valor deve ser maior que zero."]
    assert not app.dataframe


def test_lancar_fora_do_dinheiro_avisa_que_pode_contar_em_dobro(app: AppTest) -> None:
    _tela_de_lancar(app)

    app.selectbox[0].set_value("Cartão de crédito").run()

    assert len(app.warning) == 1 and "duas vezes" in app.warning[0].value


def test_corrigir_uma_transacao_marca_como_manual_e_tira_das_sugestoes(app: AppTest) -> None:
    _tela_de_regras(app)
    next(campo for campo in app.text_input if campo.label == "Procurar na descrição").set_value(
        "farmacia"
    ).run()
    transacao = next(caixa for caixa in app.selectbox if caixa.label == "Transação")
    assert len(transacao.options) == 1 and "FARMACIA FICTICIA" in transacao.options[0]
    next(caixa for caixa in app.selectbox if caixa.label == "Nova categoria").set_value("Supermercado").run()
    next(caixa for caixa in app.selectbox if caixa.label == "Nova prioridade").set_value("Essencial").run()

    _botao(app, "Salvar correção").click().run()

    assert not app.exception and not app.error
    assert [aviso.value for aviso in app.success] == [
        "Correção salva: a transação agora está em “Supermercado”."
    ]
    # marcada como manual, ela deixa de aparecer entre as descrições sem regra
    assert len([botao for botao in app.button if botao.label == "Usar como regra"]) == 7
    transacao = next(caixa for caixa in app.selectbox if caixa.label == "Transação")
    assert any("FARMACIA FICTICIA" in opcao and "Supermercado" in opcao for opcao in transacao.options)


def _legendas_da_barra(app: AppTest) -> list[str]:
    return [legenda.value for legenda in app.sidebar.caption]


def test_barra_lateral_mostra_o_interruptor_ligado_e_a_data_das_projecoes(app: AppTest) -> None:
    assert app.sidebar.toggle[0].label == "Automática" and app.sidebar.toggle[0].value is True
    assert "O robô atualiza todo dia às 07:00." in _legendas_da_barra(app)
    assert any(legenda.startswith("Projeções: calculado em ") for legenda in _legendas_da_barra(app))
    assert [botao.label for botao in app.sidebar.button] == ["Atualizar agora", "Recarregar da planilha"]


def test_interruptor_do_app_desliga_e_religa_o_robo(app: AppTest) -> None:
    app.sidebar.toggle[0].set_value(False).run()

    assert not app.exception
    assert app.sidebar.toggle[0].value is False
    assert "O robô está parado. Atualize quando quiser, pelo botão." in _legendas_da_barra(app)
    assert "desligada" in app.sidebar.success[0].value

    # a escolha fica na planilha: outra tela, ou o app reaberto, continua vendo desligado
    app.switch_page("paginas/semana.py").run()
    assert app.sidebar.toggle[0].value is False

    app.sidebar.toggle[0].set_value(True).run()
    assert app.sidebar.toggle[0].value is True
    assert "ligada" in app.sidebar.success[0].value


def test_atualizar_agora_funciona_com_o_robo_desligado(app: AppTest) -> None:
    app.sidebar.toggle[0].set_value(False).run()

    _botao(app, "Atualizar agora").click().run()

    assert not app.exception and not app.sidebar.error
    assert [aviso.value for aviso in app.sidebar.success] == [
        "Atualizado: 0 transações novas, 0 recategorizadas."
    ]
    assert app.sidebar.toggle[0].value is False
    assert len(app.metric) >= 4


def _campo(app: AppTest, rotulo: str, posicao: int = 0) -> Selectbox[str]:
    return [caixa for caixa in app.selectbox if caixa.label == rotulo][posicao]


def test_editar_regra_pelo_app_recategoriza_as_transacoes_antigas(app: AppTest) -> None:
    _tela_de_regras(app)
    _campo(app, "Regra").set_value("ENTREGA").run()
    # a segunda caixa "Categoria" é a da edição; a primeira é a da regra nova
    _campo(app, "Categoria", 1).set_value("Supermercado").run()

    _botao(app, "Salvar alterações").click().run()

    assert not app.exception and not app.error
    assert [aviso.value for aviso in app.success] == [
        'Regra "ENTREGA" atualizada. 1 transações recategorizadas.'
    ]
    regras = app.dataframe[0].value
    assert regras.loc[regras["Palavra-chave"] == "ENTREGA", "Categoria"].tolist() == ["Supermercado"]


def test_apagar_regra_pede_confirmacao_e_devolve_as_transacoes(app: AppTest) -> None:
    _tela_de_regras(app)
    _campo(app, "Regra").set_value("ENTREGA").run()
    assert _botao(app, "Apagar regra").disabled

    next(caixa for caixa in app.checkbox if caixa.label == "Quero apagar esta regra").check().run()
    _botao(app, "Apagar regra").click().run()

    assert not app.exception and not app.error
    assert [aviso.value for aviso in app.success] == [
        'Regra "ENTREGA" apagada. 1 transações recategorizadas.'
    ]
    assert "ENTREGA" not in _regras_em_uso(app)
