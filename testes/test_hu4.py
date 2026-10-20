import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.HU1.parser import SQLParserHU1
from src.HU4.optimizer import otimizar, otimizar_sql

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


def nos(arvore):
    """Todos os nós da árvore (pós-ordem)."""
    lista = []
    for filho in arvore.filhos:
        lista.extend(nos(filho))
    lista.append(arvore)
    return lista


def tipos(arvore):
    return [no.tipo for no in nos(arvore)]


# Teste 1: consulta simples, sem condições -> nada a otimizar além da projeção final
r = otimizar_sql("SELECT Nome, Preco FROM Produto")
verificar("T1 - SELECT simples", r.algebra, "π_{Nome, Preco}(Produto)")

# Teste 2: tabela única com WHERE -> seleção logo acima da tabela
r = otimizar_sql("SELECT Nome FROM Produto WHERE Preco > 100")
verificar("T2 - Seleção junto da tabela", r.algebra, "π_{Nome}(σ_{Preco > 100}(Produto))")

# Teste 3: consulta padrão da interface (a.i, a.ii, b.i, b.ii juntos)
SQL_PADRAO = (
    "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
    "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
    "WHERE ValorTotalPedido > 100"
)
r = otimizar_sql(SQL_PADRAO)
verificar(
    "T3 - Álgebra otimizada da consulta padrão",
    r.algebra,
    "π_{Cliente.Nome, Pedido.ValorTotalPedido}"
    "(π_{Pedido.ValorTotalPedido, Pedido.Cliente_idCliente}(σ_{ValorTotalPedido > 100}(Pedido))"
    " ⋈_{Cliente.idCliente = Pedido.Cliente_idCliente} "
    "π_{Cliente.idCliente, Cliente.Nome}(Cliente))",
)
verificar("T3 - b.i: tabela com seleção vem primeiro", r.ordem_juncoes, ["Pedido", "Cliente"])

# Teste 4: a.i - a seleção foi empurrada para baixo da junção, direto sobre a tabela
selecao = [no for no in nos(r.arvore) if no.tipo == "selecao"][0]
verificar("T4 - a.i: σ fica sobre a tabela Pedido", (selecao.filhos[0].tipo, selecao.filhos[0].tabela), ("tabela", "Pedido"))

# Teste 5: a.ii - projeções antecipadas mantêm só os atributos usados adiante
juncao = [no for no in nos(r.arvore) if no.tipo == "juncao"][0]
verificar(
    "T5 - a.ii: projeções logo acima das folhas",
    [filho.atributos for filho in juncao.filhos],
    [["Pedido.ValorTotalPedido", "Pedido.Cliente_idCliente"], ["Cliente.idCliente", "Cliente.Nome"]],
)

# Teste 6: seleções da mesma tabela em cascata, a mais restritiva (chave primária) executa primeiro
r = otimizar_sql("SELECT Nome FROM Produto WHERE Preco > 10 AND idProduto = 7")
verificar(
    "T6 - b: cascata com a seleção mais restritiva primeiro",
    r.algebra,
    "π_{Nome}(σ_{Preco > 10}(σ_{idProduto = 7}(Produto)))",
)

# Teste 7: b.i - reordenação das folhas em consulta com 3 tabelas
r = otimizar_sql(
    "SELECT Cliente.Nome FROM Cliente "
    "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
    "JOIN Status ON Pedido.Status_idStatus = Status.idStatus "
    "WHERE Status.Descricao = 'Pago'"
)
verificar("T7 - b.i: Status (mais restritiva) vira a primeira folha", r.ordem_juncoes, ["Status", "Pedido", "Cliente"])
verificar(
    "T7 - Árvore left-deep, sem produto cartesiano",
    tipos(r.arvore),
    ["tabela", "selecao", "projecao", "tabela", "projecao", "juncao", "projecao",
     "tabela", "projecao", "juncao", "projecao"],
)

# Teste 8: b.ii - condição entre tabelas no WHERE é incorporada à junção (σ sobre × vira ⋈)
r = otimizar_sql(
    "SELECT Produto.Nome FROM Produto "
    "JOIN Pedido_has_Produto ON Produto.idProduto = Pedido_has_Produto.Produto_idProduto "
    "WHERE Produto.Preco > Pedido_has_Produto.PrecoUnitario"
)
juncao = [no for no in nos(r.arvore) if no.tipo == "juncao"][0]
verificar(
    "T8 - b.ii: condição do WHERE vira condição da junção",
    juncao.condicao,
    ["Produto.idProduto", "=", "Pedido_has_Produto.Produto_idProduto",
     "AND", "Produto.Preco", ">", "Pedido_has_Produto.PrecoUnitario"],
)
verificar("T8 - Nenhum σ sobrou acima da junção", "selecao" in tipos(r.arvore), False)

