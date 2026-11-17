"""Como os números e as datas aparecem para quem lê: reais e meses em português."""

from __future__ import annotations

from datetime import date
from numbers import Real

_MESES = [
    "Janeiro",
    "Fevereiro",
    "Março",
    "Abril",
    "Maio",
    "Junho",
    "Julho",
    "Agosto",
    "Setembro",
    "Outubro",
    "Novembro",
    "Dezembro",
]

_DIAS_DA_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def reais(valor: object, centavos: bool = True) -> str:
    """1240.5 vira "R$ 1.240,50". Célula vazia ou com texto vira um traço."""
    if isinstance(valor, bool) or not isinstance(valor, Real):
        return "–"
    numero = float(valor)
    texto = f"{abs(numero):,.2f}" if centavos else f"{abs(numero):,.0f}"
    # O Python escreve 1,240.50; em português é 1.240,50.
    texto = texto.replace(",", "_").replace(".", ",").replace("_", ".")
    sinal = "-" if round(numero, 2 if centavos else 0) < 0 else ""
    return f"{sinal}R$ {texto}"


def mes_por_extenso(ano_e_mes: object) -> str:
    """"2026-11" vira "Novembro de 2026". O que não estiver nesse formato volta como veio."""
    partes = str(ano_e_mes).split("-")
    if len(partes) != 2 or not all(parte.isdecimal() for parte in partes):
        return str(ano_e_mes)
    ano, mes = int(partes[0]), int(partes[1])
    if not 1 <= mes <= 12:
        return str(ano_e_mes)
    return f"{_MESES[mes - 1]} de {ano}"


def dia_da_semana(dia: date) -> str:
    """Abreviação do dia: "seg", "ter"..."""
    return _DIAS_DA_SEMANA[dia.weekday()]


def periodo(inicio: date, fim: date) -> str:
    """"9 a 15 de novembro" ou, virando o mês, "30 de novembro a 6 de dezembro"."""
    mes_do_fim = _MESES[fim.month - 1].lower()
    if (inicio.year, inicio.month) == (fim.year, fim.month):
        return f"{inicio.day} a {fim.day} de {mes_do_fim}"
    return f"{inicio.day} de {_MESES[inicio.month - 1].lower()} a {fim.day} de {mes_do_fim}"
