"""
HU4 - Otimização da Consulta (heurísticas)

ÍNDICE — pesquise (Ctrl+F / lupa) pelo nome:
  otimizar                              OTIMIZAÇÃO: ponto de entrada chamado pela interface
  executar_otimizacao                   EXECUÇÃO: roteiro com todas as etapas, na ordem
  decompor_condicoes                    σ_{c1 ∧ c2} ≡ σ_{c1}(σ_{c2}): separa os AND
  estimar_restritividade                seletividade estimada de cada condição (System R)
  heuristica_reordenar_arvore           b.i   mais restritiva primeiro: ordem das folhas/junções
  heuristica_selecao_reduz_tuplas       a.i   σ desce para junto da tabela
  heuristica_selecao_apos_juncao        a.i   σ de várias tabelas logo após a junção
  heuristica_projecao_reduz_atributos   a.ii  π descarta atributos que não serão mais usados
  heuristica_evitar_produto_cartesiano  b.ii  ⋈ com condição no lugar de ×
  construir_arvore_otimizada            b.iii monta a árvore left-deep, π final na raiz
  gerar_relatorio_heuristicas           texto "HEURÍSTICAS APLICADAS" da interface
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

Atributo = Tuple[str, str]  # (tabela, coluna) em minúsculas
OPERADORES = ("=", "<>", "!=", "<", ">", "<=", ">=")
SIMBOLOS = {"tabela": "", "selecao": "σ", "projecao": "π", "juncao": "⋈", "produto": "×"}

# Restritividade estimada (padrão System R): fração das tuplas que passa na condição
SELETIVIDADE_CHAVE = 0.01       # atributo = valor, na chave primária (≈ 1 tupla)
SELETIVIDADE_IGUAL = 0.10       # atributo = valor
SELETIVIDADE_FAIXA = 1 / 3      # <, >, <=, >=
SELETIVIDADE_DIFERENTE = 0.90   # <>
SELETIVIDADE_COMPOSTA = 0.50    # condição composta (ex.: com OR)

H_TABELA = "Acesso à relação base (folha da árvore)"
H_PROJECAO_FINAL = "Projeção final: retorna apenas os atributos pedidos no SELECT"
_TOKENS = re.compile(r"'[^']*'|\"[^\"]*\"|<=|>=|<>|!=|∧|∨|[A-Za-z0-9_.@]+|[*=<>(),]")
_NUMERO = re.compile(r"^[+-]?\d+(\.\d+)?$")


# ============================================================================
# Estruturas de dados
# ============================================================================
@dataclass
class NoOperador:
    """Nó do grafo de operadores (contrato lido pelo HU5 e pela visualização)."""
    tipo: str                                    # 'tabela' | 'selecao' | 'projecao' | 'juncao' | 'produto'
    filhos: List["NoOperador"] = field(default_factory=list)
    tabela: Optional[str] = None                 # folhas
    condicao: Optional[List[str]] = None         # σ e ⋈
    atributos: Optional[List[str]] = None        # π
    heuristicas: List[str] = field(default_factory=list)

    def para_dict(self) -> Dict[str, Any]:
        dados = {"tipo": self.tipo, "tabela": self.tabela, "condicao": self.condicao, "atributos": self.atributos}
        dados = {k: (v if k in ("tipo", "tabela") else list(v)) for k, v in dados.items() if v is not None}
        return {**dados, "heuristicas": list(self.heuristicas), "filhos": [f.para_dict() for f in self.filhos]}


@dataclass
class ResultadoOtimizacao:
    arvore: NoOperador                 # entrada do HU5
    algebra: str                       # álgebra relacional otimizada
    heuristicas_aplicadas: List[str]
    ordem_juncoes: List[str]

    @property
    def texto_arvore(self) -> str:
        return arvore_para_texto(self.arvore)

    def relatorio(self) -> str:
        return "\n".join(["ÁLGEBRA RELACIONAL OTIMIZADA", self.algebra, "", "GRAFO DE OPERADORES OTIMIZADO",
                          self.texto_arvore, "", "HEURÍSTICAS APLICADAS", *self.heuristicas_aplicadas])

    def para_dict(self) -> Dict[str, Any]:
        return {"algebra": self.algebra, "ordem_juncoes": list(self.ordem_juncoes),
                "heuristicas_aplicadas": list(self.heuristicas_aplicadas), "arvore": self.arvore.para_dict()}


@dataclass
class Condicao:
    """Uma condição simples (já separada nos AND) e sua análise."""
    tokens: List[str]
    origem: str                      # 'WHERE' ou 'ON do JOIN X'
    do_join: bool
    refs: List[List[Atributo]]       # para cada atributo citado: onde ele pode estar
    tipo: str = "selecao"            # 'selecao' (1 tabela) | 'juncao' | 'complexo' | 'constante'
    fator: float = 1.0               # restritividade estimada (quanto menor, mais restritiva)

    @property
    def tabelas(self) -> Set[str]:
        return {t for ref in self.refs for t, _ in ref}

    @property
    def atributos(self) -> Set[Atributo]:
        return {a for ref in self.refs for a in ref}

    @property
    def texto(self) -> str:
        return formatar_condicao(self.tokens)


# ============================================================================
# Leitura e exibição de árvores (NoOperador, NoGrafo do HU3 ou dict)
# ============================================================================
def _campo(no: Any, nome: str) -> Any:
    return no.get(nome) if isinstance(no, dict) else getattr(no, nome, None)


def tipo_do_no(no: Any) -> str:
    tipo = str(_campo(no, "tipo")).strip().lower()
    if tipo not in SIMBOLOS:
        raise ValueError(f"Tipo de operador desconhecido: {tipo!r}")
    return tipo


def filhos_do_no(no: Any) -> List[Any]:
    return list(_campo(no, "filhos") or [])


def _atributos_do_no(no: Any) -> List[str]:
    valor = _campo(no, "atributos")
    if isinstance(valor, str):
        valor = [parte.strip() for parte in valor.split(",") if parte.strip()]
    return [str(a) for a in valor or []] or ["*"]


def _texto_atributos(atributos: Any) -> str:
    return atributos if isinstance(atributos, str) else ", ".join(str(a) for a in atributos)


def descricao_do_no(no: Any) -> str:
    """Rótulo curto do nó: 'π a, b', 'σ cond', '⋈ cond', '×' ou o nome da tabela."""
    tipo = tipo_do_no(no)
    if tipo == "tabela":
        return str(_campo(no, "tabela") or "?")
    if tipo == "produto":
        return "×"
    if tipo == "projecao":
        return f"π {_texto_atributos(_atributos_do_no(no))}"
    return f"{SIMBOLOS[tipo]} {formatar_condicao(_campo(no, 'condicao'))}"


def arvore_para_algebra(no: Any) -> str:
    """Árvore -> álgebra relacional (recursivo), no mesmo formato do HU2."""
    tipo, filhos = tipo_do_no(no), filhos_do_no(no)
    if tipo == "tabela":
        return str(_campo(no, "tabela") or "?")
    if tipo == "selecao":
        return f"σ_{{{formatar_condicao(_campo(no, 'condicao'))}}}({arvore_para_algebra(filhos[0])})"
    if tipo == "projecao":
        return f"π_{{{_texto_atributos(_atributos_do_no(no))}}}({arvore_para_algebra(filhos[0])})"
    esquerda, direita = (f"({arvore_para_algebra(f)})" if tipo_do_no(f) in ("juncao", "produto")
                         else arvore_para_algebra(f) for f in filhos[:2])
    if tipo == "juncao":
        return f"{esquerda} ⋈_{{{formatar_condicao(_campo(no, 'condicao'))}}} {direita}"
    return f"{esquerda} × {direita}"


def arvore_para_texto(raiz: Any) -> str:
    """Desenha a árvore em texto (raiz no topo, folhas = tabelas)."""
    linhas = [descricao_do_no(raiz)]

    def visitar(no: Any, prefixo: str) -> None:
        filhos = filhos_do_no(no)
        for i, filho in enumerate(filhos):
            ultimo = i == len(filhos) - 1
            linhas.append(f"{prefixo}{'└── ' if ultimo else '├── '}{descricao_do_no(filho)}")
            visitar(filho, prefixo + ("    " if ultimo else "│   "))

    visitar(raiz, "")
    return "\n".join(linhas)


# ============================================================================
# Condições
# ============================================================================
def tokens_condicao(condicao: Any) -> List[str]:
    """Texto, tupla (a, op, b) ou lista de tokens -> lista de tokens (∧/∨ viram AND/OR)."""
    if condicao is None:
        return []
    if not isinstance(condicao, str):
        condicao = " ".join(str(item) for item in condicao)
    return [{"∧": "AND", "∨": "OR"}.get(t, t) for t in _TOKENS.findall(condicao)]


def formatar_condicao(condicao: Any) -> str:
    """Tokens -> texto, trocando AND/OR por ∧/∨ (mesma notação do HU2)."""
    texto = " ".join({"AND": "∧", "OR": "∨"}.get(t.upper(), t) for t in tokens_condicao(condicao))
    return texto.replace("( ", "(").replace(" )", ")")


def _niveis(tokens: List[str]) -> List[int]:
    """Profundidade de parênteses depois de cada token."""
    nivel, niveis = 0, []
    for t in tokens:
        nivel += (t == "(") - (t == ")")
        niveis.append(nivel)
    return niveis


def decompor_condicoes(tokens: List[str]) -> List[List[str]]:
    """σ_{c1 ∧ c2 ∧ ...} ≡ σ_{c1}(σ_{c2}(...)): separa a condição nos AND fora de parênteses."""
    niveis = _niveis(tokens)
    if min(niveis, default=0) < 0 or (niveis and niveis[-1] != 0):
        raise ValueError(f"Parênteses desbalanceados na condição: {formatar_condicao(tokens)}")
    while len(tokens) >= 2 and tokens[0] == "(" and tokens[-1] == ")" and 0 not in _niveis(tokens)[:-1]:
        tokens = tokens[1:-1]                    # "(a AND b)" -> "a AND b"
    partes, atual = [], []
    for token, nivel in zip(tokens, _niveis(tokens)):
        if nivel == 0 and token.upper() == "AND":
            partes.append(atual)
            atual = []
        else:
            atual.append(token)
    partes.append(atual)
    if len(partes) == 1:
        return [atual] if atual else []
    if not all(partes):
        raise ValueError(f"Condição incompleta: 'AND' sem operando em {formatar_condicao(tokens)}")
    return [c for parte in partes for c in decompor_condicoes(parte)]   # cada parte pode ter parênteses


def _eh_atributo(token: str) -> bool:
    literal = (token[:1] in "'\"" and len(token) >= 2 and token[0] == token[-1]) \
        or _NUMERO.match(token) or token.upper() in ("NULL", "TRUE", "FALSE")
    return not (literal or token in OPERADORES or token in ("(", ")", ",") or token.upper() in ("AND", "OR", "NOT"))


def _pct(fator: float) -> str:
    valor = fator * 100
    if valor < 0.1:
        return "< 0,1%"
    return f"{valor:.0f}%" if valor >= 10 or valor == int(valor) else f"{valor:.1f}%".replace(".", ",")


# ============================================================================
# O otimizador
# ============================================================================
class Otimizador:
    def __init__(self, schema: Dict[str, List[str]], tabelas: List[str],
                 condicoes: List[Tuple[List[str], str, bool]], select: List[str]):
        self.schema = schema
        self.chaves: List[str] = []              # tabelas da consulta (minúsculas, ordem original)
        self.nome_tabela: Dict[str, str] = {}    # minúscula -> nome como foi escrito
        self.nome_coluna: Dict[Atributo, str] = {}
        self.avisos, self.log_juncoes, self.log_projecoes = [], [], []
        for nome in (str(n).strip() for n in tabelas):
            if nome.lower() not in schema:
                raise ValueError(f"Tabela '{nome}' não existe no modelo relacional.")
            if nome.lower() in self.nome_tabela:
                raise ValueError(f"A tabela '{nome}' aparece mais de uma vez na consulta "
                                 "(auto-junção sem alias não é suportada).")
            self.chaves.append(nome.lower())
            self.nome_tabela[nome.lower()] = nome
        if not self.chaves:
            raise ValueError("Consulta sem tabela (cláusula FROM).")
        self.select = [str(a).strip() for a in select or [] if str(a).strip()] or ["*"]
        self.todos_atributos = "*" in self.select
        self.atributos_select = {a for texto in self.select if texto != "*" for a in self._resolver_atributo(texto)}
        self.condicoes = [self.analisar_condicao(parte, origem, do_join)        # cada AND vira uma condição
                          for tokens, origem, do_join in condicoes for parte in decompor_condicoes(tokens)]

    # ------------------------------------------------------------------------
    def executar_otimizacao(self) -> ResultadoOtimizacao:
        """EXECUÇÃO da otimização: todas as etapas, na ordem."""
        # 1. seleções de cada tabela, da mais para a menos restritiva
        self.locais = {t: sorted((c for c in self.condicoes if c.tipo == "selecao" and c.tabelas == {t}),
                                 key=lambda c: c.fator) for t in self.chaves}
        # 2. fração estimada de tuplas que sobra de cada tabela depois das suas seleções
        self.fator_tabela = {t: math.prod(c.fator for c in self.locais[t]) for t in self.chaves}
        ordem = self.heuristica_reordenar_arvore()            # 3. b.i + b.ii
        arvore = self.construir_arvore_otimizada(ordem)       # 4. a.i, a.ii, b.ii, b.iii
        return ResultadoOtimizacao(arvore, arvore_para_algebra(arvore), self.gerar_relatorio_heuristicas(ordem),
                                   [self.nome_tabela[t] for t in ordem])

    # ------------------------------------------------------------------------
    def _resolver_atributo(self, texto: str) -> List[Atributo]:
        """'Tabela.coluna' ou 'coluna' -> lista de (tabela, coluna) onde o atributo pode estar."""
        if "." in texto:
            prefixo, coluna = texto.split(".", 1)
            if prefixo.lower() not in self.nome_tabela:
                raise ValueError(f"A tabela '{prefixo}' (em '{texto}') não está no FROM/JOIN da consulta.")
            if coluna.lower() not in self.schema[prefixo.lower()]:
                raise ValueError(f"O atributo '{coluna}' não existe na tabela '{self.nome_tabela[prefixo.lower()]}'.")
            candidatos = [(prefixo.lower(), coluna.lower())]
        else:
            coluna = texto
            candidatos = [(t, texto.lower()) for t in self.chaves if texto.lower() in self.schema[t]]
            if not candidatos:
                raise ValueError(f"O atributo '{texto}' não pertence a nenhuma tabela da consulta.")
            aviso = (f"Atributo '{texto}' é ambíguo (existe em {self._nomes(t for t, _ in candidatos)}): "
                     "tratado de forma conservadora — qualifique como Tabela.Atributo para otimizar melhor.")
            if len(candidatos) > 1 and aviso not in self.avisos:
                self.avisos.append(aviso)
        for atributo in candidatos:
            self.nome_coluna.setdefault(atributo, coluna)
        return candidatos

    def analisar_condicao(self, tokens: List[str], origem: str, do_join: bool) -> Condicao:
        """Classifica a condição pelo nº de tabelas que ela usa e estima sua restritividade."""
        c = Condicao(list(tokens), origem, do_join, [self._resolver_atributo(t) for t in tokens if _eh_atributo(t)])
        simples = len(tokens) == 3 and tokens[1] in OPERADORES           # formato "a op b"
        if not c.tabelas:
            c.tipo = "constante"
        elif len(c.tabelas) == 1:
            c.tipo = "selecao"                                            # 1 tabela: pode descer até ela
        elif simples and len(c.refs) == 2 and all(len(r) == 1 for r in c.refs):
            c.tipo = "juncao"                                             # Tabela1.x op Tabela2.y
        else:
            c.tipo = "complexo"                                           # várias tabelas: após a junção
        c.fator = self.estimar_restritividade(c, simples)
        return c

    def estimar_restritividade(self, c: Condicao, simples: bool) -> float:
        """Seletividade estimada (System R), já que não há estatísticas do banco."""
        if c.tipo == "constante":
            return 1.0
        if not simples:
            return SELETIVIDADE_COMPOSTA
        if c.tokens[1] in ("<>", "!="):
            return SELETIVIDADE_DIFERENTE
        if c.tokens[1] != "=":
            return SELETIVIDADE_FAIXA
        if c.tipo == "selecao" and len(c.refs) == 1 and len(c.refs[0]) == 1:
            tabela, coluna = c.refs[0][0]      # chave primária = 1ª coluna e começa com 'id'
            if coluna == self.schema[tabela][0] and coluna.startswith("id"):
                return SELETIVIDADE_CHAVE
        return SELETIVIDADE_IGUAL

    # ------------------------------------------------------------------------
    def heuristica_reordenar_arvore(self) -> List[str]:
        """b.i + b.ii: ordem das folhas (junções). Guloso: começa pela tabela mais restritiva; depois,
        entre as tabelas LIGADAS por condição de junção às que já entraram, pega a mais restritiva."""
        posicao = {t: i for i, t in enumerate(self.chaves)}
        juncoes = [c for c in self.condicoes if c.tipo == "juncao"]
        restantes = sorted(self.chaves, key=lambda t: (self.fator_tabela[t], posicao[t]))
        ordem = [restantes.pop(0)]
        while restantes:
            ligadas = []
            for t in restantes:
                fatores = [j.fator for j in juncoes if t in j.tabelas and j.tabelas - {t} <= set(ordem)]
                if fatores:
                    ligadas.append((self.fator_tabela[t] * min(fatores), posicao[t], t))
            escolhida = min(ligadas)[2] if ligadas else restantes[0]   # nenhuma ligada: × inevitável
            ordem.append(escolhida)
            restantes.remove(escolhida)
        return ordem

    def heuristica_selecao_reduz_tuplas(self, no: NoOperador, tabela: str, multi: bool) -> NoOperador:
        """a.i: cada seleção que usa só esta tabela vira um σ logo acima dela (a mais restritiva embaixo)."""
        nome, locais = self.nome_tabela[tabela], self.locais[tabela]
        empate = len({c.fator for c in locais}) == 1
        for i, c in enumerate(locais, 1):
            h = [f"a.i – Seleção empurrada para junto de {nome}: reduz o número de tuplas "
                 f"{'antes das junções' if multi else 'o quanto antes'} (seletividade estimada: {_pct(c.fator)})"]
            if len(locais) > 1:
                criterio = ("mesma restritividade estimada, mantida a ordem da consulta" if empate
                            else "da mais para a menos restritiva")
                h.append(f"b – Seleções de {nome} em cascata ({criterio}): esta é a {i}ª de {len(locais)}")
            if c.do_join:
                h.append(f"a.i – Condição veio do {c.origem}, mas só envolve {nome}: "
                         "aplicada como seleção antes da junção")
            no = NoOperador("selecao", [no], condicao=list(c.tokens), heuristicas=h)
        return no

    def heuristica_selecao_apos_juncao(self, no: NoOperador, juntas: Set[str], forcar: bool = False) -> NoOperador:
        """a.i: condição de várias tabelas vira σ logo após a junção que traz seus atributos."""
        prontas = [c for c in self.pendentes if c.tipo in ("complexo", "constante") and (forcar or c.tabelas <= juntas)]
        for c in sorted(prontas, key=lambda c: c.fator):
            self.pendentes.remove(c)
            h = ("Condição constante (não depende de atributos): aplicada uma única vez, no início"
                 if c.tipo == "constante" else
                 f"a.i – Seleção que envolve {self._nomes(sorted(c.tabelas, key=self.chaves.index))} "
                 "aplicada logo após a junção que disponibiliza seus atributos")
            no = NoOperador("selecao", [no], condicao=list(c.tokens), heuristicas=[h])
        return no

    def heuristica_projecao_reduz_atributos(self, no: NoOperador, usados: Set[Atributo], disponiveis: Set[Atributo],
                                            ordem: List[str], tabela: str = "", juncao: int = 0):
        """a.ii: π que mantém só os atributos ainda usados; só é criado se descartar algum."""
        if self.todos_atributos or not usados or not usados < disponiveis:
            return no, disponiveis
        nomes = self._nomes_atributos(usados, ordem)
        if tabela:      # logo acima da tabela
            h = (f"a.ii – Projeção antecipada em {self.nome_tabela[tabela]}: mantém só {len(usados)} de "
                 f"{len(disponiveis)} atributos (os usados no SELECT e nas condições seguintes)")
            self.log_projecoes.append(f"   • logo após {self.nome_tabela[tabela]}: π {', '.join(nomes)}")
        else:           # logo após a junção
            descartados = self._nomes_atributos(disponiveis - usados, ordem)
            resumo = ", ".join(descartados) if len(descartados) <= 4 else f"{len(descartados)} atributos"
            h = f"a.ii – Projeção após a junção: descarta {resumo}, que não são mais usados"
            self.log_projecoes.append(f"   • após a {juncao}ª junção: π {', '.join(nomes)}")
        return NoOperador("projecao", [no], atributos=nomes, heuristicas=[h]), set(usados)

    def heuristica_evitar_produto_cartesiano(self, esquerda: NoOperador, direita: NoOperador, tabela: str,
                                             posicao: int, ordem: List[str], juntas: Set[str]) -> NoOperador:
        """b.ii: junta com ⋈ usando as condições que ligam a tabela às anteriores; × só se não houver nenhuma."""
        nome = self.nome_tabela[tabela]
        anterior = self.nome_tabela[ordem[0]] if posicao == 2 else "(resultado anterior)"
        ligacoes = [c for c in self.pendentes if c.tipo == "juncao" and c.tabelas <= juntas]
        for c in ligacoes:
            self.pendentes.remove(c)
        if not ligacoes:
            self.log_juncoes.append(f"   • ATENÇÃO: {anterior} × {nome} — nenhuma condição liga {nome} às "
                                    "demais tabelas, então o produto cartesiano não pôde ser evitado")
            return NoOperador("produto", [esquerda, direita], heuristicas=[
                f"b.ii – Atenção: não existe condição ligando {nome} às tabelas anteriores; "
                "produto cartesiano inevitável"])
        tokens = [t for i, c in enumerate(ligacoes) for t in (["AND"] if i else []) + c.tokens]
        texto = formatar_condicao(tokens)
        h = [f"b.ii – Junção com condição ({texto}) no lugar de produto cartesiano"]
        do_where = [c.texto for c in ligacoes if not c.do_join]
        if do_where:
            h.append(f"b.ii – Condição do WHERE ({'; '.join(do_where)}) combinada à junção: σ sobre × vira ⋈")
        if ordem != self.chaves:
            h.append(f"b.i – Junção mais restritiva primeiro: {nome} entra na {posicao}ª posição da ordem de junção")
        if esquerda.tipo != "tabela" or direita.tipo != "tabela":
            h.append("a – Junção recebe entradas já reduzidas por seleção/projeção")
        self.log_juncoes.append(f"   • {anterior} ⋈ {nome} usando {texto}")
        return NoOperador("juncao", [esquerda, direita], condicao=tokens, heuristicas=h)

    def construir_arvore_otimizada(self, ordem: List[str]) -> NoOperador:
        """b.iii: monta a árvore left-deep na ordem decidida, com σ e π junto às folhas e π final na raiz."""
        self.pendentes = [c for c in self.condicoes if c.tipo != "selecao"]   # junções e condições complexas
        multi = len(ordem) > 1
        folhas = {}
        for posicao, t in enumerate(ordem, 1):          # subárvore de cada tabela: tabela -> σ -> π
            h = [H_TABELA]
            if ordem != self.chaves:
                fator = self.fator_tabela[t]
                estimativa = "sem seleção própria" if fator == 1 else f"suas seleções deixam ≈ {_pct(fator)} das tuplas"
                h.append(f"b.i – Folhas reordenadas: {self.nome_tabela[t]} é a {posicao}ª relação "
                         f"na ordem de junção ({estimativa})")
            no = self.heuristica_selecao_reduz_tuplas(NoOperador("tabela", tabela=self.nome_tabela[t], heuristicas=h), t, multi)
            disponiveis = {(t, coluna) for coluna in self.schema[t]}
            if multi:
                no, disponiveis = self.heuristica_projecao_reduz_atributos(
                    no, self._necessarios({t}), disponiveis, ordem, tabela=t)
            folhas[t] = (no, disponiveis)

        atual, disponiveis = folhas[ordem[0]]
        juntas = {ordem[0]}
        atual = self.heuristica_selecao_apos_juncao(atual, juntas)
        for posicao, t in enumerate(ordem[1:], 2):     # junta uma tabela por vez (left-deep)
            direita, disponiveis_direita = folhas[t]
            juntas = juntas | {t}
            atual = self.heuristica_evitar_produto_cartesiano(atual, direita, t, posicao, ordem, juntas)
            disponiveis = disponiveis | disponiveis_direita
            atual = self.heuristica_selecao_apos_juncao(atual, juntas)
            if posicao < len(ordem):                   # após a última junção, o π final já resolve
                atual, disponiveis = self.heuristica_projecao_reduz_atributos(
                    atual, self._necessarios(juntas), disponiveis, ordem, juncao=posicao - 1)
        atual = self.heuristica_selecao_apos_juncao(atual, set(self.chaves), forcar=True)
        return NoOperador("projecao", [atual], atributos=list(self.select), heuristicas=[H_PROJECAO_FINAL])

    # ------------------------------------------------------------------------
    def _necessarios(self, juntas: Set[str]) -> Set[Atributo]:
        """Atributos do SELECT + das condições ainda não aplicadas, das tabelas já juntadas."""
        return {a for a in self.atributos_select.union(*(c.atributos for c in self.pendentes)) if a[0] in juntas}

    def _nomes(self, chaves) -> str:
        return ", ".join(self.nome_tabela[t] for t in chaves)

    def _nomes_atributos(self, atributos: Set[Atributo], ordem: List[str]) -> List[str]:
        ordenados = sorted(atributos, key=lambda a: (ordem.index(a[0]), self.schema[a[0]].index(a[1])))
        return [f"{self.nome_tabela[t]}.{self.nome_coluna.get((t, c), c)}" for t, c in ordenados]

    def gerar_relatorio_heuristicas(self, ordem: List[str]) -> List[str]:
        """Texto 'HEURÍSTICAS APLICADAS' exibido na janela da HU4."""
        multi, n = len(ordem) > 1, self.nome_tabela

        def classificar(c: Condicao) -> str:
            ts = sorted(c.tabelas, key=self.chaves.index)
            if c.tipo == "selecao":
                return f"seleção sobre {n[ts[0]]} (seletividade estimada {_pct(c.fator)})"
            if c.tipo == "juncao":
                return f"condição de junção {n[ts[0]]} – {n[ts[1]]}"
            return f"seleção sobre {self._nomes(ts)} (depende de várias tabelas)" if c.tipo == "complexo" \
                else "condição constante"

        linhas = [f"1. Decomposição das condições (σ_{{c1 ∧ c2}} ≡ σ_{{c1}}(σ_{{c2}})): "
                  f"{len(self.condicoes)} condição(ões) simples"]
        linhas += [f"   • {c.texto}  [{c.origem}] → {classificar(c)}" for c in self.condicoes] \
            or ["   • a consulta não possui condições"]
        linhas.append(f"2. [a.i] Seleções empurradas para junto das tabelas (reduzem tuplas "
                      f"{'antes das junções' if multi else 'o quanto antes'}):")
        for t in (t for t in ordem if self.locais[t]):
            locais = self.locais[t]
            extra = "" if len(locais) == 1 else (" (mesma restritividade: ordem da consulta)"
                                                 if len({c.fator for c in locais}) == 1 else " (mais restritiva primeiro)")
            linhas.append(f"   • {n[t]}: {' → '.join(f'σ {c.texto}' for c in locais)}{extra}")
        if not any(self.locais.values()):
            linhas.append("   • nenhuma condição envolve uma única tabela")
        linhas.append("3. [b.i] Reordenação das folhas pela restritividade (% estimado de tuplas após as seleções):")
        if not multi:
            linhas.append("   • consulta com uma única tabela: não há junções para reordenar")
        else:
            linhas.append("   • " + " → ".join(f"{n[t]} ({_pct(self.fator_tabela[t])})" for t in ordem))
            linhas.append(f"   • ordem original da consulta: {' → '.join(n[t] for t in self.chaves)}"
                          if ordem != self.chaves else "   • a ordem original da consulta já era a mais restritiva")
        linhas += ["4. [b.ii] Junções com condição (evitam produto cartesiano):",
                   *(self.log_juncoes or ["   • não há junções"]),
                   "5. [a.ii] Projeções empurradas para baixo (reduzem atributos):"]
        if self.todos_atributos:
            linhas.append("   • SELECT * — todos os atributos são necessários; "
                          "projeções intermediárias não reduziriam nada")
        elif not multi:
            linhas.append("   • consulta com uma única tabela: a projeção final já ocorre logo após as seleções")
        else:
            linhas += self.log_projecoes or ["   • todos os atributos já são usados adiante; "
                                             "nenhuma projeção extra reduz atributos"]
        return linhas + [
            "6. [b.iii] Árvore ajustada: junções encadeadas à esquerda (left-deep), seleções e projeções "
            "junto às folhas e projeção final π na raiz",
            *(f"⚠ {aviso}" for aviso in self.avisos),
            "Obs.: sem estatísticas do banco, a seletividade é estimada pelo padrão do System R — "
            "'=' 10%, '=' na chave primária ≈ 1 tupla (1%), '<>' 90%, '<' '>' '<=' '>=' 33%."]


# ============================================================================
# Entradas aceitas e funções públicas
# ============================================================================
def _extrair_de_consulta(parsed: Dict[str, Any]):
    """Dicionário do HU1: main_table, joins [{table, on}], where_conditions, select_attributes."""
    joins = parsed.get("joins") or []
    tabelas = [parsed.get("main_table", "")] + [j.get("table", "") for j in joins]
    condicoes = [(tokens_condicao(j.get("on")), f"ON do JOIN {j.get('table', '')}", True) for j in joins]
    condicoes.append((tokens_condicao(parsed.get("where_conditions") or []), "WHERE", False))
    return [t for t in tabelas if t], [c for c in condicoes if c[0]], list(parsed.get("select_attributes") or ["*"])


def _extrair_de_arvore(raiz: Any):
    """Grafo original (HU3): coleta tabelas, condições e a projeção final."""
    tabelas, condicoes, select = [], [], []

    def visitar(no: Any) -> None:
        tipo, tokens = tipo_do_no(no), tokens_condicao(_campo(no, "condicao"))
        if tipo == "tabela":
            tabelas.append(str(_campo(no, "tabela") or "?"))
        elif tipo == "projecao" and not select:
            select.extend(_atributos_do_no(no))
        elif tipo in ("selecao", "juncao") and tokens:
            condicoes.append((tokens, f"{SIMBOLOS[tipo]} do grafo original", tipo == "juncao"))
        for filho in filhos_do_no(no):
            visitar(filho)

    visitar(raiz)
    return tabelas, condicoes, select or ["*"]


def _schema_padrao() -> Dict[str, List[str]]:
    return json.loads((Path(__file__).resolve().parents[2] / "docs" / "schema.json").read_text(encoding="utf-8"))


def otimizar(entrada: Any, schema: Optional[Dict[str, List[str]]] = None) -> ResultadoOtimizacao:
    """OTIMIZAÇÃO — ponto de entrada (chamado pela interface). entrada: dict do HU1, grafo do HU3 ou SQL."""
    if entrada is None:
        raise ValueError("Nada para otimizar: informe a consulta do HU1 ou o grafo do HU3.")
    if isinstance(entrada, str):
        return otimizar_sql(entrada, schema)
    schema = {str(t).lower(): [str(c).lower() for c in cols] for t, cols in (schema or _schema_padrao()).items()}
    extrair = _extrair_de_consulta if isinstance(entrada, dict) and "main_table" in entrada else _extrair_de_arvore
    return Otimizador(schema, *extrair(entrada)).executar_otimizacao()


def otimizar_sql(sql: str, schema: Optional[Dict[str, List[str]]] = None) -> ResultadoOtimizacao:
    """Atalho: valida o SQL com o parser do HU1 e otimiza o resultado."""
    schema = schema or _schema_padrao()
    try:
        from src.HU1.parser import SQLParserHU1
    except ImportError:
        from HU1.parser import SQLParserHU1
    return otimizar(SQLParserHU1(schema).parse(sql), schema)


if __name__ == "__main__":
    import sys

    sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2])]
    consulta = " ".join(sys.argv[1:]) or (
        "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente WHERE ValorTotalPedido > 100")
    print(f"SQL: {consulta}\n")
    print(otimizar_sql(consulta).relatorio())