import os
import re
import queue
import threading
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

import core

MAX_ROWS_VIEW = 5000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Comparador de tablas Oracle")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.q = queue.Queue()
        self.engines = None
        self.labels = None
        self.ctx = None
        self.result = None
        self._busy = False
        self._build()
        core.set_logger(lambda m: self.post(lambda: self._append_log(m)))
        self.status.set("Listo. Configure las dos conexiones.")
        core.log(f"Aplicación iniciada. Log en: {core.LOG_FILE}")
        core.log_environment()
        self.after(100, self._poll)

    def post(self, fn):
        self.q.put(fn)

    def _poll(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def run_async(self, work, done, msg):
        self.status.set(msg)
        core.log(msg)
        self._t0 = datetime.now()
        self._busy = True
        self.progress.start(12)
        self._tick()

        def target():
            try:
                res = work()
            except Exception as e:
                tb = traceback.format_exc()
                # Capturar e y tb como valores por defecto: la variable e se
                # elimina al salir del bloque except en Python 3.
                self.post(lambda exc=e, trace=tb: self._fail(exc, trace))
                return
            self.post(lambda: (self._end_busy(), done(res)))

        threading.Thread(target=target, daemon=True).start()

    def _tick(self):
        if self._busy:
            secs = int((datetime.now() - self._t0).total_seconds())
            self.elapsed.set(f"{secs}s")
            self.after(1000, self._tick)

    def _end_busy(self):
        self._busy = False
        self.progress.stop()
        self.elapsed.set("")

    def _fail(self, e, tb):
        self._end_busy()
        self.status.set("Error")
        core.log(f"ERROR: {e}")
        core.log(tb, ui=False)
        messagebox.showerror("Error", f"{e}")

    def _append_log(self, line):
        self.log_txt.config(state="normal")
        self.log_txt.insert("end", line + "\n")
        self.log_txt.see("end")
        self.log_txt.config(state="disabled")

    def _build(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self._tab_conn()
        self._tab_struct()
        self._tab_data()
        self.nb.tab(1, state="disabled")
        self.nb.tab(2, state="disabled")

        lf = ttk.LabelFrame(self, text="Registro de actividad", padding=4)
        lf.pack(fill="x", padx=8, pady=(6, 0))
        self.log_txt = tk.Text(lf, height=8, wrap="word", state="disabled", font=("Consolas", 9), background="#f7f7f7")
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=lsb.set)
        self.log_txt.pack(side="left", fill="x", expand=True)
        lsb.pack(side="right", fill="y")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)
        self.status = tk.StringVar()
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        self.elapsed = tk.StringVar()
        ttk.Label(bar, textvariable=self.elapsed, width=6).pack(side="right", padx=6)

    def _tab_conn(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="1. Conexiones")
        saved = core.load_config()
        defaults = [
            {"NAME": "PROD", "DB_USER": "", "DB_HOST": "", "DB_PORT": 1521, "DB_SERVICE": ""},
            {"NAME": "QA", "DB_USER": "", "DB_HOST": "", "DB_PORT": 1521, "DB_SERVICE": ""},
        ]
        self.conn_vars = []
        fields = [("NAME", "Ambiente"), ("DB_USER", "Usuario"), ("DB_PASSWORD", "Contraseña"),
                  ("DB_HOST", "Host"), ("DB_PORT", "Puerto"), ("DB_SERVICE", "Service name")]
        for i, title in enumerate(("Base de datos A", "Base de datos B")):
            d = saved[i] if i < len(saved) else defaults[i]
            lf = ttk.LabelFrame(f, text=title, padding=10)
            lf.grid(row=0, column=i, padx=8, sticky="nsew")
            f.columnconfigure(i, weight=1)
            vs = {}
            for r, (key, label) in enumerate(fields):
                ttk.Label(lf, text=label).grid(row=r, column=0, sticky="w", pady=3)
                v = tk.StringVar(value=str(d.get(key, "")))
                ttk.Entry(lf, textvariable=v, width=48, show="*" if key == "DB_PASSWORD" else "").grid(row=r, column=1, pady=3, padx=6)
                vs[key] = v
            self.conn_vars.append(vs)
        ic = ttk.LabelFrame(f, text="Oracle Instant Client", padding=8)
        ic.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 0))
        ic.columnconfigure(0, weight=1)
        self.ic_var = tk.StringVar(value=core.load_instant_dir())
        ttk.Entry(ic, textvariable=self.ic_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(ic, text="Examinar…", command=lambda: self.ic_var.set(
            filedialog.askdirectory(title="Carpeta del Instant Client") or self.ic_var.get())).grid(row=0, column=1, padx=6)
        ttk.Label(ic, text="Ruta de Oracle Instant Client. En este equipo: C:\\instantclient_19_32. "
                           "Se requiere para inicializar el modo THICK antes de conectar.", foreground="#666", wraplength=900).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(f, text="La contraseña nunca se guarda; config.py se genera sin ella.",
                  foreground="#666").grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky="w")
        self.btn_connect = ttk.Button(f, text="Guardar config.py y conectar", command=self.do_connect)
        self.btn_connect.grid(row=3, column=0, columnspan=2, pady=12)

    def _tab_struct(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="2. Estructura")
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Tabla (ESQUEMA.TABLA):").pack(side="left")
        self.table_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.table_var, width=40)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda _e: self.do_structure())
        ttk.Button(top, text="Comparar estructura", command=self.do_structure).pack(side="left")
        self.struct_summary = tk.StringVar()
        ttk.Label(f, textvariable=self.struct_summary, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=6)

        cols = ("col", "ta", "tb", "estado")
        self.tree_struct = ttk.Treeview(f, columns=cols, show="headings", height=10)
        for c, t, w in (("col", "Columna", 240), ("ta", "Tipo A", 200), ("tb", "Tipo B", 200), ("estado", "Estado", 220)):
            self.tree_struct.heading(c, text=t)
            self.tree_struct.column(c, width=w)
        self.tree_struct.tag_configure("solo", background="#fde8c8")
        self.tree_struct.tag_configure("tipo", background="#f8d0d0")
        self.tree_struct.pack(fill="x")

        act = ttk.Frame(f)
        act.pack(fill="x", pady=8)
        self.dir_var = tk.StringVar()
        self.cmb_dir = ttk.Combobox(act, textvariable=self.dir_var, state="readonly", width=42)
        self.cmb_dir.pack(side="left")
        ttk.Button(act, text="Generar script para emparejar", command=self.do_alter).pack(side="left", padx=6)
        ttk.Button(act, text="Guardar .sql…", command=self.save_alter).pack(side="left")
        ttk.Button(act, text="Continuar a datos ▶", command=lambda: self.nb.select(2)).pack(side="right")

        self.txt_alter = tk.Text(f, height=10, wrap="none", font=("Consolas", 10))
        self.txt_alter.pack(fill="both", expand=True)

    def _tab_data(self):
        f = ttk.Frame(self.nb, padding=12)
        self.nb.add(f, text="3. Datos")
        g = ttk.Frame(f)
        g.pack(fill="x")
        ttk.Label(g, text="Columnas clave (coma):").grid(row=0, column=0, sticky="w", pady=3)
        self.key_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.key_var, width=70).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(g, text="WHERE (opcional):").grid(row=1, column=0, sticky="w", pady=3)
        self.where_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.where_var, width=70).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(g, text="Vacío = SELECT sin condiciones. Se aplica a ambas BD.", foreground="#666").grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(g, text="Comparar solo estas columnas:").grid(row=3, column=0, sticky="w", pady=3)
        self.inc_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.inc_var, width=70).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Button(g, text="Elegir…", command=lambda: self.pick_columns(self.inc_var, "Comparar solo estas columnas")).grid(row=3, column=2)
        ttk.Label(g, text="Excluir columnas:").grid(row=4, column=0, sticky="w", pady=3)
        self.exc_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.exc_var, width=70).grid(row=4, column=1, sticky="w", padx=6)
        ttk.Button(g, text="Elegir…", command=lambda: self.pick_columns(self.exc_var, "Excluir columnas")).grid(row=4, column=2)
        ttk.Label(g, text="Vacío = se comparan todas. Si indica 'solo estas', 'Excluir' se ignora. Las claves siempre emparejan y no se comparan.",
                  foreground="#666").grid(row=5, column=1, sticky="w", padx=6)
        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Consultar y comparar", command=self.do_data).pack(side="left")
        self.btn_export = ttk.Button(btns, text="Exportar reporte y scripts…", command=self.do_export, state="disabled")
        self.btn_export.pack(side="left", padx=8)
        self.data_summary = tk.StringVar()
        ttk.Label(f, textvariable=self.data_summary, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")

        cols = ("tipo", "reg", "campo", "va", "vb")
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True, pady=6)
        self.tree_data = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, t, w in (("tipo", "Resultado", 110), ("reg", "Registro (clave)", 260), ("campo", "Campo", 160),
                        ("va", "Valor A", 240), ("vb", "Valor B", 240)):
            self.tree_data.heading(c, text=t)
            self.tree_data.column(c, width=w)
        self.tree_data.tag_configure("dif", background="#f8d0d0")
        self.tree_data.tag_configure("solo", background="#fde8c8")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree_data.yview)
        self.tree_data.configure(yscrollcommand=sb.set)
        self.tree_data.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def do_connect(self):
        cfgs = []
        for vs in self.conn_vars:
            c = {k: v.get().strip() for k, v in vs.items()}
            c["NAME"] = c["NAME"].upper()
            if not all(c[k] for k in ("NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_SERVICE")) or not c["DB_PORT"].isdigit():
                messagebox.showwarning("Datos incompletos", "Complete todos los campos de ambas conexiones (puerto numérico).")
                return
            cfgs.append(c)
        if cfgs[0]["NAME"] == cfgs[1]["NAME"]:
            cfgs[0]["NAME"] += "_A"
            cfgs[1]["NAME"] += "_B"
        ic_dir = self.ic_var.get().strip()
        try:
            core.write_config(cfgs, ic_dir)
            core.log(f"Configuración guardada en: {core.CONFIG_FILE} (sin contraseñas)")
        except Exception as ex:
            core.log("No fue posible guardar la configuración:")
            core.log(traceback.format_exc(), ui=False)
            messagebox.showerror("Error de configuración", str(ex))
            return

        try:
            core.log("Inicializando Oracle Client en el hilo principal...")
            mode = core.init_client(ic_dir)
            core.log(f"Oracle Client listo. Modo: {mode}; versión: {core.oracledb.clientversion()}")
        except Exception as ex:
            core.log(f"ERROR inicializando Oracle Client: {type(ex).__name__}: {ex}")
            core.log(traceback.format_exc(), ui=False)
            messagebox.showerror("Error de Oracle Client", str(ex))
            return

        def work():
            engines = []
            try:
                engines = [core.get_engine(c) for c in cfgs]
                for c, e in zip(cfgs, engines):
                    try:
                        core.log(f"[{c['NAME']}] Verificando red hacia {c['DB_HOST']}:{c['DB_PORT']} ...")
                        core.check_port(c["DB_HOST"], c["DB_PORT"])
                        core.log(f"[{c['NAME']}] Red OK. Autenticando como {c['DB_USER']} (service {c['DB_SERVICE']}) ...")
                        core.log(f"[{c['NAME']}] (si pasa de 15 s, la pila de ejecución se vuelca en {core.BASE_DIR / 'hang_dump.log'})")
                        core.test_connection(e)
                        core.log(f"[{c['NAME']}] Conexión OK")
                    except Exception as ex:
                        raise RuntimeError(f"No se pudo conectar a {c['NAME']}: {ex}") from ex
                return mode, engines
            except Exception:
                for engine in engines:
                    try:
                        engine.dispose()
                    except Exception:
                        pass
                raise

        def done(result):
            mode, engines = result
            self.engines = engines
            self.labels = [c["NAME"] for c in cfgs]
            self.ctx = self.result = None
            self.nb.tab(1, state="normal")
            self.nb.tab(2, state="disabled")
            self.nb.select(1)
            self.status.set(f"Conectado a {self.labels[0]} y {self.labels[1]} (modo {mode}). config.py guardado.")

        self.run_async(work, done, "Probando conexiones...")

    def do_structure(self):
        parsed = core.parse_table(self.table_var.get())
        if not parsed:
            messagebox.showwarning("Tabla inválida", "Use el formato ESQUEMA.TABLA")
            return
        owner, table = parsed
        ea, eb = self.engines

        def work():
            core.log(f"Leyendo columnas de {owner}.{table} en {self.labels[0]} ...")
            ca = core.get_columns(ea, owner, table)
            core.log(f"Leyendo columnas de {owner}.{table} en {self.labels[1]} ...")
            cb = core.get_columns(eb, owner, table)
            pk = core.get_pk(ea, owner, table) or core.get_pk(eb, owner, table)
            return ca, cb, pk

        def done(res):
            ca, cb, pk = res
            la, lb = self.labels
            missing = [n for n, c in ((la, ca), (lb, cb)) if not c]
            if missing:
                messagebox.showerror("Tabla no encontrada", f"{owner}.{table} no existe (o sin acceso) en: {', '.join(missing)}")
                self.status.set("Tabla no encontrada")
                return
            only_a, only_b, diff = core.compare_columns(ca, cb)
            self.tree_struct.heading("ta", text=f"Tipo {la}")
            self.tree_struct.heading("tb", text=f"Tipo {lb}")
            self.tree_struct.delete(*self.tree_struct.get_children())
            for c in sorted(set(ca) | set(cb), key=lambda x: list(ca).index(x) if x in ca else 10_000 + list(cb).index(x)):
                ta, tb = ca.get(c, ""), cb.get(c, "")
                if c not in ca:
                    est, tag = f"Solo en {lb}", "solo"
                elif c not in cb:
                    est, tag = f"Solo en {la}", "solo"
                elif ta != tb:
                    est, tag = "Tipo distinto", "tipo"
                else:
                    est, tag = "Igual", ""
                self.tree_struct.insert("", "end", values=(c, ta, tb, est), tags=(tag,) if tag else ())
            n = len(only_a) + len(only_b) + len(diff)
            core.log(f"Estructura: {len(ca)} columnas en {la}, {len(cb)} en {lb}, {n} diferencia(s). PK: {', '.join(pk) or 'sin PK'}")
            self.struct_summary.set("✔ Las estructuras son IGUALES" if n == 0 else f"✖ {n} diferencia(s) de estructura")
            self.cmb_dir["values"] = [f"Dejar {lb} igual a {la}", f"Dejar {la} igual a {lb}"]
            self.cmb_dir.current(0)
            self.txt_alter.delete("1.0", "end")
            common = [c for c in ca if c in cb]
            self.ctx = dict(owner=owner, table=table, ca=ca, cb=cb, common=common)
            self.key_var.set(", ".join(k for k in pk if k in common))
            self.inc_var.set("")
            self.exc_var.set("")
            self.result = None
            self.btn_export.config(state="disabled")
            self.tree_data.delete(*self.tree_data.get_children())
            self.data_summary.set("")
            self.nb.tab(2, state="normal")
            self.status.set("Estructura analizada.")

        self.run_async(work, done, "Leyendo estructura en ambas BD...")

    def do_alter(self):
        if not self.ctx:
            return
        c = self.ctx
        la, lb = self.labels
        if self.cmb_dir.current() == 0:
            s = core.build_alter(lb, c["owner"], c["table"], c["ca"], c["cb"])
        else:
            s = core.build_alter(la, c["owner"], c["table"], c["cb"], c["ca"])
        self.txt_alter.delete("1.0", "end")
        self.txt_alter.insert("1.0", s)

    def save_alter(self):
        s = self.txt_alter.get("1.0", "end").strip()
        if not s:
            messagebox.showinfo("Sin script", "Genere primero el script.")
            return
        c = self.ctx
        p = filedialog.asksaveasfilename(defaultextension=".sql", initialdir=core.BASE_DIR,
                                         initialfile=f"alter_{c['table']}.sql", filetypes=[("SQL", "*.sql")])
        if p:
            Path(p).write_text(s + "\n", encoding="utf-8")
            self.status.set(f"Script guardado: {p}")

    @staticmethod
    def _cols(text):
        return [k.strip().upper() for k in text.split(",") if k.strip()]

    def pick_columns(self, var, title):
        if not self.ctx:
            return
        cols = self.ctx["common"]
        cur = set(self._cols(var.get()))
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("340x440")
        win.transient(self)
        ttk.Label(win, text=f"{title}\n(clic para marcar / desmarcar)").pack(anchor="w", padx=8, pady=6)
        fr = ttk.Frame(win)
        fr.pack(fill="both", expand=True, padx=8)
        lb = tk.Listbox(fr, selectmode="multiple", exportselection=False)
        sb = ttk.Scrollbar(fr, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for i, col in enumerate(cols):
            lb.insert("end", col)
            if col in cur:
                lb.selection_set(i)

        def ok():
            var.set(", ".join(cols[i] for i in lb.curselection()))
            win.destroy()

        row = ttk.Frame(win)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Button(row, text="Aceptar", command=ok).pack(side="left")
        ttk.Button(row, text="Limpiar", command=lambda: lb.selection_clear(0, "end")).pack(side="left", padx=6)
        ttk.Button(row, text="Cancelar", command=win.destroy).pack(side="right")
        win.grab_set()

    def do_data(self):
        c = self.ctx
        keys = self._cols(self.key_var.get())
        bad = [k for k in keys if k not in c["common"]]
        if not keys or bad:
            messagebox.showwarning("Clave inválida", "Indique columnas clave existentes en ambas tablas" + (f" (no válidas: {', '.join(bad)})" if bad else "."))
            return
        inc, exc = self._cols(self.inc_var.get()), self._cols(self.exc_var.get())
        bad = [k for k in inc + exc if k not in c["common"]]
        if bad:
            messagebox.showwarning("Columnas inválidas", f"No existen en ambas tablas: {', '.join(bad)}")
            return
        if inc:
            cmp_cols = [x for x in inc if x not in keys]
            if exc:
                core.log("Se indicaron columnas 'solo estas': se ignora la lista de exclusión.")
        else:
            cmp_cols = [x for x in c["common"] if x not in keys and x not in exc]
        if not cmp_cols:
            messagebox.showwarning("Sin columnas", "No queda ninguna columna por comparar (las claves no se comparan).")
            return
        core.log(f"Columnas a comparar ({len(cmp_cols)}): {', '.join(cmp_cols)}")
        where = re.sub(r"^\s*where\s+", "", self.where_var.get(), flags=re.I).strip()
        la, lb = self.labels
        ea, eb = self.engines

        def work():
            ra = core.fetch_rows(ea, c["owner"], c["table"], c["common"], where,
                                 lambda n: self.post(lambda: self.status.set(f"Leyendo {la}: {n} filas...")))
            rb = core.fetch_rows(eb, c["owner"], c["table"], c["common"], where,
                                 lambda n: self.post(lambda: self.status.set(f"Leyendo {lb}: {n} filas...")))
            self.post(lambda: self.status.set("Comparando registros..."))
            core.log("Comparando registros ...")
            return core.compare_data(la, lb, c["owner"], c["table"], where, c["common"], keys, ra, rb, cmp_cols)

        def done(r):
            self.result = r
            self.tree_data.heading("va", text=f"Valor {la}")
            self.tree_data.heading("vb", text=f"Valor {lb}")
            self.tree_data.delete(*self.tree_data.get_children())
            shown = 0
            for k, fields in r["diffs"]:
                for col, va, vb in fields:
                    if shown >= MAX_ROWS_VIEW:
                        break
                    self.tree_data.insert("", "end", tags=("dif",),
                                          values=("Diferencia", core.key_text(keys, k), col, core.show(va, 120), core.show(vb, 120)))
                    shown += 1
            for lst, lab in ((r["only_a"], f"Solo en {la}"), (r["only_b"], f"Solo en {lb}")):
                for k in lst:
                    if shown >= MAX_ROWS_VIEW:
                        break
                    self.tree_data.insert("", "end", tags=("solo",), values=(lab, core.key_text(keys, k), "", "", ""))
                    shown += 1
            tot = sum(len(f) for _, f in r["diffs"]) + len(r["only_a"]) + len(r["only_b"])
            msg = (f"{la}: {r['n_a']} | {lb}: {r['n_b']} registros ({len(r['cmp_cols'])} columnas comparadas) — {len(r['diffs'])} con diferencias, "
                   f"{len(r['only_a'])} solo en {la}, {len(r['only_b'])} solo en {lb}")
            if tot > shown:
                msg += f"  (pantalla limitada a {MAX_ROWS_VIEW} filas; el reporte exportado es completo)"
            if r["dups_a"] or r["dups_b"]:
                msg += f"  ⚠ claves duplicadas: {la}={r['dups_a']}, {lb}={r['dups_b']}"
            self.data_summary.set(msg)
            core.log(msg)
            self.btn_export.config(state="normal")
            self.status.set("Comparación terminada.")

        self.run_async(work, done, "Consultando ambas BD...")

    def do_export(self):
        if not self.result:
            return
        d = filedialog.askdirectory(initialdir=core.BASE_DIR, title="Carpeta donde guardar la salida")
        if not d:
            return
        r = self.result
        out = Path(d) / f"salida_{r['owner']}_{r['table']}_{datetime.now():%Y%m%d_%H%M%S}"
        files = core.export_all(r, out)
        self.status.set(f"Exportado en {out}")
        core.log(f"Exportado en {out}: " + ", ".join(f.name for f in files))
        messagebox.showinfo("Exportación lista", f"Carpeta:\n{out}\n\n" + "\n".join(f.name for f in files))
        try:
            os.startfile(out)  # Windows
        except Exception:
            pass


if __name__ == "__main__":
    App().mainloop()
