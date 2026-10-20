"""
HU4 - Exibição do grafo de operadores otimizado (Tkinter).

    desenhar_arvore(canvas, raiz)   desenha qualquer árvore no contrato tipo/filhos
                                    (serve também para o grafo original do HU3)
    JanelaGrafoOtimizado(master, resultado)
                                    janela com o grafo otimizado, a álgebra otimizada
                                    e as heurísticas aplicadas (resultado = otimizar(...))

Folhas = tabelas, nós intermediários = operadores (σ, ⋈, ×, π), raiz = projeção final.
As setas indicam o fluxo dos resultados intermediários (R1, R2, ...), na mesma
numeração usada pelo plano de execução (HU5).
"""
import sys
import tkinter as tk
from tkinter import font as tkfont
from typing import Any, Callable, List, Optional, Tuple

try:
    from .optimizer import descricao_do_no, filhos_do_no, tipo_do_no
except ImportError:  # executado direto como script
    from optimizer import descricao_do_no, filhos_do_no, tipo_do_no

FUNDO = "#f0f0f0"
FONTE_MONO = "Menlo" if sys.platform == "darwin" else "Consolas"

CORES = {  # tipo -> (preenchimento, borda)
    "tabela": ("#e8f5e9", "#2e7d32"),
    "selecao": ("#fff3e0", "#ef6c00"),
    "projecao": ("#e3f2fd", "#1565c0"),
    "juncao": ("#f3e5f5", "#6a1b9a"),
    "produto": ("#ffebee", "#c62828"),
}
LEGENDA = [
    ("tabela", "Tabela (folha)"),
    ("selecao", "σ Seleção"),
    ("projecao", "π Projeção"),
    ("juncao", "⋈ Junção"),
    ("produto", "× Produto cartesiano"),
]

PAD_X, PAD_Y = 12, 8
ESPACO_X, ESPACO_Y = 28, 38
LIMITE_LINHA = 30
MARGEM = 30


class _Caixa:
    def __init__(self, no: Any, linhas: List[str], largura: float, altura: float, filhos: List["_Caixa"]):
        self.no = no
        self.tipo = tipo_do_no(no)
        self.linhas = linhas
        self.largura = largura
        self.altura = altura
        self.filhos = filhos
        largura_filhos = sum(f.largura_sub for f in filhos) + ESPACO_X * max(len(filhos) - 1, 0)
        self.largura_filhos = largura_filhos
        self.largura_sub = max(largura, largura_filhos)
        self.cx = 0.0
        self.y = 0.0
        self.numero = 0


def _quebrar_linhas(texto: str, limite: int = LIMITE_LINHA) -> List[str]:
    linhas: List[str] = []
    atual = ""
    for palavra in texto.split(" "):
        candidata = f"{atual} {palavra}".strip()
        if len(candidata) > limite and atual:
            linhas.append(atual)
            atual = palavra
        else:
            atual = candidata
    if atual:
        linhas.append(atual)
    return linhas or [""]


def _medir(no: Any, fonte: tkfont.Font, altura_linha: int) -> _Caixa:
    linhas = _quebrar_linhas(descricao_do_no(no))
    largura = max(fonte.measure(linha) for linha in linhas) + 2 * PAD_X
    altura = len(linhas) * altura_linha + 2 * PAD_Y
    filhos = [_medir(filho, fonte, altura_linha) for filho in filhos_do_no(no)]
    return _Caixa(no, linhas, largura, altura, filhos)


def _posicionar(caixa: _Caixa, x_esquerda: float, y: float) -> None:
    caixa.cx = x_esquerda + caixa.largura_sub / 2
    caixa.y = y
    x = x_esquerda + (caixa.largura_sub - caixa.largura_filhos) / 2
    for filho in caixa.filhos:
        _posicionar(filho, x, y + caixa.altura + ESPACO_Y)
        x += filho.largura_sub + ESPACO_X


def _pos_ordem(caixa: _Caixa) -> List[_Caixa]:
    ordem: List[_Caixa] = []
    for filho in caixa.filhos:
        ordem.extend(_pos_ordem(filho))
    ordem.append(caixa)
    return ordem


def _retangulo_arredondado(canvas: tk.Canvas, x1, y1, x2, y2, raio=10, **opcoes):
    pontos = [
        x1 + raio, y1, x2 - raio, y1, x2, y1, x2, y1 + raio, x2, y2 - raio, x2, y2,
        x2 - raio, y2, x1 + raio, y2, x1, y2, x1, y2 - raio, x1, y1 + raio, x1, y1,
    ]
    return canvas.create_polygon(pontos, smooth=True, **opcoes)


