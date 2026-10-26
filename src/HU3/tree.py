"""
HU3 - Construção do Grafo de Operadores (grafo ORIGINAL, não otimizado)

Recebe a consulta já validada pelo HU1 (dicionário do parser) e constrói, em
memória, a árvore de operadores que representa a estratégia de execução da
consulta exatamente como ela foi escrita, sem nenhuma heurística:

    π  (projeção final: atributos do SELECT)               <- raiz
    └── σ  (todas as condições do WHERE, ligadas por ∧)    <- omitida se não há WHERE
        └── ⋈ (último JOIN)
            ├── ⋈ (JOIN anterior)     junções encadeadas à esquerda: ((A ⋈ B) ⋈ C) ⋈ D
            │   ├── A
            │   └── B
            └── C                     folhas = tabelas

As arestas vão do filho para o pai: cada operador consome os resultados
intermediários produzidos pelos filhos. Otimizar a árvore é papel do HU4.

Uso:
    from src.HU3.tree import build_operator_tree, render_ascii
    arvore = build_operator_tree(parsed)      # parsed = SQLParserHU1(schema).parse(sql)
    print(render_ascii(arvore))

Cada nó (NoGrafo) segue o mesmo contrato lido pelo HU4 e pelo HU5:
    tipo        -> 'tabela' | 'selecao' | 'projecao' | 'juncao'
    filhos      -> lista de nós filhos (vazia nas folhas)
    tabela      -> nome canônico da tabela (folhas)
    condicao    -> tokens da condição (seleção/junção), com "AND" entre condições simples
    atributos   -> atributos qualificados da projeção (ex.: "Cliente.Nome")
    heuristicas -> sempre vazia no grafo original (quem preenche é o HU4)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

# O front importa "HU1.parser" (com src/ no sys.path) e os testes importam
# "src.HU1.parser": para o Python são dois módulos com duas classes ParseError
# diferentes. O estilo do import segue o pacote em que este módulo foi carregado,
# para que o "except ParseError" de quem chamou capture os erros do HU3.
if (__package__ or "").startswith("src."):
    from src.database.schema import DatabaseSchema
    from src.HU1.parser import ParseError, SQLParserHU1
else:
    from database.schema import DatabaseSchema
    from HU1.parser import ParseError, SQLParserHU1

OPERADORES = ("<=", ">=", "<>", "=", ">", "<")  # os mesmos aceitos pelo HU1
SIMBOLOS = {"tabela": "", "selecao": "σ", "projecao": "π", "juncao": "⋈"}

_NUMERO = re.compile(r"^[+-]?\d+(\.\d+)?$")
_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


# ---------------------------------------------------------------------------
# Nó do grafo de operadores
#
# Cada NoGrafo é uma "peça" da árvore: uma tabela ou um operador (σ, π, ⋈).
# A árvore inteira é só uma peça (a raiz π) apontando para as filhas, que
# apontam para as filhas delas, até chegar nas tabelas (folhas).
#
# Os NOMES dos campos são um contrato com as outras HUs: o HU4 (otimização),
# o desenho do HU4 e o HU5 (plano) procuram exatamente "tipo", "filhos",
# "tabela", "condicao" e "atributos". Por isso eles conseguem ler a árvore do HU3.
# ---------------------------------------------------------------------------
@dataclass(eq=False)  # eq=False: nós com o mesmo conteúdo continuam sendo nós distintos
class NoGrafo:
    tipo: str                                              # 'tabela' | 'selecao' (σ) | 'projecao' (π) | 'juncao' (⋈)
    filhos: List["NoGrafo"] = field(default_factory=list)  # quem alimenta este nó: 0 (tabela), 1 (σ, π) ou 2 (⋈)
    tabela: Optional[str] = None                           # só nas folhas: nome da tabela, ex.: "Cliente"
    condicao: Optional[List[str]] = None                   # só em σ e ⋈: tokens, ex.: ["Pedido.ValorTotalPedido", "=", "0"]
    atributos: Optional[List[str]] = None                  # só na π: colunas do SELECT, ex.: ["Cliente.Nome"]
    heuristicas: List[str] = field(default_factory=list)   # sempre vazia: o grafo original não aplica heurística (é o HU4)

    @property
    def simbolo(self) -> str:
        return SIMBOLOS[self.tipo]

    def descricao(self) -> str:
        return descricao_no(self)

    def para_dict(self) -> Dict[str, Any]:
        dados: Dict[str, Any] = {"tipo": self.tipo}
        if self.tabela is not None:
            dados["tabela"] = self.tabela
        if self.condicao is not None:
            dados["condicao"] = list(self.condicao)
        if self.atributos is not None:
            dados["atributos"] = list(self.atributos)
        dados["heuristicas"] = list(self.heuristicas)
        dados["filhos"] = [filho.para_dict() for filho in self.filhos]
        return dados


# ---------------------------------------------------------------------------
# Percursos e exibição
#
# Os percursos NÃO alteram a árvore: só a visitam numa ordem definida.
#   postorder -> ordem de EXECUÇÃO (tabelas primeiro, π por último). É a base da
#                numeração R1, R2, ... dos resultados intermediários, a mesma do HU5.
#   preorder  -> de cima para baixo; a janela usa para descobrir o pai de cada nó.
# Já descricao_no e render_ascii são só de EXIBIÇÃO: transformam nós em texto.
# ---------------------------------------------------------------------------
def postorder(raiz: NoGrafo) -> Iterator[NoGrafo]:
    """Filhos antes do pai (esquerda antes da direita): a ordem em que os operadores executam."""
    # Um operador só pode rodar depois que as entradas (filhos) existirem,
    # então primeiro visita todos os filhos e só depois devolve o próprio nó.
    # Consulta 1: Cliente -> Pedido -> ⋈ -> σ -> π
    for filho in raiz.filhos:
        yield from postorder(filho)
    yield raiz


def preorder(raiz: NoGrafo) -> Iterator[NoGrafo]:
    """Pai antes dos filhos: da projeção final (raiz) até as tabelas (folhas)."""
    yield raiz
    for filho in raiz.filhos:
        yield from preorder(filho)


def _texto_condicao(condicao: Optional[Sequence[str]]) -> str:
    return " ".join("∧" if token.upper() == "AND" else token for token in condicao or [])


def descricao_no(no: NoGrafo) -> str:
    """Rótulo curto do nó, no mesmo formato do HU4: 'π a, b', 'σ cond', '⋈ cond' ou o nome da tabela."""
    if no.tipo == "tabela":
        return no.tabela or "?"
    if no.tipo == "projecao":
        return f"π {', '.join(no.atributos or ['*'])}"
    return f"{SIMBOLOS[no.tipo]} {_texto_condicao(no.condicao)}"


def _rotulo_ascii(no: NoGrafo) -> str:
    if no.tipo == "tabela":
        return no.tabela or "?"
    if no.tipo == "projecao":
        return f"π [{', '.join(no.atributos or ['*'])}]"
    return f"{SIMBOLOS[no.tipo]} [{_texto_condicao(no.condicao)}]"


def render_ascii(raiz: NoGrafo) -> str:
    """Desenha a árvore em texto (raiz no topo, folhas = tabelas)."""
    linhas = [_rotulo_ascii(raiz)]

    def visitar(no: NoGrafo, prefixo: str) -> None:
        # O último filho usa "└──" e os demais "├──"; enquanto ainda há irmãos
        # abaixo, os netos herdam "│   " para a linha vertical continuar.
        for posicao, filho in enumerate(no.filhos):
            ultimo = posicao == len(no.filhos) - 1
            linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{_rotulo_ascii(filho)}")
            visitar(filho, prefixo + ("    " if ultimo else "│   "))

    visitar(raiz, "")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Normalização e validação
#
# Esta parte NÃO é visual: garante que a árvore montada esteja CORRETA.
#   Normalizar = escrever todo nome do jeito oficial do modelo e sempre com a
#                tabela: "cliente.nome" -> "Cliente.Nome", "ValorTotalPedido" ->
#                "Pedido.ValorTotalPedido". Sem isso, o HU4 e o HU5 receberiam
#                nomes incompletos e não saberiam a qual tabela cada coluna pertence.
#   Validar    = barrar o que o HU1 deixa passar (ON com coluna inexistente,
#                atributo ambíguo, WHERE terminando em AND, "1 = 1", ...),
#                levantando ParseError Sintatico ou Semantico.
# ---------------------------------------------------------------------------
def _buscar_tabela(nome: str, tabelas: Sequence[str]) -> Optional[str]:
    for tabela in tabelas:
        if tabela.lower() == nome.lower():
            return tabela
    return None


def _eh_literal(token: str) -> bool:
    return (len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"") or bool(_NUMERO.match(token))


def _tabela_canonica(nome: Any, esquema: DatabaseSchema, onde: str) -> str:
    real = esquema.get_real_table_name(str(nome).strip()) if nome else None
    if not real:
        raise ParseError(f"Erro Semântico: Tabela '{nome}' {onde} não existe no modelo relacional.", "Semantico")
    return real


def _qualificar(texto: str, disponiveis: Sequence[str], todas: Sequence[str],
                esquema: DatabaseSchema, onde: str) -> str:
    """'cliente.nome' -> 'Cliente.Nome'; 'ValorTotalPedido' -> 'Pedido.ValorTotalPedido'.

    disponiveis: tabelas que podem ser usadas neste ponto da consulta
    todas:       todas as tabelas do FROM/JOIN (para explicar melhor o erro)
    """
    if not _IDENTIFICADOR.match(texto):
        raise ParseError(
            f"Erro Sintático: '{texto}' {onde} não é um atributo válido "
            "(textos devem vir entre aspas, ex.: 'Aberto').", "Sintatico"
        )

    # Caso 1: veio com a tabela ("cliente.nome"). Confere se a tabela pode ser
    # usada aqui e se a coluna existe nela; devolve os dois com o nome oficial.
    if "." in texto:
        prefixo, coluna = texto.split(".", 1)
        tabela = _buscar_tabela(prefixo, disponiveis)
        if tabela is None:
            # A tabela está na consulta, mas ainda não entrou neste ponto (dependência lógica)
            if _buscar_tabela(prefixo, todas):
                raise ParseError(
                    f"Erro Semântico: '{texto}' {onde} usa a tabela '{prefixo}', que só entra na consulta "
                    "em um JOIN posterior. Reordene os JOINs.", "Semantico"
                )
            raise ParseError(
                f"Erro Semântico: Tabela '{prefixo}' (em '{texto}' {onde}) não está no FROM/JOIN da consulta.",
                "Semantico"
            )
        if not esquema.attribute_exists(tabela, coluna):
            raise ParseError(
                f"Erro Semântico: Atributo '{coluna}' não existe na tabela '{tabela}' ({onde}).", "Semantico"
            )
        return f"{tabela}.{esquema.get_real_attribute_name(tabela, coluna)}"

    # Caso 2: veio sem a tabela ("ValorTotalPedido"). Procura quais tabelas da
    # consulta têm essa coluna: nenhuma = erro, duas ou mais = ambíguo, uma = achou a dona.
    donos = [tabela for tabela in disponiveis if esquema.attribute_exists(tabela, texto)]
    if not donos:
        if any(esquema.attribute_exists(tabela, texto) for tabela in todas):
            raise ParseError(
                f"Erro Semântico: Atributo '{texto}' {onde} pertence a uma tabela que só entra na consulta "
                "em um JOIN posterior. Reordene os JOINs.", "Semantico"
            )
        raise ParseError(
            f"Erro Semântico: Atributo '{texto}' {onde} não pertence a nenhuma tabela da consulta.", "Semantico"
        )
    if len(donos) > 1:
        exemplo = f"{donos[0]}.{esquema.get_real_attribute_name(donos[0], texto)}"
        raise ParseError(
            f"Erro Semântico: Atributo '{texto}' {onde} é ambíguo, pois existe nas tabelas {', '.join(donos)}. "
            f"Informe no formato Tabela.coluna (ex.: {exemplo}).", "Semantico"
        )
    return f"{donos[0]}.{esquema.get_real_attribute_name(donos[0], texto)}"


def _condicao_simples(tokens: Sequence[str], disponiveis: Sequence[str], todas: Sequence[str],
                      esquema: DatabaseSchema, onde: str) -> List[str]:
    """Valida 'operando operador operando' e devolve os tokens com os nomes canônicos."""
    texto = " ".join(tokens)
    # Forma: exatamente 3 peças com o operador no meio (senão é erro Sintático)
    if len(tokens) != 3 or tokens[1] not in OPERADORES or tokens[0] in OPERADORES or tokens[2] in OPERADORES:
        raise ParseError(
            f"Erro Sintático: Condição inválida {onde}: '{texto}'. Use o formato 'operando operador operando' "
            "(ex.: Pedido.ValorTotalPedido > 100) com um dos operadores =, <>, <, >, <=, >=.", "Sintatico"
        )
    esquerda, operador, direita = tokens
    # Sentido: comparar dois valores ("1 = 1") não filtra nada da tabela (erro Semântico)
    if _eh_literal(esquerda) and _eh_literal(direita):
        raise ParseError(
            f"Erro Semântico: A condição '{texto}' {onde} não usa nenhum atributo. "
            "Compare um atributo com um valor ou com outro atributo.", "Semantico"
        )

    def normalizar(operando: str) -> str:
        # Literais ('Aberto', "x", 5000, 10.5) ficam como vieram; atributos ganham o nome canônico
        return operando if _eh_literal(operando) else _qualificar(operando, disponiveis, todas, esquema, onde)

    return [normalizar(esquerda), operador, normalizar(direita)]


def _condicao_on(on: Any, tabela: str, disponiveis: Sequence[str], todas: Sequence[str],
                 esquema: DatabaseSchema) -> List[str]:
    onde = f"no ON do JOIN {tabela}"
    if not isinstance(on, (list, tuple)):
        raise ParseError(f"Erro Sintático: Condição ausente ou inválida {onde}.", "Sintatico")
    return _condicao_simples([str(token) for token in on], disponiveis, todas, esquema, onde)


def _condicoes_where(tokens: Sequence[str], tabelas: Sequence[str], esquema: DatabaseSchema) -> List[str]:
    """Tokens do WHERE -> tokens normalizados, com "AND" entre as condições simples."""
    if not tokens:
        return []

    # 1) Parênteses precisam abrir e fechar certo
    nivel = 0
    for token in tokens:
        if token == "(":
            nivel += 1
        elif token == ")":
            nivel -= 1
            if nivel < 0:
                break
    if nivel != 0:
        raise ParseError("Erro Sintático: Parênteses desbalanceados na cláusula WHERE.", "Sintatico")

    # 2) Só existe AND no escopo do trabalho, então os parênteses não mudam o significado
    sem_parenteses = [token for token in tokens if token not in ("(", ")")]
    if not sem_parenteses:
        raise ParseError("Erro Sintático: Cláusula 'WHERE' informada sem condições.", "Sintatico")
    for token in sem_parenteses:
        if token.upper() in ("OR", "NOT"):
            raise ParseError(
                f"Erro Sintático: O operador lógico '{token}' não é suportado no WHERE; use apenas AND.", "Sintatico"
            )

    # 3) Corta nos AND: [a, =, 1, AND, b, =, 0] -> [[a, =, 1], [b, =, 0]]
    #    Um grupo vazio denuncia AND sobrando (no fim, no começo ou repetido)
    grupos: List[List[str]] = [[]]
    for token in sem_parenteses:
        if token.upper() == "AND":
            grupos.append([])
        else:
            grupos[-1].append(token)

    if len(grupos) > 1 and not grupos[-1]:
        raise ParseError(
            "Erro Sintático: A cláusula WHERE termina com 'AND', mas falta a condição depois dele.", "Sintatico"
        )
    if len(grupos) > 1 and not grupos[0]:
        raise ParseError(
            "Erro Sintático: A cláusula WHERE começa com 'AND', mas falta a condição antes dele.", "Sintatico"
        )
    if any(not grupo for grupo in grupos):
        raise ParseError("Erro Sintático: Dois 'AND' seguidos na cláusula WHERE, sem condição entre eles.", "Sintatico")

    # 4) Valida e normaliza cada condição e junta tudo de volta com "AND" (vai virar UMA σ)
    resultado: List[str] = []
    for grupo in grupos:
        if resultado:
            resultado.append("AND")
        resultado.extend(_condicao_simples(grupo, tabelas, tabelas, esquema, "no WHERE"))
    return resultado


# ---------------------------------------------------------------------------
# Construção do grafo original  <- O CORAÇÃO DO HU3
#
# A árvore é montada de BAIXO para CIMA, como empilhar blocos:
#   1. começa pela tabela do FROM                          Cliente
#   2. cada JOIN abraça o que já existe (vira o filho      ⋈(Cliente, Pedido)
#      esquerdo) e a tabela nova vira o filho direito      ⋈(⋈(Cliente, Pedido), Status)
#   3. o WHERE inteiro vira UMA σ em cima das junções      σ(...)
#   4. o SELECT vira a π, que fica na raiz                 π(σ(...))
# Nada é otimizado: a σ fica lá em cima (filtra só depois de juntar tudo) e as
# junções seguem a ordem escrita. Mudar isso é o trabalho do HU4.
# ---------------------------------------------------------------------------
def build_operator_tree(parsed: Dict[str, Any], schema: Any = None) -> NoGrafo:
    """
    Constrói o grafo de operadores ORIGINAL (não otimizado) e devolve a raiz (π final).

    parsed: dicionário retornado por SQLParserHU1.parse (HU1).
    schema: DatabaseSchema ou dict {tabela: [atributos]} com os nomes canônicos;
            por padrão usa o modelo de src/database/schema.py.

    Levanta ParseError ('Sintatico' ou 'Semantico') nas validações que o HU1 não faz.
    """
    if not isinstance(parsed, dict):
        raise TypeError("build_operator_tree espera o dicionário devolvido pelo parser do HU1.")
    # Duck typing em vez de isinstance: DatabaseSchema também pode ter sido carregado pelos dois caminhos
    esquema = schema if hasattr(schema, "get_real_attribute_name") else DatabaseSchema(schema)

    # Tabelas: nomes oficiais na ordem do FROM/JOIN, ex.: ["Cliente", "Pedido", "Status"]
    if not parsed.get("main_table"):
        raise ParseError("Erro Sintático: Nenhuma tabela especificada após 'FROM'.", "Sintatico")
    joins = list(parsed.get("joins") or [])
    tabelas = [_tabela_canonica(parsed["main_table"], esquema, "do FROM")]
    for join in joins:
        tabelas.append(_tabela_canonica(join.get("table"), esquema, "do JOIN"))
    for posicao, tabela in enumerate(tabelas):
        if tabela in tabelas[:posicao]:
            raise ParseError(
                f"Erro Semântico: A tabela '{tabela}' aparece mais de uma vez no FROM/JOIN "
                "(auto-junção sem apelido não é suportada).", "Semantico"
            )

    # SELECT: vira a projeção final (raiz). Aqui só preparamos a lista de colunas;
    # o nó π é criado no último passo, para ficar no topo da árvore
    select = [str(atributo).strip() for atributo in parsed.get("select_attributes") or [] if str(atributo).strip()]
    if not select:
        raise ParseError("Erro Sintático: Nenhum atributo informado na cláusula 'SELECT'.", "Sintatico")
    atributos = [
        atributo if atributo == "*" else _qualificar(atributo, tabelas, tabelas, esquema, "no SELECT")
        for atributo in select
    ]

    # FROM/JOIN: junções na ordem escrita, encadeadas à esquerda; cada ON só enxerga
    # as tabelas que já entraram na consulta até aquele JOIN
    arvore = NoGrafo("tabela", tabela=tabelas[0])                  # passo 1: a tabela do FROM
    for posicao, join in enumerate(joins, 1):
        nova = tabelas[posicao]
        # tabelas[:posicao + 1] = tabelas disponíveis até este JOIN (regra das dependências lógicas)
        condicao = _condicao_on(join.get("on"), nova, tabelas[:posicao + 1], tabelas, esquema)
        # passo 2: a árvore atual vira o filho ESQUERDO e a tabela nova o filho DIREITO
        arvore = NoGrafo("juncao", [arvore, NoGrafo("tabela", tabela=nova)], condicao=condicao)

    # WHERE: uma única seleção com todas as condições, logo abaixo da projeção final (passo 3)
    condicoes = _condicoes_where([str(token) for token in parsed.get("where_conditions") or []], tabelas, esquema)
    if condicoes:
        arvore = NoGrafo("selecao", [arvore], condicao=condicoes)

    # Passo 4: a π fecha a árvore no topo. Devolvemos a RAIZ: a partir dela,
    # descendo pelos filhos, chega-se a todos os nós (é isso que a janela, o HU4 e o HU5 recebem)
    return NoGrafo("projecao", [arvore], atributos=atributos)


def _schema_padrao() -> Dict[str, List[str]]:
    caminho = Path(__file__).resolve().parents[2] / "docs" / "schema.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def build_operator_tree_sql(sql: str, schema: Optional[Dict[str, List[str]]] = None) -> NoGrafo:
    """Atalho: valida o SQL com o parser do HU1 e constrói o grafo original."""
    return build_operator_tree(SQLParserHU1(schema or _schema_padrao()).parse(sql))


if __name__ == "__main__":
    import sys

    consulta = " ".join(sys.argv[1:]) or (
        "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
        "WHERE ValorTotalPedido > 100"
    )
    print(f"SQL: {consulta}\n")
    try:
        print(render_ascii(build_operator_tree_sql(consulta)))
    except ParseError as erro:
        print(f"[{erro.error_type}] {erro.message}")
        sys.exit(1)
