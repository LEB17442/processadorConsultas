"""
HU3 - Exibição do grafo de operadores ORIGINAL (não otimizado) em Tkinter.

    JanelaGrafoOriginal(master, arvore, sql)
        janela com o grafo original (arvore = build_operator_tree(parsed)),
        a árvore em texto e os detalhes do nó selecionado.

O desenho reaproveita desenhar_arvore do HU4, então o grafo original e o otimizado
têm o mesmo visual e podem ser comparados lado a lado.
Folhas = tabelas, nós intermediários = σ e ⋈, raiz = projeção final π.
As setas vão do filho para o pai: fluxo dos resultados intermediários (R1, R2, ...),
na mesma numeração usada pelo grafo do HU4 e pelo plano de execução do HU5.

Teste isolado (a partir da raiz do projeto):
    python -m src.HU3.visualizacao
    python -m src.HU3.visualizacao "SELECT Nome FROM Produto WHERE Preco > 100"
"""
import sys
import tkinter as tk
from typing import Any, List

try:
    from HU4.visualizacao import CORES, FONTE_MONO, FUNDO, desenhar_arvore
except ImportError:
    from src.HU4.visualizacao import CORES, FONTE_MONO, FUNDO, desenhar_arvore

from .tree import NoGrafo, ParseError, build_operator_tree_sql, descricao_no, postorder, preorder, render_ascii

LEGENDA = [
    ("tabela", "Tabela (folha)"),
    ("selecao", "σ Seleção"),
    ("projecao", "π Projeção"),
    ("juncao", "⋈ Junção"),
]
NOMES = {
    "tabela": "Tabela (folha)",
    "selecao": "Seleção (σ)",
    "projecao": "Projeção (π)",
    "juncao": "Junção (⋈)",
}


def _condicoes_simples(condicao: List[str]) -> List[str]:
    """['a', '=', '1', 'AND', 'b', '>', '2'] -> ['a = 1', 'b > 2']"""
    partes: List[List[str]] = [[]]
    for token in condicao or []:
        if token.upper() == "AND":
            partes.append([])
        else:
            partes[-1].append(token)
    return [" ".join(parte) for parte in partes if parte]


