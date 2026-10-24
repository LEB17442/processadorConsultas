import json
import os
import sys
import tkinter as tk
from tkinter import messagebox

# Adiciona diretórios ao sys.path para garantir importações independentemente do SO
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # pasta 'src'
ROOT_DIR = os.path.dirname(BASE_DIR)  # pasta raiz do projeto

for path in [BASE_DIR, ROOT_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

# 1. Importação da HU1
try:
    from HU1.parser import ParseError, SQLParserHU1
except ImportError:
    from src.HU1.parser import ParseError, SQLParserHU1

# 2. Importação da HU2 (conversor.py)
converter_hu2 = None
try:
    from HU2.conversor import converter as converter_hu2
except ImportError:
    try:
        from src.HU2.conversor import converter as converter_hu2
    except ImportError as e:
        print(f"Aviso ao carregar HU2: {e}")

# 3. Importação da HU4 (optimizer.py e visualizacao.py)
otimizar_hu4 = None
JanelaGrafoOtimizado = None
try:
    from HU4.optimizer import otimizar as otimizar_hu4
    from HU4.visualizacao import JanelaGrafoOtimizado
except ImportError:
    try:
        from src.HU4.optimizer import otimizar as otimizar_hu4
        from src.HU4.visualizacao import JanelaGrafoOtimizado
    except ImportError as e:
        print(f"Aviso ao carregar HU4: {e}")

# 4. Importação da HU5 (plan.py)
plano_execucao_hu5 = None
try:
    from HU5.plan import plano_execucao as plano_execucao_hu5
except ImportError:
    try:
        from src.HU5.plan import plano_execucao as plano_execucao_hu5
    except ImportError as e:
        print(f"Aviso ao carregar HU5: {e}")

# 5. Importação da HU3 (tree.py e visualizacao.py)
# Imports separados: se a janela falhar, o grafo continua sendo construído pelo mesmo
# caminho do HU1 (HU1.parser), e o "except ParseError" abaixo continua capturando os erros do HU3
build_operator_tree = None
JanelaGrafoOriginal = None
try:
    from HU3.tree import build_operator_tree
except ImportError:
    try:
        from src.HU3.tree import build_operator_tree
    except ImportError as e:
        print(f"Aviso ao carregar HU3: {e}")
try:
    from HU3.visualizacao import JanelaGrafoOriginal
except ImportError:
    try:
        from src.HU3.visualizacao import JanelaGrafoOriginal
    except ImportError as e:
        print(f"Aviso ao carregar a janela da HU3: {e}")


class AppHU_Completo:
    def __init__(self, root):
        self.root = root
        self.root.title("Processador de Consultas SQL")
        self.root.geometry("950x850")
        self.root.configure(bg="#f0f0f0")
        self.resultado_hu4 = None
        self.sql_hu4 = ""
        self.arvore_hu3 = None
        self.sql_hu3 = ""

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
            main_frame, height=4, font=("Menlo" if sys.platform == "darwin" else "Consolas", 11),
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

        # 2. Painel de Botões
        btn_frame = tk.Frame(main_frame, bg="#f0f0f0")
        btn_frame.pack(fill="x", pady=8)

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

        self.btn_grafo_hu4 = tk.Button(
            btn_frame,
            text=" Ver Grafo Otimizado (HU4) ",
            command=self.abrir_grafo_otimizado,
            font=("Arial", 11, "bold"),
            bd=2,
            relief="raised",
            cursor="hand2",
            state="disabled"
        )
        self.btn_grafo_hu4.pack(side="right", padx=5)

        self.btn_grafo_hu3 = tk.Button(
            btn_frame,
            text=" Ver Grafo Original (HU3) ",
            command=self.abrir_grafo_original,
            font=("Arial", 11, "bold"),
            bd=2,
            relief="raised",
            cursor="hand2",
            state="disabled"
        )
        self.btn_grafo_hu3.pack(side="right", padx=5)

        # 3. Status
        self.lbl_status = tk.Label(
            main_frame, text="Status: Aguardando análise...", font=("Arial", 10, "italic"),
            bg="#f0f0f0", fg="#333333", anchor="w"
        )
        self.lbl_status.pack(fill="x", pady=3)

        # 4. Campo HU2 e HU4 (Álgebra)
        lbl_otimizada = tk.Label(
            main_frame, text="HU4 - Álgebra Relacional Otimizada (pós-heurísticas):", font=("Arial", 10, "bold"),
            bg="#f0f0f0", anchor="w"
        )
        lbl_otimizada.pack(fill="x", pady=(5, 2))

        self.txt_otimizada = tk.Text(
            main_frame, height=3, wrap="word", font=("Menlo" if sys.platform == "darwin" else "Consolas", 10, "bold"),
            bg="#eefaf0", fg="#1b5e20", bd=1, relief="solid"
        )
        self.txt_otimizada.pack(fill="x", pady=(0, 8))

        # 5. Campo HU5: Plano de Execução
        lbl_plano = tk.Label(
            main_frame, text="HU5 - Plano de Execução Passo a Passo:", font=("Arial", 10, "bold"),
            bg="#f0f0f0", anchor="w"
        )
        lbl_plano.pack(fill="x", pady=(0, 2))

        self.txt_plano = tk.Text(
            main_frame, height=7, font=("Menlo" if sys.platform == "darwin" else "Consolas", 9),
            bg="#fffde7", fg="#333333", bd=1, relief="solid"
        )
        self.txt_plano.pack(fill="x", pady=(0, 8))

        # 6. Campo HU1: Estrutura Parseada (JSON / Erros)
        lbl_output = tk.Label(
            main_frame, text="HU1 - Detalhes da Análise (JSON / Erros):", font=("Arial", 10, "bold"),
            bg="#f0f0f0", anchor="w"
        )
        lbl_output.pack(fill="x", pady=(2, 2))

        self.txt_output = tk.Text(
            main_frame, height=6, font=("Menlo" if sys.platform == "darwin" else "Consolas", 9),
            bg="#ffffff", fg="#000000", bd=1, relief="solid"
        )
        self.txt_output.pack(fill="both", expand=True, pady=(2, 0))

    def on_analyze(self):
        if not self.parser:
            self._display_output("❌ Erro: Parser não inicializado (falha no schema.json).")
            return

        sql_query = self.txt_sql.get("1.0", tk.END).strip()

        try:
            # Step 1: HU1 Parsing
            parsed_result = self.parser.parse(sql_query)
            self.lbl_status.config(text="Status: ✅ Consulta Válida (HU1, HU2, HU4 & HU5)", fg="green")

            formatted_json = json.dumps(parsed_result, indent=4, ensure_ascii=False)
            self._display_output(f"--- ESTRUTURA PARSEADA COM SUCESSO (HU1) ---\n\n{formatted_json}")

            # Step 1.1: HU3 Grafo de Operadores Original (try/except próprio: não derruba HU4/HU5)
            self._executar_hu3(parsed_result, sql_query)

            # Step 2: HU2 Conversão
            if converter_hu2:
                try:
                    converter_hu2(parsed_result)
                except Exception as e_hu2:
                    print(f"Aviso HU2: {e_hu2}")

            # Step 3: HU4 Otimização
            self._executar_hu4(parsed_result, sql_query)

            # Step 4: HU5 Plano de Execução
            self._executar_hu5()

        except ParseError as pe:
            self.lbl_status.config(text=f"Status: ❌ Erro {pe.error_type} Detectado (HU1)", fg="red")
            self._limpar_hu3()
            self._limpar_hu4("N/A (Falha na validação da consulta)")
            self._display_plano("N/A (Falha na validação da consulta)")
            self._display_output(f"❌ [ERRO {pe.error_type.upper()}]\n{pe.message}")

        except Exception as e:
            self.lbl_status.config(text="Status: ❌ Erro Inesperado", fg="red")
            self._limpar_hu3()
            self._limpar_hu4("N/A")
            self._display_plano("N/A")
            self._display_output(f"❌ Ocorreu um erro inesperado: {str(e)}")

    def _executar_hu3(self, parsed_result, sql_query: str):
        self._limpar_hu3()
        if not build_operator_tree:
            return
        try:
            self.arvore_hu3 = build_operator_tree(parsed_result)
            self.sql_hu3 = sql_query
            if JanelaGrafoOriginal:
                self.btn_grafo_hu3.config(state="normal")
        except ParseError as pe_hu3:
            self.lbl_status.config(text=f"Status: ❌ Erro {pe_hu3.error_type} Detectado (HU3)", fg="red")
            self._display_output(f"❌ [ERRO {pe_hu3.error_type.upper()}]\n{pe_hu3.message}")
        except Exception as e_hu3:
            print(f"Aviso HU3: {e_hu3}")

    def _limpar_hu3(self):
        self.arvore_hu3 = None
        self.btn_grafo_hu3.config(state="disabled")

    def abrir_grafo_original(self):
        if self.arvore_hu3 is not None and JanelaGrafoOriginal:
            JanelaGrafoOriginal(self.root, self.arvore_hu3, self.sql_hu3)

    def _executar_hu4(self, parsed_result, sql_query: str):
        if not otimizar_hu4:
            self._limpar_hu4("Módulo HU4 (optimizer.py) não foi localizado ou importado.")
            return
        try:
            self.resultado_hu4 = otimizar_hu4(parsed_result, self.schema)
            self.sql_hu4 = sql_query
            self._display_otimizada(self.resultado_hu4.algebra)
            if JanelaGrafoOtimizado:
                self.btn_grafo_hu4.config(state="normal")
        except Exception as e_hu4:
            self._limpar_hu4(f"Erro na otimização HU4: {str(e_hu4)}")

    def _executar_hu5(self):
        if not plano_execucao_hu5 or not self.resultado_hu4:
            self._display_plano("Módulo HU5 (plan.py) não localizado ou árvore da HU4 indisponível.")
            return
        try:
            texto_plano = plano_execucao_hu5(self.resultado_hu4.arvore, como_texto=True)
            self._display_plano(texto_plano)
        except Exception as e_hu5:
            self._display_plano(f"Erro na geração do Plano HU5: {str(e_hu5)}")

    def _limpar_hu4(self, text: str):
        self.resultado_hu4 = None
        self.btn_grafo_hu4.config(state="disabled")
        self._display_otimizada(text)

    def abrir_grafo_otimizado(self):
        if self.resultado_hu4 and JanelaGrafoOtimizado:
            JanelaGrafoOtimizado(self.root, self.resultado_hu4, self.sql_hu4)

    def _display_otimizada(self, text: str):
        self.txt_otimizada.config(state="normal")
        self.txt_otimizada.delete("1.0", tk.END)
        self.txt_otimizada.insert("1.0", text)
        self.txt_otimizada.update_idletasks()
        self.root.update_idletasks()

    def _display_plano(self, text: str):
        self.txt_plano.config(state="normal")
        self.txt_plano.delete("1.0", tk.END)
        self.txt_plano.insert("1.0", text)
        self.txt_plano.update_idletasks()
        self.root.update_idletasks()

    def _display_output(self, text: str):
        self.txt_output.config(state="normal")
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert("1.0", text)
        self.txt_output.update_idletasks()
        self.root.update_idletasks()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppHU_Completo(root)
    root.mainloop()