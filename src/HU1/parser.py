import re
from typing import Dict, List, Any, Tuple, Optional

class ParseError(Exception):
    def __init__(self, message: str, error_type: str):
        super().__init__(message)
        self.error_type = error_type  # 'Sintatico' ou 'Semantico'
        self.message = message

class SQLParserHU1:
    VALID_OPERATORS = ['<=', '>=', '<>', '=', '>', '<']
    KEYWORDS = {'SELECT', 'FROM', 'JOIN', 'ON', 'WHERE', 'AND'}

    def __init__(self, schema_data: Dict[str, List[str]]):
        # Mapeamento em minúsculas para validação case-insensitive
        self.schema = {table.lower(): [col.lower() for col in cols] for table, cols in schema_data.items()}
        self.raw_schema = schema_data

    def _normalize_query(self, query: str) -> str:
        """Remove quebras de linha e reduz espaços em branco repetidos."""
        query = re.sub(r'\s+', ' ', query.strip())
        return query

    def tokenize(self, query: str) -> List[str]:
        """Divide a consulta em tokens ignorando case mas mantendo a estrutura."""
        pattern = r"[a-zA-Z0-9_.]+|<=|>=|<>|[=><(),]"
        return re.findall(pattern, query)

    def parse(self, query: str) -> Dict[str, Any]:
        normalized = self._normalize_query(query)
        if not normalized:
            raise ParseError("A consulta SQL não pode estar vazia.", "Sintatico")

        tokens = self.tokenize(normalized)
        tokens_upper = [t.upper() for t in tokens]

        if not tokens or tokens_upper[0] != "SELECT":
            raise ParseError("Erro Sintático: A consulta deve iniciar obrigatoriamente com 'SELECT'.", "Sintatico")

        if "FROM" not in tokens_upper:
            raise ParseError("Erro Sintático: Cláusula 'FROM' obrigatória não encontrada.", "Sintatico")

        # Estrutura tratada para ser repassada às próximas HUs (HU2, HU3, etc.)
        parsed_result = {
            "select_attributes": [],
            "main_table": "",
            "joins": [],  # Lista de dicts: [{'table': ..., 'on': (left, op, right)}]
            "where_conditions": []
        }

        # --- 1. PROCESSAR E VALIDAR CLÁUSULA SELECT ---
        from_idx = tokens_upper.index("FROM")
        select_tokens = tokens[1:from_idx]
        if not select_tokens:
            raise ParseError("Erro Sintático: Nenhum atributo informado na cláusula 'SELECT'.", "Sintatico")

        select_raw = " ".join(select_tokens)
        attributes = [attr.strip() for attr in select_raw.split(",") if attr.strip()]
        if not attributes:
            raise ParseError("Erro Sintático: Lista de atributos inválida no 'SELECT'.", "Sintatico")

        # --- 2. PROCESSAR CLÁUSULAS E IDENTIFICAR TABELAS ---
        # Identificar onde terminam JOINs/WHERE
        where_idx = tokens_upper.index("WHERE") if "WHERE" in tokens_upper else len(tokens)
        from_and_joins_tokens = tokens[from_idx + 1:where_idx]
        
        if not from_and_joins_tokens:
            raise ParseError("Erro Sintático: Nenhuma tabela especificada após a cláusula 'FROM'.", "Sintatico")

        # Primeira tabela (Main Table)
        main_table = from_and_joins_tokens[0]
        if not self._table_exists(main_table):
            raise ParseError(f"Erro Semântico: Tabela '{main_table}' não existe no modelo relacional.", "Semantico")
        
        parsed_result["main_table"] = main_table
        active_tables = [main_table.lower()]

        # Processar múltiplos JOINs (se existirem)
        idx = 1
        while idx < len(from_and_joins_tokens):
            token_up = from_and_joins_tokens[idx].upper()
            if token_up == "JOIN":
                if idx + 1 >= len(from_and_joins_tokens):
                    raise ParseError("Erro Sintático: Nome da tabela ausente após 'JOIN'.", "Sintatico")
                
                join_table = from_and_joins_tokens[idx + 1]
                if not self._table_exists(join_table):
                    raise ParseError(f"Erro Semântico: Tabela '{join_table}' do JOIN não existe no banco.", "Semantico")

                if idx + 2 >= len(from_and_joins_tokens) or from_and_joins_tokens[idx + 2].upper() != "ON":
                    raise ParseError(f"Erro Sintático: Cláusula 'ON' esperada após 'JOIN {join_table}'.", "Sintatico")

                # Condição do ON (ex: Pedido.Cliente_idCliente = Cliente.idCliente)
                if idx + 5 >= len(from_and_joins_tokens):
                    raise ParseError(f"Erro Sintático: Condição incompleta na cláusula 'ON' do JOIN '{join_table}'.", "Sintatico")

                left_operand = from_and_joins_tokens[idx + 3]
                op = from_and_joins_tokens[idx + 4]
                right_operand = from_and_joins_tokens[idx + 5]

                if op not in self.VALID_OPERATORS:
                    raise ParseError(f"Erro Sintático: Operador '{op}' inválido na cláusula ON.", "Sintatico")

                active_tables.append(join_table.lower())
                parsed_result["joins"].append({
                    "table": join_table,
                    "on": (left_operand, op, right_operand)
                })
                idx += 6
            else:
                raise ParseError(f"Erro Sintático: Palavra-chave ou símbolo inesperado '{from_and_joins_tokens[idx]}'.", "Sintatico")

        # Semântica dos Atributos do SELECT
        for attr in attributes:
            self._validate_attribute(attr, active_tables)
            parsed_result["select_attributes"].append(attr)

        # --- 3. PROCESSAR CLÁUSULA WHERE (OPCIONAL) ---
        if where_idx < len(tokens):
            where_tokens = tokens[where_idx + 1:]
            if not where_tokens:
                raise ParseError("Erro Sintático: Cláusula 'WHERE' informada sem condições.", "Sintatico")
            # Validação básica de expressões no WHERE
            parsed_result["where_conditions"] = where_tokens

        return parsed_result

    def _table_exists(self, table_name: str) -> bool:
        return table_name.lower() in self.schema

    def _validate_attribute(self, attr_expression: str, active_tables: List[str]):
        """Valida se o atributo existe nas tabelas envolvidas na consulta."""
        if attr_expression == "*":
            return

        if "." in attr_expression:
            tbl, col = attr_expression.split(".", 1)
            if tbl.lower() not in active_tables:
                raise ParseError(f"Erro Semântico: Tabela '{tbl}' não está presente na cláusula FROM/JOIN.", "Semantico")
            if col.lower() not in self.schema.get(tbl.lower(), []):
                raise ParseError(f"Erro Semântico: Atributo '{col}' não existe na tabela '{tbl}'.", "Semantico")
        else:
            # Atributo sem prefixo de tabela: deve existir em pelo menos uma das tabelas ativas
            found = any(attr_expression.lower() in self.schema[t] for t in active_tables if t in self.schema)
            if not found:
                raise ParseError(f"Erro Semântico: Atributo '{attr_expression}' não pertence a nenhuma das tabelas da consulta.", "Semantico")