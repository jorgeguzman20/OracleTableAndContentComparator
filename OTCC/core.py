
import os
import re
import sys
import runpy
import socket
import threading
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote_plus



import oracledb

from sqlalchemy import create_engine, text


if getattr(sys, "frozen", False):
    _user_root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    BASE_DIR = _user_root / "ComparadorTablasOracle"
else:
    BASE_DIR = Path(__file__).resolve().parent
BASE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = BASE_DIR / "config.py"
DEFAULT_INSTANT_CLIENT_DIR = Path(r"C:\instantclient_19_32")
_DLL_DIRECTORY_HANDLE = None



oracledb.defaults.fetch_lobs = False

import faulthandler

if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):

    _console = open(BASE_DIR / "comparador_console.log", "a", encoding="utf-8", buffering=1)

    if sys.stdout is None:

        sys.stdout = _console

    if sys.stderr is None:

        sys.stderr = _console

try:

    faulthandler.enable(file=sys.stderr)  # volcado ante fallos nativos

except Exception:

    pass



LOG_FILE = BASE_DIR / "comparador.log"

_log_cb = None





def set_logger(cb):

    global _log_cb

    _log_cb = cb





def log(msg, ui=True):

    line = f"{datetime.now():%H:%M:%S}  {msg}"

    try:

        with open(LOG_FILE, "a", encoding="utf-8") as fh:

            fh.write(line + "\n")

    except Exception:

        pass

    if ui and _log_cb:

        _log_cb(line)





def log_environment():

    import platform

    parts = [f"Python {platform.python_version()} {platform.architecture()[0]}",

             "ejecutable empaquetado" if getattr(sys, "frozen", False) else "ejecución con python",

             f"oracledb {oracledb.__version__}"]

    try:

        import sqlalchemy

        parts.append(f"SQLAlchemy {sqlalchemy.__version__}")

    except Exception as e:

        parts.append(f"SQLAlchemy ERROR {e}")

    try:

        import cryptography

        parts.append(f"cryptography {cryptography.__version__}")

    except Exception as e:

        parts.append(f"cryptography NO DISPONIBLE ({e})")

    log("Entorno: " + " | ".join(parts))







_client_mode = None  # None = aún no decidido | "thick" | "thin"

_client_dir = None





def client_mode():

    return _client_mode





def _candidate_dirs(explicit=""):

    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())


    candidates.append(DEFAULT_INSTANT_CLIENT_DIR)


    install_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    try:
        candidates.extend(p for p in install_dir.glob("instantclient*") if p.is_dir())
    except OSError:
        pass


    try:
        root = Path(os.environ.get("SystemDrive", "C:") + "\\")
        candidates.extend(p for p in root.glob("instantclient*") if p.is_dir())
    except OSError:
        pass

    seen = set()
    result = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).lower()
        if key not in seen and resolved.is_dir() and (resolved / "oci.dll").is_file():
            seen.add(key)
            result.append(resolved)
    return result


