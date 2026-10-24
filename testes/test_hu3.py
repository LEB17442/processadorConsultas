import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from src.HU1.parser import ParseError, SQLParserHU1
from src.HU3.tree import build_operator_tree, descricao_no, postorder, preorder, render_ascii
from src.HU4.optimizer import descricao_do_no, otimizar
from src.HU5.plan import plano_execucao

with open(os.path.join(RAIZ, "docs", "schema.json"), "r", encoding="utf-8") as f:
    SCHEMA = json.load(f)
PARSER = SQLParserHU1(SCHEMA)

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


def verificar_erro(nome, entrada, tipo_esperado, trecho):
    """A consulta deve passar pelo HU1 e ser rejeitada pelo HU3 com o error_type esperado."""
    global FALHAS
    try:
        parsed = PARSER.parse(entrada) if isinstance(entrada, str) else entrada
    except ParseError as e:
        FALHAS += 1
        print(f"❌ {nome}")
        print(f"   o HU1 rejeitou antes do HU3: [{e.error_type}] {e.message}")
        return
    try:
        build_operator_tree(parsed)
        obtido, mensagem = "nenhum erro", ""
    except ParseError as e:
        obtido, mensagem = e.error_type, e.message
    if obtido == tipo_esperado and trecho.lower() in mensagem.lower():
        print(f"✅ {nome}")
        print(f"   [{obtido}] {mensagem}")
    else:
        FALHAS += 1
        print(f"❌ {nome}")
        print(f"   esperado: [{tipo_esperado}] mensagem contendo '{trecho}'")
        print(f"   obtido:   [{obtido}] {mensagem}")


def grafo(sql):
    return build_operator_tree(PARSER.parse(sql))


def tipos(arvore):
    return [no.tipo for no in preorder(arvore)]


def resumo(arvore):
    nos = list(postorder(arvore))
    filho = arvore.filhos[0]
    return {
        "raiz": arvore.tipo,
        "filho_da_raiz": filho.tipo,
        "juncoes": sum(1 for no in nos if no.tipo == "juncao"),
        "folhas": sum(1 for no in nos if not no.filhos),
        "condicoes_sigma": filho.condicao.count("AND") + 1 if filho.tipo == "selecao" else 0,
        "nos": len(nos),
    }


def bem_formada(arvore):
    """Folhas = tabelas, 2 filhos em ⋈ (o direito é tabela), 1 filho em σ/π, sem heurísticas."""
    for no in preorder(arvore):
        esperado = {"tabela": 0, "selecao": 1, "projecao": 1, "juncao": 2}[no.tipo]
        if len(no.filhos) != esperado or no.heuristicas:
            return False
        if no.tipo == "juncao" and no.filhos[1].tipo != "tabela":
            return False
    return True


# As 4 consultas de teste do professor
Q1 = """Select cliente.nome, pedido.idPedido, pedido.DataPedido, pedido.ValorTotalPedido
from Cliente Join pedido on cliente.idcliente = pedido.Cliente_idCliente
where cliente.TipoCliente_idTipoCliente = 1 and pedido.ValorTotalPedido = 0;"""

Q2 = """Select cliente.nome, pedido.idPedido, pedido.DataPedido, Status.descricao, pedido.ValorTotalPedido
from Cliente Join pedido on cliente.idcliente = pedido.Cliente_idCliente
Join Status on Status.idstatus = Pedido.status_idstatus
where Status.descricao = 'Aberto' and cliente.TipoCliente_idTipoCliente = 1 and pedido.ValorTotalPedido = 0;"""

Q3 = """Select cliente.nome, pedido.idPedido, pedido.DataPedido, Status.descricao, pedido.ValorTotalPedido, produto.QuantEstoque
from Cliente Join pedido on cliente.idcliente = pedido.Cliente_idCliente
Join Status on Status.idstatus = Pedido.status_idstatus
Join pedido_has_produto on pedido.idPedido = pedido_has_produto.Pedido_idPedido
Join produto on produto.idProduto = pedido_has_produto.Produto_idProduto
where Status.descricao = 'Aberto' and cliente.TipoCliente_idTipoCliente = 1 and pedido.ValorTotalPedido = 0 and produto.QuantEstoque > 0;"""

