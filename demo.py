import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.HU1.parser import SQLParserHU1, ParseError
from src.HU2.conversor import converter

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "schema.json"), "r", encoding="utf-8") as f:
    SCHEMA = json.load(f)

parser = SQLParserHU1(SCHEMA)


def processar(sql: str) -> None:
    try:
        parsed = parser.parse(sql)
        print("   ", converter(parsed), "\n")
    except ParseError as e:
        print(f"    ❌ [{e.error_type}] {e.message}\n")
    except Exception as e:
        print(f"    ❌ Erro na conversão: {e}\n")


print("=" * 60)
print("Processador de Consultas - Demo HU2")
print("Conversão de SQL para Álgebra Relacional")
print("=" * 60)
print("Consultas podem ter várias linhas.")
print("Termine com ;  (ou aperte Enter em linha vazia para executar)")
print("Digite 'sair' (ou Ctrl+D) para encerrar\n")

pendente = ""

while True:
    prompt = "SQL> " if not pendente else "...> "
    try:
        linha = input(prompt)
    except EOFError:
        break

    linha = linha.strip()

    if not pendente:
        if not linha:
            continue
        if linha.lower() in ("sair", "exit", "quit"):
            break
        pendente = linha
    else:
        if not linha:
            sql = pendente
            pendente = ""
            processar(sql)
            continue
        pendente = f"{pendente} {linha}"

    while ";" in pendente:
        antes, _, resto = pendente.partition(";")
        pendente = resto.strip()
        if antes.strip():
            processar(antes.strip())

print("Até logo!")
