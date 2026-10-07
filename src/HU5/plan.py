"""
HU5 - Plano de Execução

Recebe o grafo de operadores OTIMIZADO (saída do HU4) e gera a ordem de execução
passo a passo, indicando em cada etapa qual heurística foi aplicada.

Contrato esperado para cada nó da árvore (objeto ou dict, chaves em pt ou en):
    tipo        -> 'tabela' | 'selecao' | 'projecao' | 'juncao' | 'produto'
                   (aceita também 'table', 'select', 'project', 'join', 'σ', 'π', '⋈', '×')
    filhos      -> lista de nós filhos (vazia nas folhas)        [ou 'children']
    tabela      -> nome da tabela, nas folhas                    [ou 'nome', 'label']
    condicao    -> condição da seleção/junção (str, lista ou tupla)
    atributos   -> atributos da projeção (lista ou str)
    heuristicas -> (opcional) heurísticas que o HU4 registrou no nó

Se o nó não trouxer 'heuristicas', o HU5 deduz a heurística pela posição do
operador na árvore (ex.: seleção logo acima da tabela = redução de tuplas).

A ordem de execução é um percurso pós-ordem (filhos antes do pai, esquerda
antes da direita): cada operador só executa depois que suas entradas existem,
e a raiz (projeção final) é sempre o último passo.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

TIPOS = {
    "tabela": "tabela", "table": "tabela", "relacao": "tabela", "relação": "tabela",
    "selecao": "selecao", "seleção": "selecao", "select": "selecao", "selection": "selecao", "σ": "selecao",
    "projecao": "projecao", "projeção": "projecao", "project": "projecao", "projection": "projecao", "π": "projecao",
    "juncao": "juncao", "junção": "juncao", "join": "juncao", "⋈": "juncao",
    "produto": "produto", "cartesiano": "produto", "product": "produto", "×": "produto",
}

NOMES = {
    "tabela": "Leitura de tabela",
    "selecao": "Seleção (σ)",
    "projecao": "Projeção (π)",
    "juncao": "Junção (⋈)",
    "produto": "Produto cartesiano (×)",
}

LOGICOS = {"AND": "∧", "OR": "∨"}

H_SELECAO = "a.i – Seleção empurrada para junto da tabela: reduz o número de tuplas antes das junções"
H_SELECAO_POS_JUNCAO = "a.i – Seleção aplicada logo após a junção que disponibiliza seus atributos"
H_PROJECAO = "a.ii – Projeção antecipada: mantém só os atributos usados adiante, reduzindo o tamanho das tuplas"
H_PROJECAO_FINAL = "Projeção final: retorna apenas os atributos pedidos no SELECT"
H_JUNCAO = "b.ii – Junção com condição (⋈) no lugar de produto cartesiano"
H_JUNCAO_REDUZIDA = "b.i/b.iii – Junção recebe entradas já reduzidas por seleção/projeção (mais restritiva primeiro)"
H_PRODUTO = "Atenção: produto cartesiano sem condição de junção – não foi possível evitá-lo"
H_TABELA = "Acesso à relação base (folha da árvore)"


@dataclass
class Passo:
    numero: int
    operacao: str
    expressao: str
    entradas: List[str]
    resultado: str
    heuristicas: List[str] = field(default_factory=list)

    def para_dict(self) -> Dict[str, Any]:
        return {
            "numero": self.numero,
            "operacao": self.operacao,
            "expressao": self.expressao,
            "entradas": list(self.entradas),
            "resultado": self.resultado,
            "heuristicas": list(self.heuristicas),
        }


def _campo(no: Any, *nomes: str) -> Any:
    for nome in nomes:
        if isinstance(no, dict):
            if no.get(nome) is not None:
                return no[nome]
        elif getattr(no, nome, None) is not None:
            return getattr(no, nome)
    return None


def _tipo(no: Any) -> str:
    bruto = _campo(no, "tipo", "type", "op", "operador")
    if bruto is None:
        raise ValueError(f"Nó sem tipo de operador: {no!r}")
    tipo = TIPOS.get(str(bruto).strip().lower())
    if tipo is None:
        raise ValueError(f"Tipo de operador desconhecido: {bruto!r}")
    return tipo


def _filhos(no: Any) -> List[Any]:
    return list(_campo(no, "filhos", "children") or [])


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, tuple) and len(valor) == 3:
        return f"{valor[0]} {valor[1]} {valor[2]}"
    return " ".join(LOGICOS.get(str(t).upper(), str(t)) for t in valor)


def _atributos(valor: Any) -> str:
    if valor is None:
        return "*"
    if isinstance(valor, str):
        return valor
    return ", ".join(str(a) for a in valor)


def _contem_reducao(no: Any) -> bool:
    """True se a subárvore tem alguma seleção ou projeção (entrada já reduzida)."""
    if _tipo(no) in ("selecao", "projecao"):
        return True
    return any(_contem_reducao(f) for f in _filhos(no))


def _deduzir_heuristicas(no: Any, eh_raiz: bool) -> List[str]:
    tipo = _tipo(no)
    filhos = _filhos(no)

    if tipo == "tabela":
        return [H_TABELA]

    if tipo == "selecao":
        abaixo = filhos[0] if filhos else None
        while abaixo is not None and _tipo(abaixo) == "selecao":
            abaixo = (_filhos(abaixo) or [None])[0]
        if abaixo is not None and _tipo(abaixo) in ("juncao", "produto"):
            return [H_SELECAO_POS_JUNCAO]
        return [H_SELECAO]

    if tipo == "projecao":
        return [H_PROJECAO_FINAL] if eh_raiz else [H_PROJECAO]

    if tipo == "juncao":
        heuristicas = [H_JUNCAO]
        if any(_contem_reducao(f) for f in filhos):
            heuristicas.append(H_JUNCAO_REDUZIDA)
        return heuristicas

    return [H_PRODUTO]


def _expressao(no: Any, tipo: str, entradas: List[str]) -> str:
    if tipo == "tabela":
        return str(_campo(no, "tabela", "nome", "label", "valor", "rotulo") or "?")
    if tipo == "selecao":
        return f"σ_{{{_texto(_campo(no, 'condicao', 'condition', 'predicado'))}}}({entradas[0]})"
    if tipo == "projecao":
        return f"π_{{{_atributos(_campo(no, 'atributos', 'attributes', 'colunas'))}}}({entradas[0]})"
    if tipo == "juncao":
        condicao = _texto(_campo(no, "condicao", "condition", "on"))
        return f"{entradas[0]} ⋈_{{{condicao}}} {entradas[1]}"
    return f"{entradas[0]} × {entradas[1]}"


def gerar_plano(arvore: Any) -> List[Passo]:
    """Percorre a árvore otimizada em pós-ordem e devolve os passos em ordem de execução."""
    if arvore is None:
        raise ValueError("Árvore de operadores vazia: execute a otimização (HU4) antes do plano.")

    passos: List[Passo] = []

    def visitar(no: Any, eh_raiz: bool) -> str:
        tipo = _tipo(no)
        filhos = _filhos(no)

        esperado = {"tabela": 0, "selecao": 1, "projecao": 1, "juncao": 2, "produto": 2}[tipo]
        if len(filhos) != esperado:
            raise ValueError(f"{NOMES[tipo]} deve ter {esperado} filho(s), mas tem {len(filhos)}.")

        entradas = [visitar(filho, False) for filho in filhos]

        heuristicas = _campo(no, "heuristicas", "heuristics")
        if isinstance(heuristicas, str):
            heuristicas = [heuristicas]
        if not heuristicas:
            heuristicas = _deduzir_heuristicas(no, eh_raiz)

        resultado = f"R{len(passos) + 1}"
        passos.append(Passo(
            numero=len(passos) + 1,
            operacao=NOMES[tipo],
            expressao=_expressao(no, tipo, entradas),
            entradas=entradas,
            resultado=resultado,
            heuristicas=list(heuristicas),
        ))
        return resultado

    visitar(arvore, True)
    return passos


def formatar_plano(passos: List[Passo]) -> str:
    """Texto pronto para exibir na interface gráfica."""
    linhas = ["PLANO DE EXECUÇÃO", "=" * 60]
    for passo in passos:
        linhas.append(f"Passo {passo.numero}: {passo.operacao}")
        linhas.append(f"    {passo.resultado} ← {passo.expressao}")
        for heuristica in passo.heuristicas:
            linhas.append(f"    ↳ Heurística: {heuristica}")
    if passos:
        linhas.append("=" * 60)
        linhas.append(f"Resultado final da consulta: {passos[-1].resultado}")
    return "\n".join(linhas)


def plano_execucao(arvore: Any, como_texto: bool = True) -> Any:
    """Atalho para a interface: texto formatado ou lista de dicts."""
    passos = gerar_plano(arvore)
    if como_texto:
        return formatar_plano(passos)
    return [p.para_dict() for p in passos]