Q4 = """Select cliente.nome, tipocliente.descricao, pedido.idPedido, pedido.DataPedido, Status.descricao, pedido.ValorTotalPedido, categoria.descricao, produto.QuantEstoque
from Cliente Join pedido on cliente.idcliente = pedido.Cliente_idCliente
Join tipocliente on cliente.tipocliente_idtipocliente = tipocliente.idTipoCliente
Join endereco on cliente.idcliente = endereco.Cliente_idCliente
Join Status on Status.idstatus = Pedido.status_idstatus
Join pedido_has_produto on pedido.idPedido = pedido_has_produto.Pedido_idPedido
Join produto on produto.idProduto = pedido_has_produto.Produto_idProduto
Join categoria on categoria.idcategoria = produto.Categoria_idCategoria
where Status.descricao = 'Aberto' and cliente.email = 'Luffy@gmail.com' and pedido.ValorTotalPedido = 0
and produto.preco > 5000 and endereco.cidade = 'Gramado';"""

CONSULTAS = [Q1, Q2, Q3, Q4]
ESPERADOS = [(1, 2, 5), (2, 3, 7), (4, 4, 11), (7, 5, 17)]  # (junções, condições no σ, nós)

# Testes 1 a 4: estrutura das consultas do professor (passando pelo parser do HU1)
for numero, (sql, (juncoes, condicoes, total)) in enumerate(zip(CONSULTAS, ESPERADOS), 1):
    arvore = grafo(sql)
    verificar(
        f"T{numero} - Estrutura da consulta {numero} do professor",
        resumo(arvore),
        {"raiz": "projecao", "filho_da_raiz": "selecao", "juncoes": juncoes,
         "folhas": juncoes + 1, "condicoes_sigma": condicoes, "nos": total},
    )
    verificar(f"T{numero}b - Folhas = tabelas, ⋈ em cadeia à esquerda, sem heurísticas", bem_formada(arvore), True)

# Teste 5: árvore em texto da consulta 1
verificar(
    "T5 - render_ascii da consulta 1",
    render_ascii(grafo(Q1)),
    "π [Cliente.Nome, Pedido.idPedido, Pedido.DataPedido, Pedido.ValorTotalPedido]\n"
    "└── σ [Cliente.TipoCliente_idTipoCliente = 1 ∧ Pedido.ValorTotalPedido = 0]\n"
    "    └── ⋈ [Cliente.idCliente = Pedido.Cliente_idCliente]\n"
    "        ├── Cliente\n"
    "        └── Pedido",
)

# Teste 6: percursos pós-ordem (ordem de execução) e pré-ordem
arvore_q1 = grafo(Q1)
verificar("T6 - postorder (filhos antes do pai)", [no.tipo for no in postorder(arvore_q1)],
          ["tabela", "tabela", "juncao", "selecao", "projecao"])
verificar("T6b - preorder (raiz primeiro)", tipos(arvore_q1),
          ["projecao", "selecao", "juncao", "tabela", "tabela"])

# Teste 7: nomes canônicos e literal com @ preservado (consulta 4)
arvore_q4 = grafo(Q4)
verificar(
    "T7 - Projeção final com nomes canônicos",
    arvore_q4.atributos,
    ["Cliente.Nome", "TipoCliente.Descricao", "Pedido.idPedido", "Pedido.DataPedido",
     "Status.Descricao", "Pedido.ValorTotalPedido", "Categoria.Descricao", "Produto.QuantEstoque"],
)
verificar(
    "T7b - σ única com todas as condições (literal com @ preservado)",
    arvore_q4.filhos[0].condicao,
    ["Status.Descricao", "=", "'Aberto'", "AND", "Cliente.Email", "=", "'Luffy@gmail.com'", "AND",
     "Pedido.ValorTotalPedido", "=", "0", "AND", "Produto.Preco", ">", "5000", "AND",
     "Endereco.Cidade", "=", "'Gramado'"],
)
verificar(
    "T7c - Folhas na ordem do FROM/JOIN",
    [no.tabela for no in preorder(arvore_q4) if no.tipo == "tabela"],
    ["Cliente", "Pedido", "TipoCliente", "Endereco", "Status", "Pedido_has_Produto", "Produto", "Categoria"],
)
verificar(
    "T7d - Condição do último ⋈ = ON do último JOIN",
    arvore_q4.filhos[0].filhos[0].condicao,
    ["Categoria.idCategoria", "=", "Produto.Categoria_idCategoria"],
)
verificar(
    "T7e - Rótulo curto igual ao descricao_do_no da HU4",
    [descricao_no(no) for no in postorder(arvore_q4)],
    [descricao_do_no(no) for no in postorder(arvore_q4)],
)