def desenhar_arvore(canvas: tk.Canvas, raiz: Any,
                    ao_passar: Optional[Callable[[Any, int], None]] = None) -> Tuple[int, int]:
    """Desenha a árvore no canvas e devolve (largura, altura) ocupadas."""
    canvas.delete("all")
    fonte = tkfont.Font(family="Arial", size=10, weight="bold")
    fonte_rotulo = tkfont.Font(family="Arial", size=8)
    altura_linha = fonte.metrics("linespace")

    caixa_raiz = _medir(raiz, fonte, altura_linha)
    caixas = _pos_ordem(caixa_raiz)
    for numero, caixa in enumerate(caixas, 1):
        caixa.numero = numero

    largura = caixa_raiz.largura_sub + 2 * MARGEM
    visivel = max(canvas.winfo_width(), int(canvas.cget("width") or 0))
    deslocamento = max(MARGEM, (visivel - caixa_raiz.largura_sub) / 2)
    _posicionar(caixa_raiz, deslocamento, MARGEM)
    altura = int(max(c.y + c.altura for c in caixas) + MARGEM)

    # Arestas: do filho (resultado intermediário) para o pai
    for caixa in caixas:
        for filho in caixa.filhos:
            canvas.create_line(
                filho.cx, filho.y, caixa.cx, caixa.y + caixa.altura,
                arrow=tk.LAST, arrowshape=(10, 12, 4), fill="#616161", width=1.6,
            )

    for caixa in caixas:
        preenchimento, borda = CORES[caixa.tipo]
        x1, x2 = caixa.cx - caixa.largura / 2, caixa.cx + caixa.largura / 2
        y1, y2 = caixa.y, caixa.y + caixa.altura
        etiqueta = f"no{caixa.numero}"
        eh_raiz = caixa is caixa_raiz
        _retangulo_arredondado(
            canvas, x1, y1, x2, y2, fill=preenchimento, outline=borda,
            width=3 if eh_raiz else 2, tags=(etiqueta, "no"),
        )
        canvas.create_text(
            caixa.cx, (y1 + y2) / 2, text="\n".join(caixa.linhas), font=fonte,
            fill="#212121", justify="center", tags=(etiqueta, "no"),
        )
        canvas.create_text(x2 + 4, y1, text=f"R{caixa.numero}", anchor="nw", font=fonte_rotulo, fill="#757575")
        if eh_raiz:
            canvas.create_text(x1 - 6, (y1 + y2) / 2, text="raiz", anchor="e", font=fonte_rotulo, fill="#757575")
        if ao_passar:
            for evento in ("<Enter>", "<Button-1>"):
                canvas.tag_bind(etiqueta, evento, lambda _e, c=caixa: ao_passar(c.no, c.numero))

    regiao_largura = max(largura, deslocamento + caixa_raiz.largura_sub + MARGEM)
    canvas.configure(scrollregion=(0, 0, regiao_largura, altura))
    return int(regiao_largura), altura


class JanelaGrafoOtimizado(tk.Toplevel):
    """Janela da HU4: grafo otimizado + álgebra otimizada + heurísticas aplicadas."""

    def __init__(self, master: tk.Misc, resultado: Any, sql: str = ""):
        super().__init__(master)
        self.resultado = resultado
        self.title("HU4 - Grafo de Operadores Otimizado (pós-heurísticas)")
        self.geometry("1150x800")
        self.configure(bg=FUNDO)
        self._montar(sql)
        self.after(50, self._redesenhar)

    def _montar(self, sql: str) -> None:
        topo = tk.Frame(self, bg=FUNDO, padx=12, pady=8)
        topo.pack(fill="x")
        tk.Label(
            topo, text="HU4 - Grafo de Operadores Otimizado", font=("Arial", 13, "bold"), bg=FUNDO, anchor="w",
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
        tk.Label(direita, text="Álgebra otimizada e heurísticas aplicadas:", font=("Arial", 10, "bold"),
                 bg=FUNDO, anchor="w").pack(fill="x")
        moldura = tk.Frame(direita, bg=FUNDO)
        moldura.pack(fill="both", expand=True)
        self.txt_relatorio = tk.Text(moldura, width=40, height=9, wrap="word", font=(FONTE_MONO, 10),
                                     bg="#eef6ff", fg="#003366", bd=1, relief="solid")
        rolagem = tk.Scrollbar(moldura, command=self.txt_relatorio.yview)
        self.txt_relatorio.configure(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        self.txt_relatorio.pack(side="left", fill="both", expand=True)

        relatorio = [
            "ÁLGEBRA RELACIONAL OTIMIZADA",
            self.resultado.algebra,
            "",
            "ORDEM DAS JUNÇÕES: " + " → ".join(self.resultado.ordem_juncoes),
            "",
            "HEURÍSTICAS APLICADAS",
            *self.resultado.heuristicas_aplicadas,
        ]
        self._escrever(self.txt_relatorio, "\n".join(relatorio))
        self._escrever(self.txt_no, "Passe o mouse (ou clique) sobre um nó do grafo para ver as heurísticas aplicadas nele.")

        self.canvas.bind("<Configure>", lambda _e: self._redesenhar())
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"))
        self.canvas.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))

    def _redesenhar(self) -> None:
        desenhar_arvore(self.canvas, self.resultado.arvore, self._mostrar_no)

    def _mostrar_no(self, no: Any, numero: int) -> None:
        heuristicas = getattr(no, "heuristicas", None) or (no.get("heuristicas") if isinstance(no, dict) else None) or []
        linhas = [f"R{numero}  ←  {descricao_do_no(no)}", ""]
        linhas += [f"• {h}" for h in heuristicas] or ["(nenhuma heurística registrada neste nó)"]
        self._escrever(self.txt_no, "\n".join(linhas))

    @staticmethod
    def _escrever(widget: tk.Text, texto: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", texto)
        widget.config(state="disabled")


if __name__ == "__main__":
    import os

    _src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _caminho in (_src, os.path.dirname(_src)):
        if _caminho not in sys.path:
            sys.path.insert(0, _caminho)
    from src.HU4.optimizer import otimizar_sql

    consulta = " ".join(sys.argv[1:]) or (
        "SELECT Cliente.Nome, Pedido.ValorTotalPedido FROM Cliente "
        "JOIN Pedido ON Cliente.idCliente = Pedido.Cliente_idCliente "
        "WHERE ValorTotalPedido > 100"
    )
    janela_raiz = tk.Tk()
    janela_raiz.withdraw()
    janela = JanelaGrafoOtimizado(janela_raiz, otimizar_sql(consulta), consulta)
    janela.protocol("WM_DELETE_WINDOW", janela_raiz.destroy)
    janela_raiz.mainloop()