# Teste 9: sem condição ligando as tabelas -> produto cartesiano inevitável e sinalizado
r = otimizar_sql("SELECT Cliente.Nome FROM Cliente JOIN Pedido ON Pedido.ValorTotalPedido > 5")
produto = [no for no in nos(r.arvore) if no.tipo == "produto"]
verificar("T9 - Produto cartesiano inevitável", len(produto), 1)
verificar("T9 - Aviso registrado no nó", "produto cartesiano inevitável" in produto[0].heuristicas[0], True)

# Teste 10: SELECT * -> projeções intermediárias não reduziriam nada
r = otimizar_sql(
    "SELECT * FROM Cliente JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
    "WHERE Pedido.ValorTotalPedido > 100"
)
verificar(
    "T10 - SELECT * sem projeções intermediárias",
    r.algebra,
    "π_{*}(σ_{Pedido.ValorTotalPedido > 100}(Pedido) ⋈_{Cliente.idCliente = Pedido.Cliente_idCliente} Cliente)",
)

# Teste 11: WHERE com parênteses e AND
r = otimizar_sql(
    "SELECT Produto.Nome FROM Produto JOIN Categoria ON Produto.Categoria_idCategoria = Categoria.idCategoria "
    "WHERE (Produto.Preco > 10 AND (Categoria.Descricao = 'Livros'))"
)
verificar(
    "T11 - Parênteses: cada condição vai para sua tabela",
    r.algebra,
    "π_{Produto.Nome}(π_{Categoria.idCategoria}(σ_{Categoria.Descricao = 'Livros'}(Categoria))"
    " ⋈_{Produto.Categoria_idCategoria = Categoria.idCategoria} "
    "π_{Produto.Nome, Produto.Categoria_idCategoria}(σ_{Produto.Preco > 10}(Produto)))",
)

# Teste 12: entrada = grafo original (HU3) com produtos cartesianos e uma σ única no topo
def tabela(nome):
    return {"tipo": "tabela", "tabela": nome, "filhos": []}


canonica = {
    "tipo": "projecao",
    "atributos": ["Cliente.Nome"],
    "filhos": [{
        "tipo": "selecao",
        "condicao": "Cliente.idCliente = Pedido.Cliente_idCliente ∧ Pedido.ValorTotalPedido > 100",
        "filhos": [{"tipo": "produto", "filhos": [tabela("Cliente"), tabela("Pedido")]}],
    }],
}
r = otimizar(canonica)
verificar(
    "T12 - Grafo do HU3: × + σ vira ⋈ e σ desce até a tabela",
    r.algebra,
    "π_{Cliente.Nome}(π_{Pedido.Cliente_idCliente}(σ_{Pedido.ValorTotalPedido > 100}(Pedido))"
    " ⋈_{Cliente.idCliente = Pedido.Cliente_idCliente} π_{Cliente.idCliente, Cliente.Nome}(Cliente))",
)

# Teste 13: contrato da árvore (usado pelo HU5) — raiz π, folhas = tabelas, nº de filhos correto
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "schema.json"),
          encoding="utf-8") as f:
    schema = json.load(f)
parsed = SQLParserHU1(schema).parse(SQL_PADRAO)
r = otimizar(parsed, schema)
esperado = {"tabela": 0, "selecao": 1, "projecao": 1, "juncao": 2, "produto": 2}
verificar("T13 - Raiz é a projeção final", r.arvore.tipo, "projecao")
verificar("T13 - Nº de filhos coerente em todos os nós",
          all(len(no.filhos) == esperado[no.tipo] for no in nos(r.arvore)), True)
verificar("T13 - Todo nó registra heurística", all(no.heuristicas for no in nos(r.arvore)), True)
verificar("T13 - Serializável em JSON", isinstance(json.dumps(r.para_dict(), ensure_ascii=False), str), True)

# Teste 14: erros claros para condições malformadas
for nome, sql in [
    ("T14 - Parênteses desbalanceados", "SELECT Nome FROM Produto WHERE (Preco > 10"),
    ("T14 - AND sem operando", "SELECT Nome FROM Produto WHERE Preco > 10 AND"),
]:
    try:
        otimizar_sql(sql)
        verificar(nome, "sem erro", "ValueError")
    except ValueError:
        verificar(nome, "ValueError", "ValueError")

# Teste 15: integração com o HU5 (só roda quando o plano de execução estiver no projeto)
try:
    from src.HU5.plan import gerar_plano
except ImportError:
    gerar_plano = None
if gerar_plano:
    passos = gerar_plano(otimizar_sql(SQL_PADRAO).arvore)
    verificar("T15 - HU5 executa a árvore otimizada até a raiz", passos[-1].operacao, "Projeção (π)")
else:
    print("⏭  T15 - HU5 ainda não está nesta branch (teste de integração ignorado)")

# Exibição completa (o que aparece na interface)
print()
print(otimizar_sql(SQL_PADRAO).relatorio())

print()
if FALHAS:
    print(f"❌ {FALHAS} teste(s) falharam")
    sys.exit(1)
print("Todos os testes do HU4 passaram!")