# Teste 8: literal com espaço e atributo sem prefixo qualificado
verificar(
    "T8 - Literal com espaço preservado",
    render_ascii(grafo("select nome from cliente where nome = 'Joao Pedro'")),
    "π [Cliente.Nome]\n"
    "└── σ [Cliente.Nome = 'Joao Pedro']\n"
    "    └── Cliente",
)
verificar(
    "T8b - Atributo sem prefixo é qualificado",
    grafo(
        "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
        "WHERE ValorTotalPedido > 100"
    ).filhos[0].condicao,
    ["Pedido.ValorTotalPedido", ">", "100"],
)

# Teste 9: sem JOIN e sem WHERE
verificar(
    "T9 - Sem JOIN e sem WHERE (π → Tabela)",
    render_ascii(grafo("SELECT Nome, Preco FROM Produto")),
    "π [Produto.Nome, Produto.Preco]\n"
    "└── Produto",
)

# Teste 10: SELECT *
arvore_estrela = grafo("SELECT * FROM Categoria")
verificar("T10 - SELECT * mantém o asterisco", (tipos(arvore_estrela), arvore_estrela.atributos),
          (["projecao", "tabela"], ["*"]))

# Teste 11: parênteses no WHERE são descartados (só há AND)
verificar(
    "T11 - Parênteses no WHERE",
    grafo("SELECT Nome FROM Produto WHERE ((Preco > 100) AND (QuantEstoque < 10))").filhos[0].condicao,
    ["Produto.Preco", ">", "100", "AND", "Produto.QuantEstoque", "<", "10"],
)

# Testes 12 a 20: erros que o HU3 detecta (consultas que o HU1 aceita)
verificar_erro(
    "T12 - Atributo inexistente no WHERE",
    {"select_attributes": ["Nome"], "main_table": "Produto", "joins": [],
     "where_conditions": ["Produto.Cor", "=", "'Azul'"]},
    "Semantico", "não existe na tabela 'Produto'",
)
verificar_erro(
    "T13 - Tabela fora do FROM/JOIN (no ON)",
    "SELECT Cliente.Nome FROM Cliente JOIN Pedido ON Status.idStatus = Pedido.Status_idStatus",
    "Semantico", "não está no FROM/JOIN",
)
verificar_erro(
    "T14 - Atributo ambíguo",
    "SELECT Descricao FROM Produto JOIN Categoria ON Produto.Categoria_idCategoria = Categoria.idCategoria",
    "Semantico", "ambíguo",
)
verificar_erro(
    "T15 - WHERE terminando em AND",
    "SELECT Nome FROM Produto WHERE Preco > 100 AND",
    "Sintatico", "termina com 'AND'",
)
verificar_erro(
    "T16 - Condição malformada",
    "SELECT Nome FROM Produto WHERE Preco > 100 QuantEstoque",
    "Sintatico", "operando operador operando",
)
verificar_erro(
    "T17 - Condição sem atributo (1 = 1)",
    "SELECT Nome FROM Produto WHERE 1 = 1",
    "Semantico", "não usa nenhum atributo",
)
verificar_erro(
    "T18 - Atributo inexistente no ON",
    "SELECT Cliente.Nome FROM Cliente JOIN Pedido ON Cliente.idCliente = Pedido.Xyz",
    "Semantico", "não existe na tabela 'Pedido'",
)
verificar_erro(
    "T19 - ON usando tabela de um JOIN posterior",
    "SELECT Cliente.Nome FROM Cliente JOIN Pedido ON Status.idStatus = Pedido.Status_idStatus "
    "JOIN Status ON Cliente.idCliente = Pedido.Cliente_idCliente",
    "Semantico", "JOIN posterior",
)
verificar_erro(
    "T20 - Parênteses desbalanceados",
    "SELECT Nome FROM Produto WHERE (Preco > 100",
    "Sintatico", "desbalanceados",
)