def init_client(explicit_dir=""):
    """Inicializa Oracle Client en modo THICK desde el hilo principal."""
    global _client_mode, _client_dir, _DLL_DIRECTORY_HANDLE

    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "init_client() debe ejecutarse desde el hilo principal antes de "
            "iniciar tareas en segundo plano."
        )

    if _client_mode is not None:
        log(f"Modo Oracle ya definido en esta sesión: {_client_mode} ({_client_dir or 'sin ruta'})")
        return _client_mode

    log(f"python-oracledb {oracledb.__version__}")
    log(f"Arquitectura del proceso: {__import__('struct').calcsize('P') * 8} bits")

    candidates = _candidate_dirs(explicit_dir.strip())
    if not candidates:
        msg = ("No se encontró oci.dll. Se esperaba Oracle Instant Client en "
               f"'{explicit_dir or DEFAULT_INSTANT_CLIENT_DIR}'.")
        log(msg)
        raise FileNotFoundError(msg)

    errors = []
    for directory in candidates:
        try:
            log(f"Intentando inicializar Oracle Instant Client desde: {directory}")

            if os.name == "nt" and hasattr(os, "add_dll_directory"):
                _DLL_DIRECTORY_HANDLE = os.add_dll_directory(str(directory))
            oracledb.init_oracle_client(lib_dir=str(directory))
            if oracledb.is_thin_mode():
                raise RuntimeError("python-oracledb continúa en modo Thin después de init_oracle_client().")

            version = tuple(oracledb.clientversion())
            if not version or version[0] < 19:
                raise RuntimeError(f"Versión de Oracle Client no soportada: {version}")

            _client_mode = "thick"
            _client_dir = str(directory)
            log(f"Oracle Client inicializado correctamente. Modo THICK. Ruta: {_client_dir}")
            log(f"Versión real cargada de Oracle Client: {version}")
            log(f"Modo Thin reportado por python-oracledb: {oracledb.is_thin_mode()}")
            return _client_mode
        except Exception as exc:
            detail = f"{directory}: {type(exc).__name__}: {exc}"
            errors.append(detail)
            log(f"ERROR inicializando Oracle Client: {detail}")
            if _DLL_DIRECTORY_HANDLE is not None:
                try:
                    _DLL_DIRECTORY_HANDLE.close()
                except Exception:
                    pass
                _DLL_DIRECTORY_HANDLE = None
    details = "\n".join(errors)
    raise RuntimeError("No fue posible inicializar Oracle Instant Client en modo THICK:\n" + details)







def load_config():


    if not CONFIG_FILE.exists():

        return []

    try:

        envs = runpy.run_path(str(CONFIG_FILE)).get("ENVIRONMENTS", {})

    except Exception:

        return []

    out = []

    for name, c in list(envs.items())[:2]:

        out.append({"NAME": name, "DB_USER": c.get("DB_USER", ""), "DB_HOST": c.get("DB_HOST", ""),

                    "DB_PORT": c.get("DB_PORT", 1521), "DB_SERVICE": c.get("DB_SERVICE", "")})

    return out





def load_instant_dir():

    if CONFIG_FILE.exists():
        try:
            configured = runpy.run_path(str(CONFIG_FILE)).get("INSTANT_CLIENT_DIR", "") or ""
            if configured:
                return configured
        except Exception as exc:
            log(f"No se pudo leer la ruta de Instant Client desde config.py: {exc}")
    return str(DEFAULT_INSTANT_CLIENT_DIR) if (DEFAULT_INSTANT_CLIENT_DIR / "oci.dll").is_file() else ""





def write_config(envs, instant_dir=""):

    lines = [f"INSTANT_CLIENT_DIR = {instant_dir!r}", "", "ENVIRONMENTS = {"]

    for c in envs:

        lines += [

            f"    {c['NAME']!r}: {{",

            f"        'DB_USER': {c['DB_USER']!r},",

            "        'DB_PASSWORD': '',",

            f"        'DB_HOST': {c['DB_HOST']!r},",

            f"        'DB_PORT': {int(c['DB_PORT'])},",

            f"        'DB_SERVICE': {c['DB_SERVICE']!r},",

            "    },",

        ]

    lines.append("}")

    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")





def get_engine(c):

    dsn = oracledb.makedsn(c["DB_HOST"], int(c["DB_PORT"]), service_name=c["DB_SERVICE"])

    url = f"oracle+oracledb://{quote_plus(c['DB_USER'])}:{quote_plus(c['DB_PASSWORD'])}@{dsn}"

    log(f"Creando engine Oracle para {c['DB_HOST']}:{c['DB_PORT']}/{c['DB_SERVICE']} (usuario {c['DB_USER']})")
    return create_engine(url, connect_args={"tcp_connect_timeout": 10})





