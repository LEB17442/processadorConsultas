import json
import os
import sys
import tkinter as tk
from tkinter import messagebox

# Adiciona diretórios ao sys.path para garantir importações independentemente do SO
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # pasta 'src'
ROOT_DIR = os.path.dirname(BASE_DIR) # pasta raiz do projeto

for path in [BASE_DIR, ROOT_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Importação da HU1
try:
    from HU1.parser import SQLParserHU1, ParseError
except ImportError:
    from src.HU1.parser import SQLParserHU1, ParseError

# Importação da HU2
converter_hu2 = None
try:
    from HU2.conversor import converter as converter_hu2
except ImportError:
    try:
        from src.HU2.conversor import converter as converter_hu2
    except ImportError as e:
        print(f"Aviso ao carregar HU2: {e}")


class AppHU1_HU2:
    def __init__(self, root):
        self.root = root
        self.root.title("Processador de Consultas SQL - HU1 e HU2")
        self.root.geometry("850x700")
        self.root.configure(bg="#f0f0f0")

        # Carrega o schema.json
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

        # 1. Campo de Entrada SQL
        lbl_input = tk.Label(
            main_frame, text="Digite a consulta SQL:", font=("Arial", 11, "bold"), bg="#f0f0f0", anchor="w"
        )
        lbl_input.pack(fill="x", pady=(0, 5))

        self.txt_sql = tk.Text(
            main_frame, height=5, font=("Menlo" if sys.platform == "darwin" else "Consolas", 11),
            bg="#ffffff", fg="#000000", bd=1, relief="solid"
        )
        self.txt_sql.pack(fill="x", pady=5)

        default_sql = (
            "SELECT Cliente.Nome, Pedido.ValorTotalPedido\n"
            "FROM Cliente\n"
            "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente\n"
            "WHERE ValorTotalPedido > 100"
        )
        self.txt_sql.insert("1.0", default_sql)

        # 2. Botão "Analisar"
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

        # 4. Campo HU2: Álgebra Relacional
        lbl_algebra = tk.Label(
            main_frame, text="HU2 - Expressão em Álgebra Relacional (π, σ, ⋈):", font=("Arial", 11, "bold"),
            bg="#f0f0f0", anchor="w"
        )
        lbl_algebra.pack(fill="x", pady=(10, 5))

        self.txt_algebra = tk.Text(
            main_frame, height=3, font=("Menlo" if sys.platform == "darwin" else "Consolas", 11, "bold"),
            bg="#eef6ff", fg="#003366", bd=1, relief="solid"
        )
        self.txt_algebra.pack(fill="x", pady=(0, 10))

        # 5. Campo HU1: Estrutura Parseada (JSON / Erros)
        lbl_output = tk.Label(
            main_frame, text="HU1 - Detalhes da Análise (JSON / Erros):", font=("Arial", 11, "bold"),
            bg="#f0f0f0", anchor="w"
        )
        lbl_output.pack(fill="x", pady=(5, 5))

        self.txt_output = tk.Text(
            main_frame, height=8, font=("Menlo" if sys.platform == "darwin" else "Consolas", 10),
            bg="#ffffff", fg="#000000", bd=1, relief="solid"
        )
        self.txt_output.pack(fill="both", expand=True, pady=(5, 0))

    def on_analyze(self):
        if not self.parser:
            self._display_output("❌ Erro: Parser não inicializado (falha no schema.json).")
            return

        sql_query = self.txt_sql.get("1.0", tk.END).strip()

        try:
            # Step 1: Executa a HU1 (Parsing e Validação)
            parsed_result = self.parser.parse(sql_query)
            self.lbl_status.config(text="Status: ✅ Consulta Válida (HU1 & HU2)", fg="green")

            formatted_json = json.dumps(parsed_result, indent=4, ensure_ascii=False)
            self._display_output(f"--- ESTRUTURA PARSEADA COM SUCESSO (HU1) ---\n\n{formatted_json}")

            # Step 2: Executa a HU2 (Converter dicionário para Álgebra Relacional)
            if converter_hu2:
                try:
                    algebra_expr = converter_hu2(parsed_result)
                    self._display_algebra(algebra_expr)
                except Exception as e_hu2:
                    self._display_algebra(f"Erro na conversão HU2: {str(e_hu2)}")
            else:
                self._display_algebra("Módulo HU2 (converter.py) não foi localizado ou importado.")

        except ParseError as pe:
            self.lbl_status.config(text=f"Status: ❌ Erro {pe.error_type} Detectado (HU1)", fg="red")
            self._display_algebra("N/A (Falha na validação da consulta)")
            self._display_output(f"❌ [ERRO {pe.error_type.upper()}]\n{pe.message}")

        except Exception as e:
            self.lbl_status.config(text="Status: ❌ Erro Inesperado", fg="red")
            self._display_algebra("N/A")
            self._display_output(f"❌ Ocorreu um erro inesperado: {str(e)}")

    def _display_algebra(self, text: str):
        self.txt_algebra.config(state="normal")
        self.txt_algebra.delete("1.0", tk.END)
        self.txt_algebra.insert("1.0", text)
        self.txt_algebra.update_idletasks()

    def _display_output(self, text: str):
        self.txt_output.config(state="normal")
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", text)
        self.txt_output.update_idletasks()
        self.root.update_idletasks()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppHU1_HU2(root)
    root.mainloop()