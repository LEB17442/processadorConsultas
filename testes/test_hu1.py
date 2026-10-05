import json
from src.HU1.parser import SQLParserHU1, ParseError

# Carregar o schema do banco
with open("docs/schema.json", "r") as f:
    schema = json.load(f)

parser = SQLParserHU1(schema)

# Teste 1: Consulta Válida com JOIN
try:
    sql = "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente WHERE ValorTotalPedido > 100"
    res = parser.parse(sql)
    print("✅ Teste 1 Sucesso:", res)
except ParseError as e:
    print(f"❌ Teste 1 Falhou [{e.error_type}]: {e.message}")

# Teste 2: Erro Semântico (Coluna inexistente)
try:
    sql = "SELECT ColunaInexistente FROM Cliente"
    res = parser.parse(sql)
except ParseError as e:
    print(f"✅ Teste 2 Capturou Erro Esperado [{e.error_type}]: {e.message}")