def check_port(host, port, timeout=8):

    """Verifica que el host:puerto responde (evita quedarse colgado sin mensaje)."""

    try:

        with socket.create_connection((host, int(port)), timeout=timeout):

            return

    except Exception as e:
        raise ConnectionError(f"No hay respuesta de {host}:{port} en {timeout}s ({e}). Revise VPN/red/firewall/IP.")





def test_connection(engine, timeout=30):

    box = {}



    def t():

        try:

            with engine.connect() as cn:

                cn.execute(text("SELECT 1 FROM dual"))

            box["ok"] = True

        except Exception as e:

            box["err"] = e


    dump_path = BASE_DIR / "hang_dump.log"

    fh = open(dump_path, "a", encoding="utf-8")

    fh.write(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} intento de conexión ====\n")

    fh.flush()

    faulthandler.dump_traceback_later(15, repeat=False, file=fh)

    try:

        th = threading.Thread(target=t, daemon=True)

        th.start()

        th.join(timeout)

        if th.is_alive():

            try:

                import traceback

                fr = sys._current_frames().get(th.ident)

                if fr:

                    log("Hilo de conexión bloqueado en:\n" + "".join(traceback.format_stack(fr)))

            except Exception:

                pass

            raise TimeoutError(f"El servidor aceptó la conexión de red pero no respondió en {timeout}s (revise service name/listener).")

        if "err" in box:

            raise box["err"]

    finally:

        faulthandler.cancel_dump_traceback_later()

        fh.close()






def parse_table(full):

    full = (full or "").strip().upper()

    if re.fullmatch(r"[A-Z0-9_$#]+\.[A-Z0-9_$#]+", full):

        return tuple(full.split("."))

    return None





def get_columns(engine, owner, table):

    sql = text("""

        SELECT column_name, data_type, data_length, data_precision, data_scale, char_length, char_used

          FROM all_tab_columns

         WHERE owner = :o AND table_name = :t

         ORDER BY column_id""")

    with engine.connect() as cn:

        rows = cn.execute(sql, {"o": owner, "t": table}).fetchall()

    cols = {}

    for name, dt, dlen, prec, scale, clen, cused in rows:

        if dt in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"):

            t = f"{dt}({clen}{' CHAR' if cused == 'C' and dt in ('VARCHAR2', 'CHAR') else ''})"

        elif dt == "NUMBER":

            if prec is None and scale is None:

                t = "NUMBER"

            elif prec is None:

                t = f"NUMBER(*,{scale})"

            else:

                t = f"NUMBER({prec},{scale})" if scale else f"NUMBER({prec})"

        elif dt == "RAW":

            t = f"RAW({dlen})"

        else:

            t = dt

        cols[name] = t

    return cols





def get_pk(engine, owner, table):

    sql = text("""

        SELECT cc.column_name

          FROM all_constraints c

          JOIN all_cons_columns cc ON cc.owner = c.owner AND cc.constraint_name = c.constraint_name

         WHERE c.constraint_type = 'P' AND c.owner = :o AND c.table_name = :t

         ORDER BY cc.position""")

    with engine.connect() as cn:

        return [r[0] for r in cn.execute(sql, {"o": owner, "t": table})]





def compare_columns(a, b):

    only_a = [c for c in a if c not in b]

    only_b = [c for c in b if c not in a]

    diff = [(c, a[c], b[c]) for c in a if c in b and a[c] != b[c]]

    return only_a, only_b, diff





def build_alter(target_label, owner, table, src_cols, tgt_cols):

    """Script para que la tabla destino quede igual a la origen."""

    out = [f"-- Script para igualar la estructura de {owner}.{table} en {target_label}"]

    for c, t in src_cols.items():

        if c not in tgt_cols:

            out.append(f'ALTER TABLE {owner}.{table} ADD ("{c}" {t});')

    for c, t in src_cols.items():

        if c in tgt_cols and tgt_cols[c] != t:

            out.append(f'ALTER TABLE {owner}.{table} MODIFY ("{c}" {t});  -- era {tgt_cols[c]} (puede fallar si hay datos incompatibles)')

    for c in tgt_cols:

        if c not in src_cols:

            out.append(f'-- ALTER TABLE {owner}.{table} DROP COLUMN "{c}";  -- columna sobrante, descomentar bajo su responsabilidad')

    if len(out) == 1:

        out.append("-- Sin diferencias de estructura.")

    return "\n".join(out) + "\n"





