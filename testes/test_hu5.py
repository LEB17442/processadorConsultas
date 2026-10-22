import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.HU5.plan import (
    H_JUNCAO,
    H_JUNCAO_REDUZIDA,
    H_PROJECAO,
    H_PROJECAO_FINAL,
    H_SELECAO,
    H_SELECAO_POS_JUNCAO,
    formatar_plano,
    gerar_plano,
)

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


def tabela(nome):
    return {"tipo": "tabela", "tabela": nome, "filhos": []}


def selecao(condicao, filho):
    return {"tipo": "selecao", "condicao": condicao, "filhos": [filho]}


def projecao(atributos, filho):
    return {"tipo": "projecao", "atributos": atributos, "filhos": [filho]}


def juncao(condicao, esquerda, direita):
    return {"tipo": "juncao", "condicao": condicao, "filhos": [esquerda, direita]}


# Teste 1: consulta simples -> tabela e projeção final
passos = gerar_plano(projecao(["Nome", "Preco"], tabela("Produto")))
verificar(
    "T1 - Ordem simples",
    [p.expressao for p in passos],
    ["Produto", "π_{Nome, Preco}(R1)"],
)
verificar("T1 - Heurística da raiz", passos[-1].heuristicas, [H_PROJECAO_FINAL])

# Teste 2: árvore otimizada com seleção empurrada e projeções antecipadas
# SELECT Cliente.Nome, Pedido.idPedido FROM Cliente JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente
# WHERE Pedido.ValorTotalPedido > 100
arvore = projecao(
    ["Cliente.Nome", "Pedido.idPedido"],
    juncao(
        ("Cliente.idCliente", "=", "Pedido.Cliente_idCliente"),
        projecao(["Cliente.idCliente", "Cliente.Nome"], tabela("Cliente")),
        projecao(
            ["Pedido.idPedido", "Pedido.Cliente_idCliente"],
            selecao(["Pedido.ValorTotalPedido", ">", "100"], tabela("Pedido")),
        ),
    ),
)
passos = gerar_plano(arvore)
verificar(
    "T2 - Pós-ordem (filhos antes do pai)",
    [f"{p.resultado} ← {p.expressao}" for p in passos],
    [
        "R1 ← Cliente",
        "R2 ← π_{Cliente.idCliente, Cliente.Nome}(R1)",
        "R3 ← Pedido",
        "R4 ← σ_{Pedido.ValorTotalPedido > 100}(R3)",
        "R5 ← π_{Pedido.idPedido, Pedido.Cliente_idCliente}(R4)",
        "R6 ← R2 ⋈_{Cliente.idCliente = Pedido.Cliente_idCliente} R5",
        "R7 ← π_{Cliente.Nome, Pedido.idPedido}(R6)",
    ],
)
verificar("T2 - Seleção reduz tuplas", passos[3].heuristicas, [H_SELECAO])
verificar("T2 - Projeção antecipada", passos[1].heuristicas, [H_PROJECAO])
verificar("T2 - Junção sem produto cartesiano", passos[5].heuristicas, [H_JUNCAO, H_JUNCAO_REDUZIDA])
verificar("T2 - Raiz é o último passo", passos[-1].heuristicas, [H_PROJECAO_FINAL])

# Teste 3: seleção que depende de duas tabelas fica acima da junção
passos = gerar_plano(
    projecao(
        ["Produto.Nome"],
        selecao(
            ["Produto.Preco", ">", "Pedido_has_Produto.PrecoUnitario"],
            juncao(
                "Produto.idProduto = Pedido_has_Produto.Produto_idProduto",
                tabela("Produto"),
                tabela("Pedido_has_Produto"),
            ),
        ),
    )
)
verificar("T3 - Seleção pós-junção", passos[3].heuristicas, [H_SELECAO_POS_JUNCAO])
verificar("T3 - Junção sem entrada reduzida", passos[2].heuristicas, [H_JUNCAO])

# Teste 4: heurísticas registradas pelo HU4 têm prioridade; nós como objetos com chaves em inglês
no_tabela = SimpleNamespace(type="table", label="Categoria", children=[])
no_raiz = SimpleNamespace(
    type="π", attributes=["Descricao"], children=[no_tabela], heuristics=["Registrada pelo HU4"]
)
passos = gerar_plano(no_raiz)
verificar("T4 - Heurística vinda do HU4", passos[-1].heuristicas, ["Registrada pelo HU4"])
verificar("T4 - Objetos/inglês aceitos", passos[0].expressao, "Categoria")

# Teste 5: condição com AND convertida para ∧
passos = gerar_plano(
    projecao(["Nome"], selecao(["Preco", ">", "10", "AND", "QuantEstoque", "<", "5"], tabela("Produto")))
)
verificar("T5 - AND vira ∧", passos[1].expressao, "σ_{Preco > 10 ∧ QuantEstoque < 5}(R1)")

# Teste 6: árvore malformada gera erro claro
try:
    gerar_plano({"tipo": "juncao", "condicao": "a = b", "filhos": [tabela("Cliente")]})
    verificar("T6 - Erro em junção com 1 filho", "sem erro", "ValueError")
except ValueError as e:
    verificar("T6 - Erro em junção com 1 filho", "ValueError", "ValueError")

# Exibição completa usada na interface
print()
print(formatar_plano(gerar_plano(arvore)))

print()
if FALHAS:
    print(f"❌ {FALHAS} teste(s) falharam")
    sys.exit(1)
print("Todos os testes do HU5 passaram!")