class JanelaGrafoOriginal(tk.Toplevel):
    """Janela da HU3: grafo de operadores original + árvore em texto + nó selecionado."""

    def __init__(self, master: tk.Misc, arvore: NoGrafo, sql: str = ""):
        super().__init__(master)
        self.arvore = arvore
        # Mesma numeração pós-ordem do desenho (R1, R2, ...), para citar filhos e pai no painel
        self._numeros = {id(no): numero for numero, no in enumerate(postorder(arvore), 1)}
        self._pais = {id(filho): no for no in preorder(arvore) for filho in no.filhos}
        self.title("HU3 - Grafo de Operadores Original (não otimizado)")
        self.geometry("1150x800")
        self.configure(bg=FUNDO)
        self._montar(sql)
        self._redesenhar()

    def _montar(self, sql: str) -> None:
        topo = tk.Frame(self, bg=FUNDO, padx=12, pady=8)
        topo.pack(fill="x")
        tk.Label(
            topo, text="HU3 - Grafo de Operadores Original (não otimizado)", font=("Arial", 13, "bold"),
            bg=FUNDO, anchor="w",
        ).pack(fill="x")
        if sql:
            tk.Label(
                topo, text=" ".join(sql.split()), font=(FONTE_MONO, 9), bg=FUNDO, fg="#424242",
                anchor="w", justify="left", wraplength=1100,
            ).pack(fill="x")

        legenda = tk.Frame(topo, bg=FUNDO)
        legenda.pack(fill="x", pady=(6, 0))
        for tipo, nome in LEGENDA:
            preenchimento, borda = CORES[tipo]
            tk.Label(legenda, text="  ", bg=preenchimento, highlightbackground=borda,
                     highlightthickness=2).pack(side="left", padx=(0, 4))
            tk.Label(legenda, text=nome, font=("Arial", 9), bg=FUNDO).pack(side="left", padx=(0, 14))
        tk.Label(
            legenda, text="Setas = fluxo dos resultados intermediários · passe o mouse sobre um nó",
            font=("Arial", 9, "italic"), bg=FUNDO, fg="#616161",
        ).pack(side="right")

        painel = tk.PanedWindow(self, orient="vertical", sashwidth=6, bg=FUNDO)
        painel.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        area = tk.Frame(painel, bg="#ffffff", bd=1, relief="solid")
        self.canvas = tk.Canvas(area, bg="#ffffff", highlightthickness=0, width=1100, height=430)
        barra_v = tk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        barra_h = tk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=barra_v.set, xscrollcommand=barra_h.set)
        barra_v.pack(side="right", fill="y")
        barra_h.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        painel.add(area, stretch="always", minsize=200)

        inferior = tk.Frame(painel, bg=FUNDO)
        painel.add(inferior, stretch="never", minsize=150)
        inferior.columnconfigure(0, weight=1, uniform="paineis")
        inferior.columnconfigure(1, weight=1, uniform="paineis")
        inferior.rowconfigure(0, weight=1)

        esquerda = tk.Frame(inferior, bg=FUNDO)
        esquerda.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(esquerda, text="Nó selecionado:", font=("Arial", 10, "bold"), bg=FUNDO, anchor="w").pack(fill="x")
        self.txt_no = tk.Text(esquerda, width=40, height=9, wrap="word", font=(FONTE_MONO, 10),
                              bg="#fffde7", bd=1, relief="solid")
        self.txt_no.pack(fill="both", expand=True)

        direita = tk.Frame(inferior, bg=FUNDO)
        direita.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        tk.Label(direita, text="Árvore em texto (estratégia original, sem heurísticas):",
                 font=("Arial", 10, "bold"), bg=FUNDO, anchor="w").pack(fill="x")
        moldura = tk.Frame(direita, bg=FUNDO)
        moldura.pack(fill="both", expand=True)
        # wrap="none" para não quebrar as linhas da árvore; por isso a rolagem horizontal
        self.txt_arvore = tk.Text(moldura, width=40, height=9, wrap="none", font=(FONTE_MONO, 10),
                                  bg="#eef6ff", fg="#003366", bd=1, relief="solid")
        rolagem_v = tk.Scrollbar(moldura, command=self.txt_arvore.yview)
        rolagem_h = tk.Scrollbar(moldura, orient="horizontal", command=self.txt_arvore.xview)
        self.txt_arvore.configure(yscrollcommand=rolagem_v.set, xscrollcommand=rolagem_h.set)
        rolagem_v.pack(side="right", fill="y")
        rolagem_h.pack(side="bottom", fill="x")
        self.txt_arvore.pack(side="left", fill="both", expand=True)

        self._escrever(self.txt_arvore, self._texto_arvore())
        self._escrever(self.txt_no, "Passe o mouse (ou clique) sobre um nó do grafo para ver seus detalhes.")

        self.canvas.bind("<Configure>", lambda _e: self._redesenhar())
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"))
        self.canvas.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))

    def _texto_arvore(self) -> str:
        nos = list(postorder(self.arvore))
        quantidade = {tipo: sum(1 for no in nos if no.tipo == tipo) for tipo in NOMES}
        return "\n".join([
            "GRAFO DE OPERADORES ORIGINAL",
            render_ascii(self.arvore),
            "",
            "RESUMO",
            f"• {len(nos)} nós: {quantidade['projecao']} projeção, {quantidade['selecao']} seleção, "
            f"{quantidade['juncao']} junção(ões) e {quantidade['tabela']} tabela(s) nas folhas",
            "• Junções na ordem escrita na consulta, encadeadas à esquerda",
            "• Uma única σ com todas as condições do WHERE, logo abaixo da π final"
            if quantidade["selecao"] else "• Sem WHERE: não há seleção",
            "• Nenhuma heurística aplicada (compare com o grafo otimizado da HU4)",
        ])

    def _redesenhar(self) -> None:
        desenhar_arvore(self.canvas, self.arvore, self._mostrar_no)

    def _mostrar_no(self, no: Any, numero: int) -> None:
        linhas = [f"R{numero}  ←  {descricao_no(no)}", "", f"Tipo: {NOMES.get(no.tipo, no.tipo)}"]
        if no.tipo == "tabela":
            linhas.append(f"Leitura da relação base {no.tabela}")
        elif no.tipo == "projecao":
            linhas.append("Atributos: " + ", ".join(no.atributos or ["*"]))
        else:
            linhas.append("Condição:" if no.tipo == "juncao" else "Condições (ligadas por ∧):")
            linhas += [f"  • {condicao}" for condicao in _condicoes_simples(no.condicao)]

        if no.filhos:
            linhas += ["", "Entradas (filhos):"]
            linhas += [f"  • R{self._numeros.get(id(filho), '?')} = {descricao_no(filho)}" for filho in no.filhos]

        pai = self._pais.get(id(no))
        linhas.append("")
        if pai is None:
            linhas.append("Saída: resultado final da consulta (raiz)")
        else:
            linhas.append(f"Saída vai para: R{self._numeros.get(id(pai), '?')} = {descricao_no(pai)}")
        self._escrever(self.txt_no, "\n".join(linhas))

    @staticmethod
    def _escrever(widget: tk.Text, texto: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", texto)
        widget.config(state="disabled")


if __name__ == "__main__":
    consulta = " ".join(sys.argv[1:]) or (
        "Select cliente.nome, pedido.idPedido, pedido.DataPedido, Status.descricao, pedido.ValorTotalPedido "
        "from Cliente Join pedido on cliente.idcliente = pedido.Cliente_idCliente "
        "Join Status on Status.idstatus = Pedido.status_idstatus "
        "where Status.descricao = 'Aberto' and cliente.TipoCliente_idTipoCliente = 1 "
        "and pedido.ValorTotalPedido = 0"
    )
    try:
        arvore_original = build_operator_tree_sql(consulta)
    except ParseError as erro:
        print(f"[{erro.error_type}] {erro.message}")
        sys.exit(1)

    janela_raiz = tk.Tk()
    janela_raiz.withdraw()
    janela = JanelaGrafoOriginal(janela_raiz, arvore_original, consulta)
    janela.protocol("WM_DELETE_WINDOW", janela_raiz.destroy)
    janela_raiz.mainloop()
