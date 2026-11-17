"""Dados fictícios para o modo demo (DATA_MODE=demo).

Têm o mesmo formato e as mesmas convenções da Pluggy (inclusive o sinal invertido
do cartão), para exercitar o projeto inteiro sem tocar na API real. Nada aqui é
dado verdadeiro.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import UTC, date, datetime, time, timedelta

from bussola.limpeza import COLUNAS_PLANILHA
from bussola.planilha import (
    ABA_CONTAS_FIXAS,
    ABA_METAS,
    ABA_REGRAS,
    ABA_TRANSACOES,
    COLUNAS_CONTAS_FIXAS,
    COLUNAS_METAS,
    COLUNAS_REGRAS,
    ArmazenamentoMemoria,
    Celula,
)
from bussola.pluggy import Conta, Fatura, Transacao, traduzir_categoria

CONTA_CORRENTE = Conta(id="demo-conta-corrente", tipo="BANK", subtipo="CHECKING_ACCOUNT")
CARTAO = Conta(id="demo-cartao", tipo="CREDIT", subtipo="CREDIT_CARD")

# (dias atrás, hora UTC, conta, descrição, valor no sinal da Pluggy, tipo, status,
#  categoria da Pluggy, parcela, total de parcelas)
_MODELOS: list[
    tuple[int, int, Conta, str, float, str, str, str | None, int | None, int | None]
] = [
    (28, 12, CONTA_CORRENTE, "SALARIO EMPRESA FICTICIA", 2500.00, "CREDIT", "POSTED", "Salary", None, None),
    (27, 14, CONTA_CORRENTE, "PIX ENVIADO ALUGUEL", -900.00, "DEBIT", "POSTED", "Rent", None, None),
    (25, 21, CONTA_CORRENTE, "MOTORISTA *VIAGEM", -18.40, "DEBIT", "POSTED", None, None, None),
    (22, 1, CONTA_CORRENTE, "ENTREGA *RESTAURANTE", -42.90, "DEBIT", "POSTED", "Food delivery", None, None),
    (20, 16, CONTA_CORRENTE, "Lanchonete da Esquina", -15.00, "DEBIT", "POSTED", None, None, None),
    (15, 13, CONTA_CORRENTE, "PAGAMENTO DE FATURA", -310.00, "DEBIT", "POSTED", "Credit card payment", None, None),
    (15, 13, CARTAO, "PAGAMENTO RECEBIDO", -310.00, "CREDIT", "POSTED", "Credit card payment", None, None),
    (12, 20, CONTA_CORRENTE, "PIX RECEBIDO AMIGO", 60.00, "CREDIT", "POSTED", "Transfer", None, None),
    (10, 3, CARTAO, "STREAMING MAX", 29.90, "DEBIT", "PENDING", "Streaming", 4, 12),
    (9, 3, CARTAO, "LOJA DE JOGOS FICTICIA", 119.90, "DEBIT", "PENDING", "Gaming", 2, 3),
    (6, 22, CARTAO, "TAXI *CORRIDA", 23.10, "DEBIT", "PENDING", None, None, None),
    (3, 23, CONTA_CORRENTE, "MERCADO FICTICIO", -187.35, "DEBIT", "POSTED", "Groceries", None, None),
    (1, 2, CARTAO, "FARMACIA FICTICIA", 56.80, "DEBIT", "PENDING", "Pharmacy", None, None),
]

# Mesma ideia da tabela oficial da Pluggy: nome em inglês -> nome em português.
TRADUCOES = {
    "Salary": "Salário",
    "Rent": "Aluguel",
    "Food delivery": "Delivery de comida",
    "Credit card payment": "Pagamento de cartão de crédito",
    "Transfer": "Transferência",
    "Streaming": "Streaming",
    "Gaming": "Jogos",
    "Groceries": "Supermercado",
    "Pharmacy": "Farmácia",
}


def contas_e_transacoes(hoje: date) -> tuple[list[Conta], list[Transacao]]:
    """Contas e transações fictícias, com datas contadas para trás a partir de `hoje`."""
    transacoes = [
        Transacao(
            id=f"demo-{numero:03d}",
            conta_id=conta.id,
            data=datetime.combine(hoje - timedelta(days=dias_atras), time(hora), tzinfo=UTC),
            descricao=descricao,
            valor=valor,
            tipo=tipo,
            status=status,
            categoria=categoria,
            parcela=parcela,
            total_parcelas=total_parcelas,
        )
        for numero, (
            dias_atras,
            hora,
            conta,
            descricao,
            valor,
            tipo,
            status,
            categoria,
            parcela,
            total_parcelas,
        ) in enumerate(_MODELOS, start=1)
    ]
    return [CONTA_CORRENTE, CARTAO], transacoes



class FonteDemo:
    """Mesma interface da fonte da Pluggy, com os dados fictícios."""

    def __init__(self, hoje: date) -> None:
        self._contas, brutas = contas_e_transacoes(hoje)
        # Fatura fictícia: fechou há 8 dias e venceu há 1.
        self._ultima_fatura = Fatura(hoje - timedelta(days=8), hoje - timedelta(days=1))
        self._transacoes = [traduzir_categoria(t, TRADUCOES) for t in brutas]

    @property
    def contas(self) -> list[Conta]:
        return self._contas

    @property
    def traducoes(self) -> Mapping[str, str]:
        return TRADUCOES

    @property
    def ultima_fatura(self) -> Fatura | None:
        return self._ultima_fatura

    def do_periodo(self, inicio: date, fim: date) -> list[Transacao]:
        return [t for t in self._transacoes if inicio <= t.data.date() <= fim]

    def por_ids(self, ids: Collection[str]) -> list[Transacao]:
        return [t for t in self._transacoes if t.id in ids]


def planilha_ficticia() -> ArmazenamentoMemoria:
    """Planilha em memória com as mesmas abas da real e conteúdo fictício.

    Começa com a aba `transacoes` vazia. Nada do que for gravado nela sai do programa.
    """
    regras: list[list[Celula]] = [
        ["ENTREGA", "Alimentação", "Supérfluo"],
        ["MOTORISTA", "Transporte", "Importante"],
        ["TAXI", "Transporte", "Importante"],
        ["Lanchonete da Esquina", "Alimentação", "Supérfluo"],
        ["StreamingMax", "Assinaturas", "Supérfluo"],
    ]
    contas_fixas: list[list[Celula]] = [
        ["Assinatura fictícia em 12x", 29.90, "", "Assinaturas", "Essencial", 6],
        ["Parcela fictícia", 119.90, "", "Lazer", "Essencial", 1],
    ]
    metas: list[list[Celula]] = [["Guardar no fim do mês", 200, "", "meta fictícia"]]
    return ArmazenamentoMemoria(
        {
            ABA_TRANSACOES: [list(COLUNAS_PLANILHA)],
            ABA_REGRAS: [list(COLUNAS_REGRAS), *regras],
            ABA_CONTAS_FIXAS: [list(COLUNAS_CONTAS_FIXAS), *contas_fixas],
            ABA_METAS: [list(COLUNAS_METAS), *metas],
        }
    )
