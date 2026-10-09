import json
import os
import sys
import tkinter as tk
from tkinter import messagebox

# Adiciona diretórios ao sys.path para garantir importações em qualquer SO
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)

for path in [BASE_DIR, ROOT_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

try:
    from HU1.parser import SQLParserHU1, ParseError
except ImportError:
    from src.HU1.parser import SQLParserHU1, ParseError


class AppHU1:
    def __init__(self, root):
        self.root = root
        self.root.title("Processador de Consultas SQL - HU1")
        self.root.geometry("800x650")
        self.root.configure(bg="#f0f0f0")

        # Localizar e carregar o schema.json
        schema_path = os.path.join(ROOT_DIR, "docs", "schema.json")
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                self.schema = json.load(f)
            self.parser = SQLParserHU1(self.schema)
        except Exception as e:
            messagebox.showerror("Erro de Schema", f"Não foi possível carregar o schema:\n{e}")
            self.schema = {}
            self.parser = None

        self._build_ui()

    def _build_ui(self):
        main_frame = tk.Frame(self.root, bg="#f0f0f0", padx=15, pady=15)
        main_frame.pack(fill="both", expand=True)

        # 1. Entrada SQL
        lbl_input = tk.Label(
            main_frame, text="Digite a consulta SQL:", font=("Arial", 11, "bold"), bg="#f0f0f0", anchor="w"
        )
        lbl_input.pack(fill="x", pady=(0, 5))

        self.txt_sql = tk.Text(
            main_frame, height=6, font=("Menlo" if sys.platform == "darwin" else "Consolas", 11),
            bg="#ffffff", fg="#000000", bd=1, relief="solid"
        )
        self.txt_sql.pack(fill="x", pady=5)

        # Consulta padrão para testes
        default_sql = (
            "SELECT Cliente.Nome, Pedido.ValorTotalPedido\n"
            "FROM Cliente\n"
            "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente\n"
            "WHERE ValorTotalPedido > 100"
        )
        self.txt_sql.insert("1.0", default_sql)

        # 2. Botão "Analisar" (Critério de Aceitação da HU1)
        btn_frame = tk.Frame(main_frame, bg="#f0f0f0")
        btn_frame.pack(fill="x", pady=10)

        btn_analyze = tk.Button(
            btn_frame,
            text=" [ ANALISAR CONSULTA ] ",
            command=self.on_analyze,
            font=("Arial", 11, "bold"),
            bg="#007bff",
            fg="black" if sys.platform == "darwin" else "white",
            bd=2,
            relief="raised",
            cursor="hand2"
        )
        btn_analyze.pack(side="right", padx=5)

        # 3. Label de Status
        self.lbl_status = tk.Label(
            main_frame, text="Status: Aguardando análise...", font=("Arial", 10, "italic"),
            bg="#f0f0f0", fg="#333333", anchor="w"
        )
        self.lbl_status.pack(fill="x", pady=5)

        # 4. Campo de Saída/Resultado
        lbl_output = tk.Label(
            main_frame, text="Resultado da Análise Sintática/Semântica:", font=("Arial", 11, "bold"),
            bg="#f0f0f0", anchor="w"
        )
        lbl_output.pack(fill="x", pady=(15, 5))

        self.txt_output = tk.Text(
            main_frame, height=12, font=("Menlo" if sys.platform == "darwin" else "Consolas", 10),
            bg="#ffffff", fg="#000000", bd=1, relief="solid"
        )
        self.txt_output.pack(fill="both", expand=True, pady=(5, 0))

    def on_analyze(self):
        print("--> Evento de clique acionado!")

        if not self.parser:
            self._display_output("❌ Erro: Parser não inicializado (falha no schema.json).")
            return

        sql_query = self.txt_sql.get("1.0", tk.END).strip()
        print(f"--> Analisando SQL: {repr(sql_query)}")

        try:
            result = self.parser.parse(sql_query)
            self.lbl_status.config(text="Status: ✅ Consulta Válida (Sintaxe e Semântica OK)", fg="green")
            formatted_json = json.dumps(result, indent=4, ensure_ascii=False)
            self._display_output(f"--- ESTRUTURA PARSEADA COM SUCESSO ---\n\n{formatted_json}")

        except ParseError as pe:
            self.lbl_status.config(text=f"Status: ❌ Erro {pe.error_type} Detectado", fg="red")
            self._display_output(f"❌ [ERRO {pe.error_type.upper()}]\n{pe.message}")

        except Exception as e:
            self.lbl_status.config(text="Status: ❌ Erro Inesperado", fg="red")
            self._display_output(f"❌ Ocorreu um erro inesperado: {str(e)}")

    def _display_output(self, text: str):
        # Atualização explícita da caixa de texto
        self.txt_output.config(state="normal")
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", text)
        self.txt_output.update_idletasks()
        self.root.update_idletasks()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppHU1(root)
    root.mainloop()