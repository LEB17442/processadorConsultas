import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

for path in [BASE_DIR, ROOT_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

import tkinter as tk
from Front.app import AppHU1_HU2

def main():
    root = tk.Tk()
    app = AppHU1_HU2(root)
    
    # Traz a janela para o primeiro plano no macOS
    root.lift()
    root.attributes('-topmost', True)
    root.after_idle(root.attributes, '-topmost', False)
    
    root.mainloop()

if __name__ == "__main__":
    main()