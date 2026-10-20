"""
HU4 - Otimização da Consulta

Recebe a consulta já validada pelo HU1 (dicionário do parser) — ou o grafo de
operadores original do HU3 — e constrói o grafo de operadores OTIMIZADO,
aplicando as heurísticas do enunciado:

    a. Aplicar primeiro as operações que reduzem os resultados intermediários
         i.  seleções  -> reduzem o número de tuplas     (σ empurrada para junto da tabela)
         ii. projeções -> reduzem o número de atributos  (π empurrada para baixo)
    b. Aplicar primeiro as seleções e junções mais restritivas
         i.   reordenar os nós folha da árvore de consulta
         ii.  evitar o produto cartesiano                 (σ sobre × vira ⋈)
         iii. ajustar o restante da árvore

Uso:
    from src.HU4.optimizer import otimizar
    resultado = otimizar(parsed)          # parsed = SQLParserHU1(schema).parse(sql)
    resultado.arvore                      # NoOperador raiz (entrada do HU5)
    resultado.algebra                     # álgebra relacional otimizada (estilo do HU2)
    resultado.heuristicas_aplicadas       # passo a passo das heurísticas
    resultado.texto_arvore                # grafo otimizado em texto

Cada nó da árvore segue o contrato lido pelo HU5:
    tipo        -> 'tabela' | 'selecao' | 'projecao' | 'juncao' | 'produto'
    filhos      -> lista de nós filhos (vazia nas folhas)
    tabela      -> nome da tabela (folhas)
    condicao    -> tokens da condição (seleção/junção)
    atributos   -> atributos da projeção
    heuristicas -> heurísticas aplicadas naquele nó

Como não há estatísticas do banco, a restritividade de cada condição é
estimada com os fatores de seletividade padrão do System R (Selinger et al., 1979).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# (tabela, coluna), ambos em minúsculas — identidade de um atributo do modelo
Atributo = Tuple[str, str]

OPERADORES = ("=", "<>", "!=", "<", ">", "<=", ">=")
LOGICOS = {"AND": "∧", "OR": "∨"}
PALAVRAS_LOGICAS = {"AND", "OR", "NOT"}
LITERAIS = {"NULL", "TRUE", "FALSE"}

SIMBOLOS = {"tabela": "", "selecao": "σ", "projecao": "π", "juncao": "⋈", "produto": "×"}

TIPOS = {
    "tabela": "tabela", "table": "tabela", "relacao": "tabela", "relação": "tabela",
    "selecao": "selecao", "seleção": "selecao", "select": "selecao", "selection": "selecao", "σ": "selecao",
    "projecao": "projecao", "projeção": "projecao", "project": "projecao", "projection": "projecao", "π": "projecao",
    "juncao": "juncao", "junção": "juncao", "join": "juncao", "⋈": "juncao",
    "produto": "produto", "cartesiano": "produto", "product": "produto", "×": "produto",
}

# Fração estimada de tuplas que satisfaz cada tipo de condição (padrão System R)
SELETIVIDADE_CHAVE = 0.01       # atributo = valor, na chave primária (≈ 1 tupla)
SELETIVIDADE_IGUAL = 0.10       # atributo = valor
SELETIVIDADE_FAIXA = 1 / 3      # <, >, <=, >=
SELETIVIDADE_DIFERENTE = 0.90   # <>
SELETIVIDADE_COMPOSTA = 0.50    # condição composta (ex.: com OR)

H_TABELA = "Acesso à relação base (folha da árvore)"
H_PROJECAO_FINAL = "Projeção final: retorna apenas os atributos pedidos no SELECT"

_PADRAO_TOKENS = re.compile(r"'[^']*'|\"[^\"]*\"|<=|>=|<>|!=|∧|∨|[A-Za-z0-9_.@]+|[*=<>(),]")
_NUMERO = re.compile(r"^[+-]?\d+(\.\d+)?$")


# ---------------------------------------------------------------------------
# Nó do grafo de operadores
# ---------------------------------------------------------------------------
@dataclass
class NoOperador:
    tipo: str
    filhos: List["NoOperador"] = field(default_factory=list)
    tabela: Optional[str] = None
    condicao: Optional[List[str]] = None
    atributos: Optional[List[str]] = None
    heuristicas: List[str] = field(default_factory=list)

    @property
    def simbolo(self) -> str:
        return SIMBOLOS[self.tipo]

    def descricao(self) -> str:
        return descricao_do_no(self)

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


@dataclass
class ResultadoOtimizacao:
    arvore: NoOperador
    algebra: str
    heuristicas_aplicadas: List[str]
    ordem_juncoes: List[str]

    @property
    def texto_arvore(self) -> str:
        return arvore_para_texto(self.arvore)

    def relatorio(self) -> str:
        """Texto completo (álgebra + grafo + heurísticas) para terminal ou interface."""
        return "\n".join([
            "ÁLGEBRA RELACIONAL OTIMIZADA",
            self.algebra,
            "",
            "GRAFO DE OPERADORES OTIMIZADO",
            self.texto_arvore,
            "",
            "HEURÍSTICAS APLICADAS",
            *self.heuristicas_aplicadas,
        ])

    def para_dict(self) -> Dict[str, Any]:
        return {
            "algebra": self.algebra,
            "ordem_juncoes": list(self.ordem_juncoes),
            "heuristicas_aplicadas": list(self.heuristicas_aplicadas),
            "arvore": self.arvore.para_dict(),
        }


# ---------------------------------------------------------------------------
# Leitura genérica de nós (aceita NoOperador, dicts e objetos de outras HUs)
# ---------------------------------------------------------------------------
def _campo(no: Any, *nomes: str) -> Any:
    for nome in nomes:
        if isinstance(no, dict):
            valor = no.get(nome)
        else:
            valor = getattr(no, nome, None)
            if callable(valor):
                valor = None
        if valor is not None:
            return valor
    return None


def tipo_do_no(no: Any) -> str:
    bruto = _campo(no, "tipo", "type", "op", "operador")
    if bruto is None:
        raise ValueError(f"Nó sem tipo de operador: {no!r}")
    tipo = TIPOS.get(str(bruto).strip().lower())
    if tipo is None:
        raise ValueError(f"Tipo de operador desconhecido: {bruto!r}")
    return tipo


def filhos_do_no(no: Any) -> List[Any]:
    filhos = _campo(no, "filhos", "children")
    if filhos is not None:
        return list(filhos)
    unico = _campo(no, "filho", "child", "entrada")
    if unico is not None:
        return [unico]
    lados = [_campo(no, "esquerda", "left"), _campo(no, "direita", "right")]
    return [lado for lado in lados if lado is not None]


def _tabela_do_no(no: Any) -> str:
    return str(_campo(no, "tabela", "nome", "label", "valor", "rotulo") or "?")


def _condicao_do_no(no: Any) -> Any:
    return _campo(no, "condicao", "condition", "on", "predicado")


def _atributos_do_no(no: Any) -> List[str]:
    valor = _campo(no, "atributos", "attributes", "colunas")
    if valor is None:
        return ["*"]
    if isinstance(valor, str):
        return [parte.strip() for parte in valor.split(",") if parte.strip()] or ["*"]
    return [str(atributo) for atributo in valor] or ["*"]


# ---------------------------------------------------------------------------
# Condições
# ---------------------------------------------------------------------------
def tokens_condicao(condicao: Any) -> List[str]:
    """Normaliza a condição (texto, tupla (a, op, b), lista de tokens ou de condições) em tokens."""
    if condicao is None:
        return []
    if isinstance(condicao, str):
        return [{"∧": "AND", "∨": "OR"}.get(t, t) for t in _PADRAO_TOKENS.findall(condicao)]
    itens = list(condicao)
    if itens and all(isinstance(item, (list, tuple)) for item in itens):
        tokens: List[str] = []
        for posicao, item in enumerate(itens):
            if posicao:
                tokens.append("AND")
            tokens.extend(tokens_condicao(item))
        return tokens
    tokens = []
    for item in itens:
        if isinstance(item, (list, tuple)):
            tokens.extend(tokens_condicao(item))
        elif " " in str(item).strip():
            tokens.extend(tokens_condicao(str(item)))
        else:
            texto = str(item).strip()
            tokens.append({"∧": "AND", "∨": "OR"}.get(texto, texto))
    return tokens


def formatar_condicao(condicao: Any) -> str:
    """Tokens -> texto, trocando AND/OR por ∧/∨ (mesma notação do HU2)."""
    texto = " ".join(LOGICOS.get(t.upper(), t) for t in tokens_condicao(condicao))
    return texto.replace("( ", "(").replace(" )", ")")


def _verificar_parenteses(tokens: List[str]) -> None:
    nivel = 0
    for token in tokens:
        if token == "(":
            nivel += 1
        elif token == ")":
            nivel -= 1
            if nivel < 0:
                break
    if nivel != 0:
        raise ValueError(f"Parênteses desbalanceados na condição: {formatar_condicao(tokens)}")


def _sem_parenteses_externos(tokens: List[str]) -> List[str]:
    while len(tokens) >= 2 and tokens[0] == "(" and tokens[-1] == ")":
        nivel = 0
        for posicao, token in enumerate(tokens):
            nivel += 1 if token == "(" else -1 if token == ")" else 0
            if nivel == 0 and posicao < len(tokens) - 1:
                return tokens
        tokens = tokens[1:-1]
    return tokens


def dividir_conjuncao(tokens: List[str]) -> List[List[str]]:
    """σ_{c1 ∧ c2 ∧ ...} -> [c1, c2, ...] (separa só nos AND de nível externo)."""
    tokens = _sem_parenteses_externos(list(tokens))
    partes: List[List[str]] = []
    atual: List[str] = []
    nivel = 0
    for token in tokens:
        if token == "(":
            nivel += 1
        elif token == ")":
            nivel -= 1
        if nivel == 0 and token.upper() == "AND":
            partes.append(atual)
            atual = []
        else:
            atual.append(token)
    partes.append(atual)
    if len(partes) == 1:
        return [partes[0]] if partes[0] else []
    resultado: List[List[str]] = []
    for parte in partes:
        if not parte:
            raise ValueError(f"Condição incompleta: 'AND' sem operando em {formatar_condicao(tokens)}")
        resultado.extend(dividir_conjuncao(parte))
    return resultado


def _eh_literal(token: str) -> bool:
    return (
        (len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"")
        or bool(_NUMERO.match(token))
        or token.upper() in LITERAIS
    )


def _eh_atributo(token: str) -> bool:
    return not (
        token in OPERADORES
        or token in ("(", ")", ",")
        or token.upper() in PALAVRAS_LOGICAS
        or _eh_literal(token)
    )


# ---------------------------------------------------------------------------
# Exibição da árvore
# ---------------------------------------------------------------------------
def _texto_atributos(atributos: Any) -> str:
    if isinstance(atributos, str):
        return atributos
    return ", ".join(str(atributo) for atributo in atributos)


def descricao_do_no(no: Any) -> str:
    """Rótulo curto do nó: 'π a, b', 'σ cond', '⋈ cond', '×' ou o nome da tabela."""
    tipo = tipo_do_no(no)
    if tipo == "tabela":
        return _tabela_do_no(no)
    if tipo == "produto":
        return "×"
    if tipo == "projecao":
        return f"π {_texto_atributos(_atributos_do_no(no))}"
    return f"{SIMBOLOS[tipo]} {formatar_condicao(_condicao_do_no(no))}"


def arvore_para_algebra(no: Any) -> str:
    """Árvore -> expressão em álgebra relacional, no mesmo formato do HU2."""
    tipo = tipo_do_no(no)
    filhos = filhos_do_no(no)
    if tipo == "tabela":
        return _tabela_do_no(no)
    if tipo == "selecao":
        return f"σ_{{{formatar_condicao(_condicao_do_no(no))}}}({arvore_para_algebra(filhos[0])})"
    if tipo == "projecao":
        return f"π_{{{_texto_atributos(_atributos_do_no(no))}}}({arvore_para_algebra(filhos[0])})"
    lados = []
    for filho in filhos[:2]:
        texto = arvore_para_algebra(filho)
        if tipo_do_no(filho) in ("juncao", "produto"):
            texto = f"({texto})"
        lados.append(texto)
    if tipo == "juncao":
        return f"{lados[0]} ⋈_{{{formatar_condicao(_condicao_do_no(no))}}} {lados[1]}"
    return f"{lados[0]} × {lados[1]}"


def arvore_para_texto(raiz: Any) -> str:
    """Desenha a árvore em texto (raiz no topo, folhas = tabelas)."""
    linhas: List[str] = []

    def visitar(no: Any, prefixo: str, ultimo: bool, eh_raiz: bool) -> None:
        if eh_raiz:
            linhas.append(descricao_do_no(no))
            proximo = ""
        else:
            linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{descricao_do_no(no)}")
            proximo = prefixo + ("    " if ultimo else "│   ")
        filhos = filhos_do_no(no)
        for posicao, filho in enumerate(filhos):
            visitar(filho, proximo, posicao == len(filhos) - 1, False)

    visitar(raiz, "", True, True)
    return "\n".join(linhas)


def _pct(fator: float) -> str:
    valor = fator * 100
    if valor < 0.1:
        return "< 0,1%"
    if valor >= 10 or valor == int(valor):
        return f"{valor:.0f}%"
    return f"{valor:.1f}%".replace(".", ",")


def _produto(valores: Iterable[float]) -> float:
    total = 1.0
    for valor in valores:
        total *= valor
    return total


# ---------------------------------------------------------------------------
# Otimização
# ---------------------------------------------------------------------------
@dataclass
class _Referencia:
    texto: str
    candidatos: List[Atributo]

    @property
    def tabelas(self) -> Set[str]:
        return {tabela for tabela, _ in self.candidatos}


@dataclass
class _Predicado:
    tokens: List[str]
    origem: str
    de_juncao: bool
    referencias: List[_Referencia]
    tipo: str = "selecao"   # 'selecao' | 'juncao' | 'complexo' | 'constante'
    fator: float = 1.0

    @property
    def tabelas(self) -> Set[str]:
        return set().union(*(r.tabelas for r in self.referencias))

    @property
    def atributos(self) -> Set[Atributo]:
        return {atributo for r in self.referencias for atributo in r.candidatos}

    @property
    def texto(self) -> str:
        return formatar_condicao(self.tokens)


class _Otimizacao:
    def __init__(self, schema: Dict[str, List[str]], tabelas: List[str],
                 condicoes: List[Tuple[List[str], str, bool]], select: List[str]):
        self.schema = schema
        self.chaves: List[str] = []
        self.nome_tabela: Dict[str, str] = {}
        self.nome_coluna: Dict[Atributo, str] = {}
        self.avisos: List[str] = []

        for nome in tabelas:
            nome = str(nome).strip()
            chave = nome.lower()
            if chave not in schema:
                raise ValueError(f"Tabela '{nome}' não existe no modelo relacional.")
            if chave in self.nome_tabela:
                raise ValueError(
                    f"A tabela '{nome}' aparece mais de uma vez na consulta "
                    "(auto-junção sem alias não é suportada)."
                )
            self.chaves.append(chave)
            self.nome_tabela[chave] = nome
        if not self.chaves:
            raise ValueError("Consulta sem tabela (cláusula FROM).")

        self.select = [str(a).strip() for a in (select or []) if str(a).strip()] or ["*"]
        self.todos_atributos = "*" in self.select
        self.refs_select = [self._resolver(a) for a in self.select if a != "*"]

        self.predicados: List[_Predicado] = []
        for tokens, origem, de_juncao in condicoes:
            _verificar_parenteses(tokens)
            for conjunto in dividir_conjuncao(tokens):
                self.predicados.append(self._analisar(conjunto, origem, de_juncao))

        self.log_juncoes: List[str] = []
        self.log_projecoes: List[str] = []

    # --- análise das condições -------------------------------------------
    def _resolver(self, texto: str) -> _Referencia:
        if "." in texto:
            prefixo, coluna = texto.split(".", 1)
            chave = prefixo.lower()
            if chave not in self.nome_tabela:
                raise ValueError(f"A tabela '{prefixo}' (em '{texto}') não está no FROM/JOIN da consulta.")
            if coluna.lower() not in self.schema[chave]:
                raise ValueError(f"O atributo '{coluna}' não existe na tabela '{self.nome_tabela[chave]}'.")
            candidatos = [(chave, coluna.lower())]
        else:
            coluna = texto
            candidatos = [(t, texto.lower()) for t in self.chaves if texto.lower() in self.schema[t]]
            if not candidatos:
                raise ValueError(f"O atributo '{texto}' não pertence a nenhuma tabela da consulta.")
            if len(candidatos) > 1:
                donos = ", ".join(self.nome_tabela[t] for t, _ in candidatos)
                aviso = (f"Atributo '{texto}' é ambíguo (existe em {donos}): tratado de forma "
                         "conservadora — qualifique como Tabela.Atributo para otimizar melhor.")
                if aviso not in self.avisos:
                    self.avisos.append(aviso)
        for atributo in candidatos:
            self.nome_coluna.setdefault(atributo, coluna)
        return _Referencia(texto, candidatos)

    def _analisar(self, tokens: List[str], origem: str, de_juncao: bool) -> _Predicado:
        referencias = [self._resolver(token) for token in tokens if _eh_atributo(token)]
        predicado = _Predicado(list(tokens), origem, de_juncao, referencias)
        simples = len(tokens) == 3 and tokens[1] in OPERADORES
        tabelas = predicado.tabelas
        if not tabelas:
            predicado.tipo = "constante"
        elif len(tabelas) == 1:
            predicado.tipo = "selecao"
        elif simples and len(referencias) == 2 and all(len(r.candidatos) == 1 for r in referencias):
            predicado.tipo = "juncao"
        else:
            predicado.tipo = "complexo"
        predicado.fator = self._seletividade(predicado, simples)
        return predicado

    def _eh_chave_primaria(self, referencia: _Referencia) -> bool:
        if len(referencia.candidatos) != 1:
            return False
        tabela, coluna = referencia.candidatos[0]
        colunas = self.schema[tabela]
        return bool(colunas) and coluna == colunas[0] and coluna.startswith("id")

    def _seletividade(self, predicado: _Predicado, simples: bool) -> float:
        if predicado.tipo == "constante":
            return 1.0
        if not simples:
            return SELETIVIDADE_COMPOSTA
        operador = predicado.tokens[1]
        if operador in ("<>", "!="):
            return SELETIVIDADE_DIFERENTE
        if operador != "=":
            return SELETIVIDADE_FAIXA
        if (predicado.tipo == "selecao" and len(predicado.referencias) == 1
                and self._eh_chave_primaria(predicado.referencias[0])):
            return SELETIVIDADE_CHAVE
        return SELETIVIDADE_IGUAL

    # --- utilidades ------------------------------------------------------
    def _nomes_tabelas(self, chaves: Iterable[str]) -> str:
        return ", ".join(self.nome_tabela[t] for t in chaves)

    def _nomes_atributos(self, atributos: Set[Atributo], ordem: List[str]) -> List[str]:
        def chave(atributo: Atributo) -> Tuple[int, int]:
            tabela, coluna = atributo
            colunas = self.schema[tabela]
            return ordem.index(tabela), colunas.index(coluna) if coluna in colunas else len(colunas)

        return [
            f"{self.nome_tabela[t]}.{self.nome_coluna.get((t, c), c)}"
            for t, c in sorted(atributos, key=chave)
        ]

    # --- heurística b.i: ordem das folhas ----------------------------------
    def _ordenar_folhas(self) -> Tuple[List[str], Set[str]]:
        posicao = {t: i for i, t in enumerate(self.chaves)}
        juncoes = [p for p in self.predicados if p.tipo == "juncao"]
        restantes = list(self.chaves)
        primeiro = min(restantes, key=lambda t: (self.fator_tabela[t], posicao[t]))
        ordem = [primeiro]
        restantes.remove(primeiro)
        produtos: Set[str] = set()

        while restantes:
            juntas = set(ordem)
            candidatos = []
            for t in restantes:
                ligacoes = [p.fator for p in juncoes if t in p.tabelas and (p.tabelas - {t}) <= juntas]
                if ligacoes:
                    candidatos.append((self.fator_tabela[t] * min(ligacoes), posicao[t], t))
            if candidatos:
                escolhida = min(candidatos)[2]
            else:
                escolhida = min(restantes, key=lambda t: (self.fator_tabela[t], posicao[t]))
                produtos.add(escolhida)
            ordem.append(escolhida)
            restantes.remove(escolhida)
        return ordem, produtos

    # --- heurísticas a.i e a.ii nas folhas ---------------------------------
    def _subarvore_folha(self, tabela: str, posicao: int, multi: bool, reordenado: bool,
                         necessarios: Set[Atributo], ordem: List[str]) -> Tuple[NoOperador, Set[Atributo]]:
        nome = self.nome_tabela[tabela]
        heuristicas = [H_TABELA]
        if reordenado:
            fator = self.fator_tabela[tabela]
            estimativa = "sem seleção própria" if fator == 1 else f"suas seleções deixam ≈ {_pct(fator)} das tuplas"
            heuristicas.append(
                f"b.i – Folhas reordenadas: {nome} é a {posicao}ª relação na ordem de junção ({estimativa})"
            )
        no = NoOperador("tabela", tabela=nome, heuristicas=heuristicas)
        disponiveis = {(tabela, coluna) for coluna in self.schema[tabela]}

        locais = self.locais[tabela]
        momento = "antes das junções" if multi else "o quanto antes"
        empate = len({p.fator for p in locais}) == 1
        for indice, predicado in enumerate(locais, 1):
            heuristicas = [
                f"a.i – Seleção empurrada para junto de {nome}: reduz o número de tuplas {momento} "
                f"(seletividade estimada: {_pct(predicado.fator)})"
            ]
            if len(locais) > 1:
                criterio = ("mesma restritividade estimada, mantida a ordem da consulta" if empate
                            else "da mais para a menos restritiva")
                heuristicas.append(
                    f"b – Seleções de {nome} em cascata ({criterio}): esta é a {indice}ª de {len(locais)}"
                )
            if predicado.de_juncao:
                heuristicas.append(
                    f"a.i – Condição veio do {predicado.origem}, mas só envolve {nome}: "
                    "aplicada como seleção antes da junção"
                )
            no = NoOperador("selecao", [no], condicao=list(predicado.tokens), heuristicas=heuristicas)

        if multi and not self.todos_atributos and necessarios and necessarios < disponiveis:
            nomes = self._nomes_atributos(necessarios, ordem)
            no = NoOperador("projecao", [no], atributos=nomes, heuristicas=[
                f"a.ii – Projeção antecipada em {nome}: mantém só {len(necessarios)} de "
                f"{len(disponiveis)} atributos (os usados no SELECT e nas condições seguintes)"
            ])
            self.log_projecoes.append(f"   • logo após {nome}: π {', '.join(nomes)}")
            disponiveis = set(necessarios)
        return no, disponiveis

    def _aplicar_selecoes_pendentes(self, atual: NoOperador, juntas: Set[str],
                                    pendentes: List[_Predicado], forcar: bool = False) -> NoOperador:
        aplicaveis = [
            p for p in pendentes
            if p.tipo in ("complexo", "constante") and (forcar or p.tabelas <= juntas)
        ]
        for predicado in sorted(aplicaveis, key=lambda p: p.fator):
            pendentes.remove(predicado)
            if predicado.tipo == "constante":
                heuristica = "Condição constante (não depende de atributos): aplicada uma única vez, no início"
            else:
                heuristica = (
                    f"a.i – Seleção que envolve {self._nomes_tabelas(sorted(predicado.tabelas, key=self.chaves.index))} "
                    "aplicada logo após a junção que disponibiliza seus atributos"
                )
            atual = NoOperador("selecao", [atual], condicao=list(predicado.tokens), heuristicas=[heuristica])
        return atual

    # --- heurísticas b.ii e b.iii: montagem da árvore ----------------------
    def _construir_arvore(self, ordem: List[str], produtos: Set[str]) -> NoOperador:
        multi = len(ordem) > 1
        reordenado = ordem != self.chaves
        pendentes = [p for p in self.predicados if p.tipo != "selecao"]
        finais = {atributo for r in self.refs_select for atributo in r.candidatos}

        def necessarios(juntas: Set[str]) -> Set[Atributo]:
            atributos = set(finais)
            for predicado in pendentes:
                atributos |= predicado.atributos
            return {a for a in atributos if a[0] in juntas}

        subarvores = {
            t: self._subarvore_folha(t, posicao, multi, reordenado, necessarios({t}), ordem)
            for posicao, t in enumerate(ordem, 1)
        }

        atual, disponiveis = subarvores[ordem[0]]
        juntas = {ordem[0]}
        atual = self._aplicar_selecoes_pendentes(atual, juntas, pendentes)

        for posicao, tabela in enumerate(ordem[1:], 2):
            nome = self.nome_tabela[tabela]
            direita, disponiveis_direita = subarvores[tabela]
            esquerda_texto = self.nome_tabela[ordem[0]] if posicao == 2 else "(resultado anterior)"
            juntas = juntas | {tabela}
            condicoes = [p for p in pendentes if p.tipo == "juncao" and p.tabelas <= juntas]
            for predicado in condicoes:
                pendentes.remove(predicado)
            filhos = [atual, direita]

            if condicoes:
                tokens: List[str] = []
                for predicado in condicoes:
                    if tokens:
                        tokens.append("AND")
                    tokens.extend(predicado.tokens)
                texto = formatar_condicao(tokens)
                heuristicas = [f"b.ii – Junção com condição ({texto}) no lugar de produto cartesiano"]
                do_where = [p.texto for p in condicoes if not p.de_juncao]
                if do_where:
                    heuristicas.append(
                        f"b.ii – Condição do WHERE ({'; '.join(do_where)}) combinada à junção: σ sobre × vira ⋈"
                    )
                if reordenado:
                    heuristicas.append(
                        f"b.i – Junção mais restritiva primeiro: {nome} entra na {posicao}ª posição da ordem de junção"
                    )
                if any(tipo_do_no(f) != "tabela" for f in filhos):
                    heuristicas.append("a – Junção recebe entradas já reduzidas por seleção/projeção")
                atual = NoOperador("juncao", filhos, condicao=tokens, heuristicas=heuristicas)
                self.log_juncoes.append(f"   • {esquerda_texto} ⋈ {nome} usando {texto}")
            else:
                atual = NoOperador("produto", filhos, heuristicas=[
                    f"b.ii – Atenção: não existe condição ligando {nome} às tabelas anteriores; "
                    "produto cartesiano inevitável"
                ])
                self.log_juncoes.append(
                    f"   • ATENÇÃO: {esquerda_texto} × {nome} — nenhuma condição liga {nome} às demais tabelas, "
                    "então o produto cartesiano não pôde ser evitado"
                )

            disponiveis = disponiveis | disponiveis_direita
            atual = self._aplicar_selecoes_pendentes(atual, juntas, pendentes)

            if posicao < len(ordem) and not self.todos_atributos:
                atributos = necessarios(juntas)
                if atributos and atributos < disponiveis:
                    descartados = self._nomes_atributos(disponiveis - atributos, ordem)
                    resumo = ", ".join(descartados) if len(descartados) <= 4 else f"{len(descartados)} atributos"
                    nomes = self._nomes_atributos(atributos, ordem)
                    atual = NoOperador("projecao", [atual], atributos=nomes, heuristicas=[
                        f"a.ii – Projeção após a junção: descarta {resumo}, que não são mais usados"
                    ])
                    self.log_projecoes.append(f"   • após a {posicao - 1}ª junção: π {', '.join(nomes)}")
                    disponiveis = atributos

        atual = self._aplicar_selecoes_pendentes(atual, set(self.chaves), pendentes, forcar=True)
        return NoOperador("projecao", [atual], atributos=list(self.select), heuristicas=[H_PROJECAO_FINAL])

    # --- relatório -------------------------------------------------------
    def _classificacao(self, predicado: _Predicado) -> str:
        tabelas = sorted(predicado.tabelas, key=self.chaves.index)
        if predicado.tipo == "selecao":
            return f"seleção sobre {self.nome_tabela[tabelas[0]]} (seletividade estimada {_pct(predicado.fator)})"
        if predicado.tipo == "juncao":
            return f"condição de junção {self.nome_tabela[tabelas[0]]} – {self.nome_tabela[tabelas[1]]}"
        if predicado.tipo == "complexo":
            return f"seleção sobre {self._nomes_tabelas(tabelas)} (depende de várias tabelas)"
        return "condição constante"

    def _relatorio(self, ordem: List[str]) -> List[str]:
        multi = len(ordem) > 1
        linhas = [
            f"1. Decomposição das condições (σ_{{c1 ∧ c2}} ≡ σ_{{c1}}(σ_{{c2}})): "
            f"{len(self.predicados)} condição(ões) simples"
        ]
        if self.predicados:
            linhas += [f"   • {p.texto}  [{p.origem}] → {self._classificacao(p)}" for p in self.predicados]
        else:
            linhas.append("   • a consulta não possui condições")

        momento = "antes das junções" if multi else "o quanto antes"
        linhas.append(f"2. [a.i] Seleções empurradas para junto das tabelas (reduzem tuplas {momento}):")
        com_selecao = [t for t in ordem if self.locais[t]]
        for t in com_selecao:
            locais = self.locais[t]
            cascata = " → ".join(f"σ {p.texto}" for p in locais)
            extra = ""
            if len(locais) > 1:
                extra = (" (mesma restritividade: ordem da consulta)" if len({p.fator for p in locais}) == 1
                         else " (mais restritiva primeiro)")
            linhas.append(f"   • {self.nome_tabela[t]}: {cascata}{extra}")
        if not com_selecao:
            linhas.append("   • nenhuma condição envolve uma única tabela")

        linhas.append("3. [b.i] Reordenação das folhas pela restritividade (% estimado de tuplas após as seleções):")
        if multi:
            linhas.append("   • " + " → ".join(
                f"{self.nome_tabela[t]} ({_pct(self.fator_tabela[t])})" for t in ordem
            ))
            if ordem != self.chaves:
                linhas.append(f"   • ordem original da consulta: {' → '.join(self.nome_tabela[t] for t in self.chaves)}")
            else:
                linhas.append("   • a ordem original da consulta já era a mais restritiva")
        else:
            linhas.append("   • consulta com uma única tabela: não há junções para reordenar")

        linhas.append("4. [b.ii] Junções com condição (evitam produto cartesiano):")
        linhas += self.log_juncoes or ["   • não há junções"]

        linhas.append("5. [a.ii] Projeções empurradas para baixo (reduzem atributos):")
        if self.todos_atributos:
            linhas.append("   • SELECT * — todos os atributos são necessários; projeções intermediárias não reduziriam nada")
        elif not multi:
            linhas.append("   • consulta com uma única tabela: a projeção final já ocorre logo após as seleções")
        else:
            linhas += self.log_projecoes or ["   • todos os atributos já são usados adiante; nenhuma projeção extra reduz atributos"]

        linhas.append(
            "6. [b.iii] Árvore ajustada: junções encadeadas à esquerda (left-deep), seleções e projeções "
            "junto às folhas e projeção final π na raiz"
        )
        for aviso in self.avisos:
            linhas.append(f"⚠ {aviso}")
        linhas.append(
            "Obs.: sem estatísticas do banco, a seletividade é estimada pelo padrão do System R — "
            "'=' 10%, '=' na chave primária ≈ 1 tupla (1%), '<>' 90%, '<' '>' '<=' '>=' 33%."
        )
        return linhas

    def executar(self) -> ResultadoOtimizacao:
        self.locais = {
            t: sorted(
                (p for p in self.predicados if p.tipo == "selecao" and p.tabelas == {t}),
                key=lambda p: p.fator,
            )
            for t in self.chaves
        }
        self.fator_tabela = {t: _produto(p.fator for p in self.locais[t]) for t in self.chaves}
        ordem, produtos = self._ordenar_folhas()
        arvore = self._construir_arvore(ordem, produtos)
        return ResultadoOtimizacao(
            arvore=arvore,
            algebra=arvore_para_algebra(arvore),
            heuristicas_aplicadas=self._relatorio(ordem),
            ordem_juncoes=[self.nome_tabela[t] for t in ordem],
        )


# ---------------------------------------------------------------------------
# Entradas aceitas
# ---------------------------------------------------------------------------
def _extrair_de_consulta(parsed: Dict[str, Any]):
    """Dicionário do HU1: main_table, joins [{table, on}], where_conditions, select_attributes."""
    tabelas = [parsed.get("main_table", "")]
    condicoes = []
    for join in parsed.get("joins") or []:
        tabelas.append(join.get("table", ""))
        tokens = tokens_condicao(join.get("on"))
        if tokens:
            condicoes.append((tokens, f"ON do JOIN {join.get('table', '')}", True))
    where = tokens_condicao(parsed.get("where_conditions") or [])
    if where:
        condicoes.append((where, "WHERE", False))
    select = list(parsed.get("select_attributes") or ["*"])
    return [t for t in tabelas if t], condicoes, select


def _extrair_de_arvore(raiz: Any):
    """Grafo original (HU3): coleta tabelas, condições e a projeção final para reconstruí-lo otimizado."""
    tabelas: List[str] = []
    condicoes = []
    select: Optional[List[str]] = None

    def visitar(no: Any) -> None:
        nonlocal select
        tipo = tipo_do_no(no)
        if tipo == "tabela":
            tabelas.append(_tabela_do_no(no))
        elif tipo == "projecao" and select is None:
            select = _atributos_do_no(no)
        elif tipo in ("selecao", "juncao"):
            tokens = tokens_condicao(_condicao_do_no(no))
            if tokens:
                origem = "σ do grafo original" if tipo == "selecao" else "⋈ do grafo original"
                condicoes.append((tokens, origem, tipo == "juncao"))
        for filho in filhos_do_no(no):
            visitar(filho)

    visitar(raiz)
    return tabelas, condicoes, select or ["*"]


def _schema_padrao() -> Dict[str, List[str]]:
    caminho = Path(__file__).resolve().parents[2] / "docs" / "schema.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def otimizar(entrada: Any, schema: Optional[Dict[str, List[str]]] = None) -> ResultadoOtimizacao:
    """
    Otimiza a consulta aplicando as heurísticas da HU4.

    entrada: dicionário retornado por SQLParserHU1.parse (HU1), grafo de operadores
             original (HU3: nós com tipo/filhos/...) ou o próprio texto SQL.
    schema:  {tabela: [atributos]}; por padrão usa docs/schema.json.
    """
    if entrada is None:
        raise ValueError("Nada para otimizar: informe a consulta do HU1 ou o grafo do HU3.")
    if isinstance(entrada, str):
        return otimizar_sql(entrada, schema)
    if schema is None:
        schema = _schema_padrao()
    schema_normalizado = {str(t).lower(): [str(c).lower() for c in colunas] for t, colunas in schema.items()}
    if isinstance(entrada, dict) and "main_table" in entrada:
        tabelas, condicoes, select = _extrair_de_consulta(entrada)
    else:
        tabelas, condicoes, select = _extrair_de_arvore(entrada)
    return _Otimizacao(schema_normalizado, tabelas, condicoes, select).executar()


def otimizar_sql(sql: str, schema: Optional[Dict[str, List[str]]] = None) -> ResultadoOtimizacao:
    """Atalho: valida o SQL com o parser do HU1 e otimiza o resultado."""
    if schema is None:
        schema = _schema_padrao()
    try:
        from src.HU1.parser import SQLParserHU1
    except ImportError:
        from HU1.parser import SQLParserHU1
    return otimizar(SQLParserHU1(schema).parse(sql), schema)


if __name__ == "__main__":
    import os
    import sys

    _src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _caminho in (_src, os.path.dirname(_src)):
        if _caminho not in sys.path:
            sys.path.insert(0, _caminho)

    consulta = " ".join(sys.argv[1:]) or (
        "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
        "WHERE ValorTotalPedido > 100"
    )
    print(f"SQL: {consulta}\n")
    print(otimizar_sql(consulta).relatorio())
