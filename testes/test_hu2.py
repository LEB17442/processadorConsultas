import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.HU2.conversor import converter, converter_sql

FALHAS = 0


def verificar(nome, obtido, esperado):
    global FALHAS
    if obtido == esperado:
        print(f"✅ {nome}")
        print(f"   {obtido}")
    else:
        FALHAS += 1
        print(f"❌ {nome}")
        print(f"   esperado: {esperado}")
        print(f"   obtido:   {obtido}")


# Teste 1: SELECT simples sem JOIN e sem WHERE
verificar(
    "T1 - SELECT simples",
    converter_sql("SELECT Nome, Preco FROM Produto"),
    "π_{Nome, Preco}(Produto)",
)

# Teste 2: SELECT com asterisco (entrada estruturada, pois o lexer do HU1 descarta '*')
verificar(
    "T2 - SELECT *",
    converter(
        {
            "select_attributes": ["*"],
            "main_table": "Categoria",
            "joins": [],
            "where_conditions": [],
        }
    ),
    "π_{*}(Categoria)",
)

# Teste 3: SELECT com WHERE
verificar(
    "T3 - SELECT com WHERE",
    converter_sql("SELECT Nome FROM Produto WHERE Preco > 100"),
    "π_{Nome}(σ_{Preco > 100}(Produto))",
)

# Teste 4: SELECT com JOIN e WHERE
verificar(
    "T4 - SELECT com JOIN e WHERE",
    converter_sql(
        "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
        "WHERE ValorTotalPedido > 100"
    ),
    "π_{Cliente.Nome, Pedido.ValorTotalPedido}"
    "(σ_{ValorTotalPedido > 100}"
    "(Cliente ⋈_{Cliente.idCliente = Pedido.Cliente_idCliente} Pedido))",
)

# Teste 5: WHERE com AND (convertido para o símbolo ∧)
verificar(
    "T5 - WHERE com AND",
    converter_sql(
        "SELECT Nome FROM Produto WHERE Preco > 100 AND QuantEstoque < 10"
    ),
    "π_{Nome}(σ_{Preco > 100 ∧ QuantEstoque < 10}(Produto))",
)

# Teste 6: dois JOINs encadeados
verificar(
    "T6 - Dois JOINs",
    converter_sql(
        "SELECT Cliente.Nome, Pedido_has_Produto.Quantidade FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
        "JOIN Pedido_has_Produto ON Pedido.idPedido = Pedido_has_Produto.Pedido_idPedido"
    ),
    "π_{Cliente.Nome, Pedido_has_Produto.Quantidade}"
    "((Cliente ⋈_{Cliente.idCliente = Pedido.Cliente_idCliente} Pedido)"
    " ⋈_{Pedido.idPedido = Pedido_has_Produto.Pedido_idPedido} Pedido_has_Produto)",
)

# Teste 7: conversão a partir de uma estrutura já interpretada (entrada do HU1)
verificar(
    "T7 - converter() com dict do HU1",
    converter(
        {
            "select_attributes": ["Descricao"],
            "main_table": "Categoria",
            "joins": [],
            "where_conditions": [],
        }
    ),
    "π_{Descricao}(Categoria)",
)

# Teste 8: operadores relacionais preservados
verificar(
    "T8 - Operadores preservados",
    converter_sql(
        "SELECT idCliente FROM Cliente WHERE Nascimento >= 19900101 AND idCliente <> 0"
    ),
    "π_{idCliente}(σ_{Nascimento >= 19900101 ∧ idCliente <> 0}(Cliente))",
)

print()
if FALHAS:
    print(f"❌ {FALHAS} teste(s) falharam")
    sys.exit(1)
print("Todos os testes do HU2 passaram!")