# Teste 21: contrato com a HU5 (um passo por nó, projeção final por último)
for numero, sql in enumerate(CONSULTAS, 1):
    arvore = grafo(sql)
    passos = plano_execucao(arvore, como_texto=False)
    verificar(
        f"T21.{numero} - HU5 gera o plano a partir do grafo original da consulta {numero}",
        (len(passos), passos[-1]["operacao"]),
        (len(list(postorder(arvore))), "Projeção (π)"),
    )

# Teste 22: contrato com a HU4 (mesma ordem de tabelas que otimizar(parsed))
for numero, sql in enumerate(CONSULTAS, 1):
    parsed = PARSER.parse(sql)
    pelo_grafo = otimizar(build_operator_tree(parsed))
    pelo_dict = otimizar(parsed)
    verificar(
        f"T22.{numero} - HU4 otimiza o grafo original da consulta {numero}",
        [tabela.lower() for tabela in pelo_grafo.ordem_juncoes],
        [tabela.lower() for tabela in pelo_dict.ordem_juncoes],
    )

# Teste 23: armadilha de import — no estilo do app.py ("HU1.parser"), o erro do HU3
# precisa ser capturado pelo except ParseError do HU1, e não virar "Erro inesperado"
codigo = f"""
import sys
for caminho in [{os.path.join(RAIZ, "src")!r}, {RAIZ!r}]:
    sys.path.insert(0, caminho)
from HU1.parser import ParseError
from HU3.tree import build_operator_tree
parsed = {{"select_attributes": ["Nome"], "main_table": "Produto", "joins": [],
          "where_conditions": ["Preco", ">", "100", "AND"]}}
try:
    build_operator_tree(parsed)
    print("sem erro")
except ParseError as e:
    print("capturado", e.error_type)
except Exception as e:
    print("nao capturado", type(e).__module__)
import Front.app as app
print("mesma classe no app:", app.ParseError is ParseError, app.build_operator_tree is build_operator_tree)
"""
saida = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True, timeout=120)
verificar(
    "T23 - Erro do HU3 capturado pelo except ParseError do app.py",
    saida.stdout.strip().splitlines() or [saida.stderr.strip()],
    ["capturado Sintatico", "mesma classe no app: True True"],
)

# Teste 24: janela da HU3 (pulado se não houver display)
try:
    import tkinter as tk

    from src.HU3.visualizacao import JanelaGrafoOriginal

    janela_raiz = tk.Tk()
except tk.TclError as e:
    print(f"⏭️  T24 - Janela pulada (sem display disponível: {e})")
else:
    janela_raiz.withdraw()
    janela = JanelaGrafoOriginal(janela_raiz, arvore_q4, Q4)
    janela.update()
    canvas = janela.canvas
    caixas = [item for item in canvas.find_withtag("no") if canvas.type(item) == "polygon"]
    setas = [item for item in canvas.find_all() if canvas.type(item) == "line"]
    total = len(list(postorder(arvore_q4)))
    verificar("T24 - Uma caixa por nó e (nós - 1) setas", (len(caixas), len(setas)), (total, total - 1))
    # Cada seta sai do topo do filho (embaixo) e aponta para a base do pai (em cima)
    verificar(
        "T24b - Setas apontam do filho para o pai",
        all(canvas.itemcget(seta, "arrow") == "last" and canvas.coords(seta)[1] > canvas.coords(seta)[3]
            for seta in setas),
        True,
    )
    textos = [item for item in canvas.find_withtag("no") if canvas.type(item) == "text"]
    topo = min(textos, key=lambda item: canvas.coords(item)[1])
    verificar("T24c - Raiz (no topo) é a projeção π", canvas.itemcget(topo, "text").startswith("π"), True)
    verificar("T24d - Painel com a árvore em texto", render_ascii(arvore_q4) in janela.txt_arvore.get("1.0", "end"), True)
    janela_raiz.destroy()

print()
if FALHAS:
    print(f"❌ {FALHAS} teste(s) falharam")
    sys.exit(1)
print("Todos os testes do HU3 passaram!")
