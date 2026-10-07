import json
from pathlib import Path
from typing import Any, Dict, List, Optional

LOGICOS = {"AND": "∧", "OR": "∨"}


def _formatar_condicao(tokens: List[str]) -> str:
    partes = []
    for token in tokens:
        partes.append(LOGICOS.get(token.upper(), token))
    return " ".join(partes)


def _formatar_on(on: Any) -> str:
    if isinstance(on, (tuple, list)) and len(on) == 3:
        return f"{on[0]} {on[1]} {on[2]}"
    return str(on)


def converter(parsed: Dict[str, Any]) -> str:
    tabela_principal = parsed.get("main_table", "")
    if not tabela_principal:
        raise ValueError("Consulta sem tabela principal (cláusula FROM).")

    expressao = tabela_principal
    joins = parsed.get("joins") or []
    for posicao, join in enumerate(joins):
        condicao = _formatar_on(join.get("on"))
        tabela = join.get("table", "")
        esquerda = f"({expressao})" if posicao > 0 else expressao
        expressao = f"{esquerda} ⋈_{{{condicao}}} {tabela}"

    condicoes = parsed.get("where_conditions") or []
    if condicoes:
        expressao = f"σ_{{{_formatar_condicao(condicoes)}}}({expressao})"

    atributos = parsed.get("select_attributes") or ["*"]
    lista = ", ".join(atributos)
    return f"π_{{{lista}}}({expressao})"


def _schema_padrao() -> Dict[str, List[str]]:
    caminho = Path(__file__).resolve().parents[2] / "docs" / "schema.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def converter_sql(sql: str, schema: Optional[Dict[str, List[str]]] = None) -> str:
    if schema is None:
        schema = _schema_padrao()
    try:
        from src.HU1.parser import SQLParserHU1
    except ImportError:
        from HU1.parser import SQLParserHU1
    parser = SQLParserHU1(schema)
    return converter(parser.parse(sql))