# ---------------------------------------------------------------------- datos

def fetch_rows(engine, owner, table, cols, where, progress=None):

    collist = ", ".join(f'"{c}"' for c in cols)

    sql = f"SELECT {collist} FROM {owner}.{table}" + (f" WHERE {where}" if where else "")

    rows = []

    log(f"Ejecutando: {sql}")

    with engine.connect().execution_options(stream_results=True) as cn:

        for r in cn.execute(text(sql)):

            rows.append(tuple(r))

            if progress and len(rows) % 5000 == 0:

                progress(len(rows))

    if progress:

        progress(len(rows))

    log(f"   {len(rows)} filas leídas")

    return rows





def compare_data(la, lb, owner, table, where, cols, pk, rows_a, rows_b, compare_cols=None):

    idx = [cols.index(k) for k in pk]

    cmp_cols = [c for c in (compare_cols or cols) if c not in pk]

    cmp_idx = [(c, cols.index(c)) for c in cmp_cols]



    def index(rows):

        d, dups = {}, 0

        for r in rows:

            k = tuple(r[i] for i in idx)

            if k in d:

                dups += 1

            d[k] = r

        return d, dups



    da, dups_a = index(rows_a)

    db, dups_b = index(rows_b)

    order = lambda ks: sorted(ks, key=lambda k: tuple(str(x) for x in k))

    only_a = order(k for k in da if k not in db)

    only_b = order(k for k in db if k not in da)

    diffs = []

    for k in order(k for k in da if k in db):

        fields = [(c, da[k][i], db[k][i]) for c, i in cmp_idx if da[k][i] != db[k][i]]

        if fields:

            diffs.append((k, fields))

    return dict(la=la, lb=lb, owner=owner, table=table, where=where, cols=cols, pk=pk, cmp_cols=cmp_cols,

                n_a=len(rows_a), n_b=len(rows_b), da=da, db=db, diffs=diffs,

                only_a=only_a, only_b=only_b, dups_a=dups_a, dups_b=dups_b)





# -------------------------------------------------------------------- scripts

def lit(v):

    if v is None:

        return "NULL"

    if isinstance(v, (datetime, date)):

        if not isinstance(v, datetime):

            v = datetime(v.year, v.month, v.day)

        return f"TO_TIMESTAMP('{v.strftime('%Y-%m-%d %H:%M:%S.%f')}','YYYY-MM-DD HH24:MI:SS.FF6')"

    if isinstance(v, bool):

        return "1" if v else "0"

    if isinstance(v, (int, float, Decimal)):

        return repr(v) if isinstance(v, float) else str(v)

    if isinstance(v, (bytes, bytearray)):

        h = bytes(v).hex().upper()

        return f"HEXTORAW('{h}')" if len(h) <= 4000 else "NULL /* BLOB/RAW demasiado grande: cargar aparte */"

    s = str(v).replace("'", "''")

    if len(s) <= 4000:

        return f"'{s}'"

    return "||".join(f"TO_CLOB('{s[i:i + 4000]}')" for i in range(0, len(s), 4000))





def show(v, limit=None):

    s = "<NULL>" if v is None else repr(v)

    return s if not limit or len(s) <= limit else s[:limit] + "…"





def key_text(pk, k):

    return ", ".join(f"{p}={show(v)}" for p, v in zip(pk, k))





def insert_stmt(owner, table, cols, row):

    cl = ", ".join(f'"{c}"' for c in cols)

    vl = ", ".join(lit(v) for v in row)

    return f"INSERT INTO {owner}.{table} ({cl}) VALUES ({vl});"





