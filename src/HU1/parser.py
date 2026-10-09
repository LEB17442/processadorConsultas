import re
from typing import Dict, List, Any

class ParseError(Exception):
    def __init__(self, message: str, error_type: str):
        super().__init__(message)
        self.error_type = error_type  # 'Sintatico' ou 'Semantico'
        self.message = message

class SQLParserHU1:
    # Operadores válidos conforme especificação do enunciado da HU1
    VALID_OPERATORS = ['<=', '>=', '<>', '=', '>', '<']
    ALLOWED_WHERE_TOKENS = VALID_OPERATORS + ['AND', '(', ')']
    KEYWORDS = {'SELECT', 'FROM', 'JOIN', 'ON', 'WHERE', 'AND'}

    def __init__(self, schema_data: Dict[str, List[str]]):
        self.schema = {table.lower(): [col.lower() for col in cols] for table, cols in schema_data.items()}
        self.raw_schema = schema_data

    def _normalize_query(self, query: str) -> str:
        return re.sub(r'\s+', ' ', query.strip())

    def tokenize(self, query: str) -> List[str]:
        """
        Tokeniza a consulta suportando:
        - Aspas e e-mails (@)
        - Caractere asterisco (*) para SELECT *
        - Operadores e delimitadores
        """
        pattern = r"'[^']*'|\"[^\"]*\"|<=|>=|<>|[a-zA-Z0-9_.@]+|[\*=><\(\),]"
        return re.findall(pattern, query)

    def parse(self, query: str) -> Dict[str, Any]:
        normalized = self._normalize_query(query)
        if not normalized:
            raise ParseError("A consulta SQL não pode estar vazia.", "Sintatico")

        tokens = self.tokenize(normalized)
        tokens_upper = [t.upper() for t in tokens]

        if not tokens or tokens_upper[0] != "SELECT":
            raise ParseError("Erro Sintático: A consulta deve iniciar com 'SELECT'.", "Sintatico")

        if "FROM" not in tokens_upper:
            raise ParseError("Erro Sintático: Cláusula 'FROM' obrigatória não encontrada.", "Sintatico")

        parsed_result = {
            "select_attributes": [],
            "main_table": "",
            "joins": [],
            "where_conditions": []
        }

        # --- 1. PROCESSAR E VALIDAR SELECT ---
        from_idx = tokens_upper.index("FROM")
        select_tokens = tokens[1:from_idx]
        if not select_tokens:
            raise ParseError("Erro Sintático: Nenhum atributo informado na cláusula 'SELECT'.", "Sintatico")

        select_raw = " ".join(select_tokens)
        attributes = [attr.strip() for attr in select_raw.split(",") if attr.strip()]

        # --- 2. PROCESSAR FROM E JOINS ---
        where_idx = tokens_upper.index("WHERE") if "WHERE" in tokens_upper else len(tokens)
        from_and_joins_tokens = tokens[from_idx + 1:where_idx]

        if not from_and_joins_tokens:
            raise ParseError("Erro Sintático: Nenhuma tabela especificada após 'FROM'.", "Sintatico")

        main_table = from_and_joins_tokens[0]
        if not self._table_exists(main_table):
            raise ParseError(f"Erro Semântico: Tabela '{main_table}' não existe no modelo relacional.", "Semantico")

        parsed_result["main_table"] = main_table
        active_tables = [main_table.lower()]

        # Processar JOINs
        idx = 1
        while idx < len(from_and_joins_tokens):
            token_up = from_and_joins_tokens[idx].upper()
            if token_up == "JOIN":
                if idx + 1 >= len(from_and_joins_tokens):
                    raise ParseError("Erro Sintático: Nome da tabela ausente após 'JOIN'.", "Sintatico")
                
                join_table = from_and_joins_tokens[idx + 1]
                if not self._table_exists(join_table):
                    raise ParseError(f"Erro Semântico: Tabela '{join_table}' do JOIN não existe.", "Semantico")

                if idx + 2 >= len(from_and_joins_tokens) or from_and_joins_tokens[idx + 2].upper() != "ON":
                    raise ParseError(f"Erro Sintático: Cláusula 'ON' esperada após 'JOIN {join_table}'.", "Sintatico")

                if idx + 5 >= len(from_and_joins_tokens):
                    raise ParseError(f"Erro Sintático: Condição incompleta no 'ON' do JOIN '{join_table}'.", "Sintatico")

                left_op = from_and_joins_tokens[idx + 3]
                op = from_and_joins_tokens[idx + 4]
                right_op = from_and_joins_tokens[idx + 5]

                if op not in self.VALID_OPERATORS:
                    raise ParseError(f"Erro Sintático: Operador '{op}' inválido na cláusula ON.", "Sintatico")

                active_tables.append(join_table.lower())
                parsed_result["joins"].append({
                    "table": join_table,
                    "on": (left_op, op, right_op)
                })
                idx += 6
            else:
                raise ParseError(f"Erro Sintático: Token inesperado '{from_and_joins_tokens[idx]}'.", "Sintatico")

        # Validação semântica dos atributos do SELECT
        for attr in attributes:
            if attr != "*":
                self._validate_attribute(attr, active_tables)
            parsed_result["select_attributes"].append(attr)

        # --- 3. PROCESSAR E VALIDAR WHERE ---
        if where_idx < len(tokens):
            where_tokens = tokens[where_idx + 1:]
            if not where_tokens:
                raise ParseError("Erro Sintático: Cláusula 'WHERE' informada sem condições.", "Sintatico")

            self._validate_where_clause(where_tokens, active_tables)
            parsed_result["where_conditions"] = where_tokens

        return parsed_result

    def _table_exists(self, table_name: str) -> bool:
        return table_name.lower() in self.schema

    def _validate_attribute(self, attr_expression: str, active_tables: List[str]):
        if attr_expression == "*":
            return

        if "." in attr_expression:
            tbl, col = attr_expression.split(".", 1)
            if tbl.lower() not in active_tables:
                raise ParseError(f"Erro Semântico: Tabela '{tbl}' não está no FROM/JOIN.", "Semantico")
            if col.lower() not in self.schema.get(tbl.lower(), []):
                raise ParseError(f"Erro Semântico: Atributo '{col}' não existe na tabela '{tbl}'.", "Semantico")
        else:
            found = any(attr_expression.lower() in self.schema[t] for t in active_tables if t in self.schema)
            if not found:
                raise ParseError(f"Erro Semântico: Atributo '{attr_expression}' não pertence às tabelas da consulta.", "Semantico")

    def _validate_where_clause(self, where_tokens: List[str], active_tables: List[str]):
        """Valida operadores e atributos utilizados na cláusula WHERE."""
        for token in where_tokens:
            token_up = token.upper()

            # Pula strings literais, números e operadores válidos
            if (token.startswith("'") and token.endswith("'")) or \
               (token.startswith('"') and token.endswith('"')) or \
               token.isdigit() or \
               token_up in self.ALLOWED_WHERE_TOKENS:
                continue

            # Se for um identificador (possível coluna)
            if re.match(r"^[a-zA-Z0-9_.]+$", token):
                self._validate_attribute(token, active_tables)
            else:
                # Caso encontre operadores inválidos (ex: %, +, /)
                raise ParseError(f"Erro Sintático: Operador ou símbolo '{token}' inválido no WHERE.", "Sintatico")