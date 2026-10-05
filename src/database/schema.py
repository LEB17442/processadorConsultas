import json
from typing import Dict, List, Optional, Set

# Mapeamento do modelo de dados conforme especificação do trabalho
DEFAULT_SCHEMA = {
    "Categoria": [
        "idCategoria", "Descricao"
    ],
    "Produto": [
        "idProduto", "Nome", "Descricao", "Preco", "QuantEstoque", "Categoria_idCategoria"
    ],
    "TipoCliente": [
        "idTipoCliente", "Descricao"
    ],
    "Cliente": [
        "idCliente", "Nome", "Email", "Nascimento", "Senha", "TipoCliente_idTipoCliente", "DataRegistro"
    ],
    "TipoEndereco": [
        "idTipoEndereco", "Descricao"
    ],
    "Endereco": [
        "idEndereco", "EnderecoPadrao", "Logradouro", "Numero", "Complemento", 
        "Bairro", "Cidade", "UF", "CEP", "TipoEndereco_idTipoEndereco", "Cliente_idCliente"
    ],
    "Telefone": [
        "Numero", "Cliente_idCliente"
    ],
    "Status": [
        "idStatus", "Descricao"
    ],
    "Pedido": [
        "idPedido", "Status_idStatus", "DataPedido", "ValorTotalPedido", "Cliente_idCliente"
    ],
    "Pedido_has_Produto": [
        "idPedidoProduto", "Pedido_idPedido", "Produto_idProduto", "Quantidade", "PrecoUnitario"
    ]
}

class DatabaseSchema:
    def __init__(self, schema_dict: Optional[Dict[str, List[str]]] = None):
        self.raw_schema = schema_dict if schema_dict else DEFAULT_SCHEMA
        
        # Mapeamento em minúsculas para validações case-insensitive (Regra de Negócio HU1)
        self.tables_lower: Dict[str, str] = {}  # ex: 'cliente' -> 'Cliente'
        self.attributes_lower: Dict[str, Dict[str, str]] = {}  # ex: 'cliente' -> {'nome': 'Nome', ...}

        self._build_index()

    def _build_index(self):
        for table, attributes in self.raw_schema.items():
            t_lower = table.lower()
            self.tables_lower[t_lower] = table
            self.attributes_lower[t_lower] = {attr.lower(): attr for attr in attributes}

    def table_exists(self, table_name: str) -> bool:
        """Verifica se a tabela existe no modelo relacional (case-insensitive)."""
        return table_name.lower() in self.tables_lower

    def get_real_table_name(self, table_name: str) -> Optional[str]:
        """Retorna o nome original da tabela com maiúsculas/minúsculas corretas."""
        return self.tables_lower.get(table_name.lower())

    def attribute_exists(self, table_name: str, attribute_name: str) -> bool:
        """Verifica se o atributo pertence à tabela informada (case-insensitive)."""
        t_lower = table_name.lower()
        if t_lower in self.attributes_lower:
            return attribute_name.lower() in self.attributes_lower[t_lower]
        return False

    def get_real_attribute_name(self, table_name: str, attribute_name: str) -> Optional[str]:
        """Retorna o nome original do atributo com maiúsculas/minúsculas corretas."""
        t_lower = table_name.lower()
        if t_lower in self.attributes_lower:
            return self.attributes_lower[t_lower].get(attribute_name.lower())
        return None

    def get_tables_containing_attribute(self, attribute_name: str) -> List[str]:
        """Retorna todas as tabelas do esquema que possuem um atributo com esse nome."""
        attr_lower = attribute_name.lower()
        matching_tables = []
        for t_lower, attrs in self.attributes_lower.items():
            if attr_lower in attrs:
                matching_tables.append(self.tables_lower[t_lower])
        return matching_tables