def update_stmt(owner, table, pk, key, fields):

    sets = ", ".join(f'"{c}" = {lit(v)}' for c, v in fields)

    wh = " AND ".join(f'"{p}" IS NULL' if v is None else f'"{p}" = {lit(v)}' for p, v in zip(pk, key))

    return f"UPDATE {owner}.{table} SET {sets} WHERE {wh};"





def _safe(s):

    return re.sub(r"[^A-Za-z0-9_-]", "_", s)





def build_report(r):

    la, lb, pk = r["la"], r["lb"], r["pk"]

    rep = [

        f"COMPARACION {r['owner']}.{r['table']}  {la} vs {lb}   ({datetime.now():%Y-%m-%d %H:%M:%S})",

        f"WHERE: {r['where'] or '(sin condición)'}",

        f"Clave: {', '.join(pk)}",

        "Columnas comparadas: " + (", ".join(r["cmp_cols"]) if len(r["cmp_cols"]) != len(r["cols"]) - len(pk) else "todas"),

        f"Registros {la}: {r['n_a']} | {lb}: {r['n_b']}",

        f"Con diferencias: {len(r['diffs'])} | Solo en {la}: {len(r['only_a'])} | Solo en {lb}: {len(r['only_b'])}",

    ]

    if r["dups_a"] or r["dups_b"]:

        rep.append(f"AVISO: claves duplicadas ({la}: {r['dups_a']}, {lb}: {r['dups_b']}); solo se compara el último de cada una.")

    rep += ["", "=" * 70, "REGISTROS CON DIFERENCIAS", "=" * 70]

    for k, fields in r["diffs"]:

        rep.append("Registro " + key_text(pk, k))

        for c, va, vb in fields:

            rep.append(f"   {c}:  {la}={show(va)}  |  {lb}={show(vb)}")

        rep.append("")

    rep += ["=" * 70, f"SOLO EN {la} (faltan en {lb})", "=" * 70]

    rep += ["Registro " + key_text(pk, k) for k in r["only_a"]]

    rep += ["", "=" * 70, f"SOLO EN {lb} (faltan en {la})", "=" * 70]

    rep += ["Registro " + key_text(pk, k) for k in r["only_b"]]

    return "\n".join(rep) + "\n"





def export_all(r, out_dir):

    """Escribe comparacion.txt + scripts. Devuelve la lista de archivos creados."""

    out_dir = Path(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    la, lb, owner, table, cols, pk = r["la"], r["lb"], r["owner"], r["table"], r["cols"], r["pk"]

    files = []



    def w(name, content):

        p = out_dir / name

        p.write_text(content, encoding="utf-8")

        files.append(p)



    w("comparacion.txt", build_report(r))

    if r["only_a"]:  # faltan en B

        w(f"inserts_para_{_safe(lb)}.sql", "\n".join(

            ["SET DEFINE OFF;"] + [insert_stmt(owner, table, cols, r["da"][k]) for k in r["only_a"]] + ["COMMIT;"]) + "\n")

    if r["only_b"]:  # faltan en A

        w(f"inserts_para_{_safe(la)}.sql", "\n".join(

            ["SET DEFINE OFF;"] + [insert_stmt(owner, table, cols, r["db"][k]) for k in r["only_b"]] + ["COMMIT;"]) + "\n")

    if r["diffs"]:

        # dejar B igual a A (valores de A) y dejar A igual a B (valores de B)

        w(f"updates_para_{_safe(lb)}.sql", "\n".join(

            ["SET DEFINE OFF;"] + [update_stmt(owner, table, pk, k, [(c, va) for c, va, _ in f]) for k, f in r["diffs"]] + ["COMMIT;"]) + "\n")

        w(f"updates_para_{_safe(la)}.sql", "\n".join(

            ["SET DEFINE OFF;"] + [update_stmt(owner, table, pk, k, [(c, vb) for c, _, vb in f]) for k, f in r["diffs"]] + ["COMMIT;"]) + "\n")

    return files