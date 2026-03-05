# -*- coding: utf-8 -*-
"""
==============================================================
  MOTOR DE TRANSACCIONES BANCARIAS - Interfaz Tkinter
==============================================================
"""

import uuid
import time
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from collections import deque
from enum import Enum


# ─────────────────────────────────────────────────────────────
# ENUMERACIONES
# ─────────────────────────────────────────────────────────────

class TipoTransaccion(Enum):
    DEPOSITO      = "DEPOSITO"
    RETIRO        = "RETIRO"
    TRANSFERENCIA = "TRANSFERENCIA"

class EstadoTransaccion(Enum):
    PENDIENTE  = "PENDIENTE"
    PROCESANDO = "PROCESANDO"
    COMPLETADA = "COMPLETADA"
    FALLIDA    = "FALLIDA"
    REVERTIDA  = "REVERTIDA"


# ─────────────────────────────────────────────────────────────
# MODELO: Cuenta
# ─────────────────────────────────────────────────────────────

class Cuenta:
    def __init__(self, titular: str, saldo_inicial: float = 0.0):
        self.id      = str(uuid.uuid4())[:8].upper()
        self.titular = titular
        self._saldo  = saldo_inicial
        self.creada  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def saldo(self):
        return self._saldo

    def depositar(self, monto: float):
        if monto <= 0:
            raise ValueError("El monto debe ser positivo.")
        self._saldo += monto

    def retirar(self, monto: float):
        if monto <= 0:
            raise ValueError("El monto debe ser positivo.")
        if monto > self._saldo:
            raise ValueError(f"Saldo insuficiente. Disponible: ${self._saldo:,.2f}")
        self._saldo -= monto


# ─────────────────────────────────────────────────────────────
# MODELO: Transaccion
# ─────────────────────────────────────────────────────────────

class Transaccion:
    def __init__(self, tipo, monto, cuenta_origen, cuenta_destino=None):
        self.id             = str(uuid.uuid4())[:10].upper()
        self.tipo           = tipo
        self.monto          = monto
        self.cuenta_origen  = cuenta_origen
        self.cuenta_destino = cuenta_destino
        self.estado         = EstadoTransaccion.PENDIENTE
        self.timestamp      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.error_msg      = None


# ─────────────────────────────────────────────────────────────
# ESTRUCTURA 1: ColaTransacciones (FIFO)
# ─────────────────────────────────────────────────────────────

class ColaTransacciones:
    def __init__(self):
        self._cola = deque()

    def encolar(self, tx):
        self._cola.append(tx)

    def desencolar(self):
        if self.esta_vacia():
            raise IndexError("Cola vacía.")
        return self._cola.popleft()

    def esta_vacia(self):
        return len(self._cola) == 0

    def tamanio(self):
        return len(self._cola)

    def lista(self):
        return list(self._cola)


# ─────────────────────────────────────────────────────────────
# ESTRUCTURA 2: PilaCompensacion (LIFO)
# ─────────────────────────────────────────────────────────────

class PilaCompensacion:
    def __init__(self):
        self._pila = []

    def apilar(self, paso):
        self._pila.append(paso)

    def desapilar(self):
        return self._pila.pop()

    def esta_vacia(self):
        return len(self._pila) == 0

    def ejecutar_rollback(self, log_fn=None):
        msgs = []
        while not self.esta_vacia():
            paso = self.desapilar()
            try:
                paso['revertir']()
                msgs.append(f"  [ROLLBACK] Revertido: {paso['nombre']}")
            except Exception as e:
                msgs.append(f"  [ROLLBACK] Error al revertir {paso['nombre']}: {e}")
        if log_fn:
            for m in msgs:
                log_fn(m)

    def limpiar(self):
        self._pila.clear()


# ─────────────────────────────────────────────────────────────
# ESTRUCTURA 3: RegistroErrores (Array fijo)
# ─────────────────────────────────────────────────────────────

class RegistroErrores:
    def __init__(self, capacidad=10):
        self._cap    = capacidad
        self._arr    = [None] * capacidad
        self._idx    = 0
        self._total  = 0

    def registrar(self, tx):
        self._arr[self._idx % self._cap] = {
            "id":        tx.id,
            "tipo":      tx.tipo.value,
            "monto":     tx.monto,
            "titular":   tx.cuenta_origen.titular,
            "error":     tx.error_msg,
            "timestamp": tx.timestamp,
        }
        self._idx   += 1
        self._total += 1

    def obtener_todos(self):
        cantidad = min(self._total, self._cap)
        resultado = []
        for i in range(cantidad):
            idx = (self._idx - cantidad + i) % self._cap
            if self._arr[idx]:
                resultado.append(self._arr[idx])
        return resultado


# ─────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────

class MotorTransacciones:
    def __init__(self, log_fn=None):
        self._cola    = ColaTransacciones()
        self._pila    = PilaCompensacion()
        self._errores = RegistroErrores(10)
        self._cuentas = {}
        self._log     = log_fn or print

    def crear_cuenta(self, titular, saldo_inicial=0.0):
        c = Cuenta(titular, saldo_inicial)
        self._cuentas[c.id] = c
        self._log(f"[OK] Cuenta creada: {c.titular} | ID: {c.id} | Saldo: ${saldo_inicial:,.2f}")
        return c

    def buscar_cuenta(self, cid):
        c = self._cuentas.get(cid.upper())
        if not c:
            raise KeyError(f"Cuenta '{cid}' no encontrada.")
        return c

    def listar_cuentas(self):
        return list(self._cuentas.values())

    def solicitar_deposito(self, cuenta, monto):
        tx = Transaccion(TipoTransaccion.DEPOSITO, monto, cuenta)
        self._cola.encolar(tx)
        self._log(f"[COLA] + Deposito encolado: ${monto:,.2f} para {cuenta.titular}")
        return tx

    def solicitar_retiro(self, cuenta, monto):
        tx = Transaccion(TipoTransaccion.RETIRO, monto, cuenta)
        self._cola.encolar(tx)
        self._log(f"[COLA] + Retiro encolado: ${monto:,.2f} de {cuenta.titular}")
        return tx

    def solicitar_transferencia(self, origen, destino, monto):
        tx = Transaccion(TipoTransaccion.TRANSFERENCIA, monto, origen, destino)
        self._cola.encolar(tx)
        self._log(f"[COLA] + Transferencia encolada: ${monto:,.2f} de {origen.titular} a {destino.titular}")
        return tx

    def procesar_siguiente(self):
        if self._cola.esta_vacia():
            self._log("[!] No hay transacciones pendientes.")
            return None
        tx = self._cola.desencolar()
        tx.estado = EstadoTransaccion.PROCESANDO
        self._log(f"\n--- Procesando [{tx.id}] {tx.tipo.value} ${tx.monto:,.2f} ---")
        try:
            if tx.tipo == TipoTransaccion.DEPOSITO:
                self._hacer_deposito(tx)
            elif tx.tipo == TipoTransaccion.RETIRO:
                self._hacer_retiro(tx)
            elif tx.tipo == TipoTransaccion.TRANSFERENCIA:
                self._hacer_transferencia(tx)
            tx.estado = EstadoTransaccion.COMPLETADA
            self._log(f"[OK] Transaccion COMPLETADA: {tx.id}")
        except Exception as e:
            tx.estado    = EstadoTransaccion.FALLIDA
            tx.error_msg = str(e)
            self._log(f"[FALLO] Transaccion FALLIDA: {tx.id} — {e}")
            self._pila.ejecutar_rollback(self._log)
            tx.estado = EstadoTransaccion.REVERTIDA
            self._errores.registrar(tx)
        return tx

    def procesar_todo(self):
        n = self._cola.tamanio()
        if n == 0:
            self._log("[!] Cola vacía.")
            return
        self._log(f"\n[*] Procesando {n} transacciones...")
        while not self._cola.esta_vacia():
            self.procesar_siguiente()

    def _hacer_deposito(self, tx):
        self._pila.limpiar()
        c = tx.cuenta_origen
        self._pila.apilar({"nombre": "Validar monto", "revertir": lambda: None})
        if tx.monto <= 0:
            raise ValueError("Monto invalido.")
        self._log(f"  [PASO 1] Monto valido: ${tx.monto:,.2f}")
        self._pila.apilar({"nombre": "Acreditar saldo", "revertir": lambda: c.retirar(tx.monto)})
        c.depositar(tx.monto)
        self._log(f"  [PASO 2] Saldo acreditado. Nuevo saldo: ${c.saldo:,.2f}")
        self._pila.limpiar()

    def _hacer_retiro(self, tx):
        self._pila.limpiar()
        c = tx.cuenta_origen
        self._pila.apilar({"nombre": "Validar monto", "revertir": lambda: None})
        if tx.monto <= 0:
            raise ValueError("Monto invalido.")
        self._log(f"  [PASO 1] Monto valido: ${tx.monto:,.2f}")
        self._pila.apilar({"nombre": "Validar saldo", "revertir": lambda: None})
        if tx.monto > c.saldo:
            raise ValueError(f"Saldo insuficiente. Disponible: ${c.saldo:,.2f}")
        self._log(f"  [PASO 2] Saldo suficiente: ${c.saldo:,.2f}")
        self._pila.apilar({"nombre": "Descontar saldo", "revertir": lambda: c.depositar(tx.monto)})
        c.retirar(tx.monto)
        self._log(f"  [PASO 3] Saldo descontado. Nuevo saldo: ${c.saldo:,.2f}")
        self._pila.limpiar()

    def _hacer_transferencia(self, tx):
        self._pila.limpiar()
        o, d = tx.cuenta_origen, tx.cuenta_destino
        self._pila.apilar({"nombre": "Validar saldo origen", "revertir": lambda: None})
        if tx.monto > o.saldo:
            raise ValueError(f"Saldo insuficiente en '{o.titular}'. Disponible: ${o.saldo:,.2f}")
        self._log(f"  [PASO 1] Saldo origen valido: ${o.saldo:,.2f}")
        self._pila.apilar({"nombre": "Descontar origen", "revertir": lambda: o.depositar(tx.monto)})
        o.retirar(tx.monto)
        self._log(f"  [PASO 2] Descontado de '{o.titular}'. Saldo: ${o.saldo:,.2f}")
        self._pila.apilar({"nombre": "Acreditar destino", "revertir": lambda: d.retirar(tx.monto)})
        d.depositar(tx.monto)
        self._log(f"  [PASO 3] Acreditado en '{d.titular}'. Saldo: ${d.saldo:,.2f}")
        self._pila.limpiar()

    def ver_errores(self):
        return self._errores.obtener_todos()

    def cola_pendiente(self):
        return self._cola.tamanio()

    def cola_lista(self):
        return self._cola.lista()


# ─────────────────────────────────────────────────────────────
# COLORES Y ESTILOS
# ─────────────────────────────────────────────────────────────

BG        = "#0d1117"
BG2       = "#161b22"
BG3       = "#21262d"
ACCENT    = "#238636"
ACCENT2   = "#1f6feb"
RED       = "#da3633"
YELLOW    = "#e3b341"
TEXT      = "#e6edf3"
TEXT2     = "#8b949e"
BORDER    = "#30363d"
WHITE     = "#ffffff"
GREEN_LT  = "#3fb950"
BLUE_LT   = "#58a6ff"
RED_LT    = "#ff7b72"


# ─────────────────────────────────────────────────────────────
# VENTANA PRINCIPAL
# ─────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Motor de Transacciones Bancarias")
        self.geometry("1100x700")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self.resizable(True, True)

        # Motor con log conectado a la consola interna
        self.motor = MotorTransacciones(log_fn=self._log)

        self._build_ui()
        self._log("Sistema iniciado. Crea una cuenta para comenzar.")

    # ── Construcción de UI ──────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=10)
        hdr.pack(fill="x", padx=20)

        tk.Label(hdr, text="MOTOR DE TRANSACCIONES BANCARIAS",
                 font=("Courier", 16, "bold"), fg=BLUE_LT, bg=BG).pack(side="left")

        self._lbl_cola = tk.Label(hdr, text="Cola: 0 pendientes",
                                   font=("Courier", 10), fg=YELLOW, bg=BG)
        self._lbl_cola.pack(side="right", padx=10)

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.pack(fill="x")

        # Cuerpo principal
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        # Columna izquierda: acciones
        left = tk.Frame(body, bg=BG, width=280)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        self._build_panel_acciones(left)

        # Columna central: cuentas + cola
        center = tk.Frame(body, bg=BG)
        center.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self._build_panel_cuentas(center)

        # Columna derecha: log + errores
        right = tk.Frame(body, bg=BG, width=320)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self._build_panel_log(right)

    # ── Panel izquierdo: botones de acción ──────────────────

    def _build_panel_acciones(self, parent):
        tk.Label(parent, text="ACCIONES", font=("Courier", 11, "bold"),
                 fg=TEXT2, bg=BG).pack(anchor="w", pady=(0, 8))

        acciones = [
            ("Nueva Cuenta",          ACCENT,  self._dlg_crear_cuenta),
            ("Depositar",             ACCENT2, self._dlg_depositar),
            ("Retirar",               ACCENT2, self._dlg_retirar),
            ("Transferir",            ACCENT2, self._dlg_transferir),
            ("Consultar Saldo",       BG3,     self._dlg_consultar),
            ("Procesar Siguiente",    YELLOW,  self._procesar_siguiente),
            ("Procesar Todo",         YELLOW,  self._procesar_todo),
            ("Ver Errores",           RED,     self._ver_errores),
        ]

        for texto, color, cmd in acciones:
            btn = tk.Button(parent, text=texto, bg=color, fg=WHITE,
                            font=("Courier", 10, "bold"), relief="flat",
                            activebackground=WHITE, activeforeground=BG,
                            cursor="hand2", padx=10, pady=8,
                            command=cmd)
            btn.pack(fill="x", pady=3)

    # ── Panel central: tabla de cuentas + cola ──────────────

    def _build_panel_cuentas(self, parent):
        # Tabla de cuentas
        tk.Label(parent, text="CUENTAS REGISTRADAS", font=("Courier", 11, "bold"),
                 fg=TEXT2, bg=BG).pack(anchor="w", pady=(0, 4))

        frame_tbl = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        frame_tbl.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Bank.Treeview",
                        background=BG2, foreground=TEXT,
                        fieldbackground=BG2, rowheight=26,
                        font=("Courier", 10))
        style.configure("Bank.Treeview.Heading",
                        background=BG3, foreground=TEXT2,
                        font=("Courier", 10, "bold"), relief="flat")
        style.map("Bank.Treeview", background=[("selected", ACCENT2)])

        self._tbl_cuentas = ttk.Treeview(frame_tbl,
            columns=("id", "titular", "saldo", "creada"),
            show="headings", style="Bank.Treeview")

        for col, ancho, txt in [
            ("id",      90,  "ID"),
            ("titular", 160, "Titular"),
            ("saldo",   120, "Saldo"),
            ("creada",  160, "Creada"),
        ]:
            self._tbl_cuentas.heading(col, text=txt)
            self._tbl_cuentas.column(col, width=ancho, anchor="center")

        sb = ttk.Scrollbar(frame_tbl, orient="vertical",
                           command=self._tbl_cuentas.yview)
        self._tbl_cuentas.configure(yscrollcommand=sb.set)
        self._tbl_cuentas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Cola pendiente
        tk.Label(parent, text="COLA DE TRANSACCIONES (FIFO)",
                 font=("Courier", 11, "bold"), fg=TEXT2, bg=BG).pack(
                     anchor="w", pady=(12, 4))

        frame_cola = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        frame_cola.pack(fill="x")

        self._tbl_cola = ttk.Treeview(frame_cola,
            columns=("pos", "id", "tipo", "monto", "titular"),
            show="headings", style="Bank.Treeview", height=5)

        for col, ancho, txt in [
            ("pos",     40,  "#"),
            ("id",      110, "ID"),
            ("tipo",    110, "Tipo"),
            ("monto",   100, "Monto"),
            ("titular", 150, "Titular"),
        ]:
            self._tbl_cola.heading(col, text=txt)
            self._tbl_cola.column(col, width=ancho, anchor="center")

        self._tbl_cola.pack(fill="x")

    # ── Panel derecho: log de eventos ───────────────────────

    def _build_panel_log(self, parent):
        tk.Label(parent, text="CONSOLA DE EVENTOS", font=("Courier", 11, "bold"),
                 fg=TEXT2, bg=BG).pack(anchor="w", pady=(0, 4))

        frame_log = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        frame_log.pack(fill="both", expand=True)

        self._txt_log = tk.Text(frame_log, bg=BG2, fg=GREEN_LT,
                                 font=("Courier", 9), relief="flat",
                                 wrap="word", state="disabled",
                                 insertbackground=TEXT)
        sb2 = tk.Scrollbar(frame_log, command=self._txt_log.yview, bg=BG3)
        self._txt_log.configure(yscrollcommand=sb2.set)
        self._txt_log.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        # Tags de color
        self._txt_log.tag_config("ok",     foreground=GREEN_LT)
        self._txt_log.tag_config("fallo",  foreground=RED_LT)
        self._txt_log.tag_config("cola",   foreground=BLUE_LT)
        self._txt_log.tag_config("pila",   foreground=YELLOW)
        self._txt_log.tag_config("info",   foreground=TEXT2)

        btn_limpiar = tk.Button(parent, text="Limpiar consola",
                                bg=BG3, fg=TEXT2, font=("Courier", 9),
                                relief="flat", cursor="hand2",
                                command=self._limpiar_log)
        btn_limpiar.pack(fill="x", pady=(4, 0))

    # ── Sistema de log ──────────────────────────────────────

    def _log(self, msg: str):
        self._txt_log.config(state="normal")
        ts  = datetime.now().strftime("%H:%M:%S")
        tag = "info"
        if "[OK]" in msg or "COMPLETADA" in msg or "creada" in msg.lower():
            tag = "ok"
        elif "[FALLO]" in msg or "FALLIDA" in msg or "ROLLBACK" in msg or "insuficiente" in msg.lower():
            tag = "fallo"
        elif "[COLA]" in msg:
            tag = "cola"
        elif "[PILA]" in msg or "PASO" in msg:
            tag = "pila"

        self._txt_log.insert("end", f"[{ts}] {msg}\n", tag)
        self._txt_log.see("end")
        self._txt_log.config(state="disabled")

    def _limpiar_log(self):
        self._txt_log.config(state="normal")
        self._txt_log.delete("1.0", "end")
        self._txt_log.config(state="disabled")

    # ── Actualizar tablas ───────────────────────────────────

    def _refrescar_cuentas(self):
        for row in self._tbl_cuentas.get_children():
            self._tbl_cuentas.delete(row)
        for c in self.motor.listar_cuentas():
            self._tbl_cuentas.insert("", "end",
                values=(c.id, c.titular, f"${c.saldo:,.2f}", c.creada))

    def _refrescar_cola(self):
        for row in self._tbl_cola.get_children():
            self._tbl_cola.delete(row)
        for i, tx in enumerate(self.motor.cola_lista(), 1):
            dest = f" -> {tx.cuenta_destino.titular}" if tx.cuenta_destino else ""
            self._tbl_cola.insert("", "end",
                values=(i, tx.id, tx.tipo.value, f"${tx.monto:,.2f}",
                        tx.cuenta_origen.titular + dest))
        self._lbl_cola.config(text=f"Cola: {self.motor.cola_pendiente()} pendientes")

    def _refrescar(self):
        self._refrescar_cuentas()
        self._refrescar_cola()

    # ── Diálogos ────────────────────────────────────────────

    def _dlg_crear_cuenta(self):
        dlg = Dialogo(self, "Nueva Cuenta", bg=BG2)
        dlg.agregar_campo("Nombre del titular:")
        dlg.agregar_campo("Saldo inicial ($):", default="0")
        if dlg.mostrar():
            titular = dlg.valores[0].strip()
            if not titular:
                messagebox.showerror("Error", "El nombre no puede estar vacio.")
                return
            try:
                saldo = float(dlg.valores[1]) if dlg.valores[1] else 0.0
                self.motor.crear_cuenta(titular, saldo)
                self._refrescar()
            except ValueError as e:
                messagebox.showerror("Error", str(e))

    def _dlg_depositar(self):
        cuentas = self.motor.listar_cuentas()
        if not cuentas:
            messagebox.showwarning("Aviso", "No hay cuentas creadas.")
            return
        dlg = Dialogo(self, "Depositar", bg=BG2)
        dlg.agregar_selector("Cuenta:", [(f"{c.id} - {c.titular}", c.id) for c in cuentas])
        dlg.agregar_campo("Monto ($):")
        if dlg.mostrar():
            try:
                cid   = dlg.valores[0]
                monto = float(dlg.valores[1])
                cuenta = self.motor.buscar_cuenta(cid)
                self.motor.solicitar_deposito(cuenta, monto)
                self._refrescar()
            except (KeyError, ValueError) as e:
                messagebox.showerror("Error", str(e))

    def _dlg_retirar(self):
        cuentas = self.motor.listar_cuentas()
        if not cuentas:
            messagebox.showwarning("Aviso", "No hay cuentas creadas.")
            return
        dlg = Dialogo(self, "Retirar", bg=BG2)
        dlg.agregar_selector("Cuenta:", [(f"{c.id} - {c.titular}", c.id) for c in cuentas])
        dlg.agregar_campo("Monto ($):")
        if dlg.mostrar():
            try:
                cid   = dlg.valores[0]
                monto = float(dlg.valores[1])
                cuenta = self.motor.buscar_cuenta(cid)
                self.motor.solicitar_retiro(cuenta, monto)
                self._refrescar()
            except (KeyError, ValueError) as e:
                messagebox.showerror("Error", str(e))

    def _dlg_transferir(self):
        cuentas = self.motor.listar_cuentas()
        if len(cuentas) < 2:
            messagebox.showwarning("Aviso", "Necesitas al menos 2 cuentas para transferir.")
            return
        opciones = [(f"{c.id} - {c.titular}", c.id) for c in cuentas]
        dlg = Dialogo(self, "Transferir", bg=BG2)
        dlg.agregar_selector("Cuenta ORIGEN:", opciones)
        dlg.agregar_selector("Cuenta DESTINO:", opciones)
        dlg.agregar_campo("Monto ($):")
        if dlg.mostrar():
            try:
                if dlg.valores[0] == dlg.valores[1]:
                    messagebox.showerror("Error", "Origen y destino no pueden ser iguales.")
                    return
                origen  = self.motor.buscar_cuenta(dlg.valores[0])
                destino = self.motor.buscar_cuenta(dlg.valores[1])
                monto   = float(dlg.valores[2])
                self.motor.solicitar_transferencia(origen, destino, monto)
                self._refrescar()
            except (KeyError, ValueError) as e:
                messagebox.showerror("Error", str(e))

    def _dlg_consultar(self):
        cuentas = self.motor.listar_cuentas()
        if not cuentas:
            messagebox.showwarning("Aviso", "No hay cuentas creadas.")
            return
        dlg = Dialogo(self, "Consultar Saldo", bg=BG2)
        dlg.agregar_selector("Cuenta:", [(f"{c.id} - {c.titular}", c.id) for c in cuentas])
        if dlg.mostrar():
            try:
                c = self.motor.buscar_cuenta(dlg.valores[0])
                messagebox.showinfo("Saldo",
                    f"ID:      {c.id}\n"
                    f"Titular: {c.titular}\n"
                    f"Saldo:   ${c.saldo:,.2f}\n"
                    f"Creada:  {c.creada}")
            except KeyError as e:
                messagebox.showerror("Error", str(e))

    def _procesar_siguiente(self):
        self.motor.procesar_siguiente()
        self._refrescar()

    def _procesar_todo(self):
        self.motor.procesar_todo()
        self._refrescar()

    def _ver_errores(self):
        errores = self.motor.ver_errores()
        if not errores:
            messagebox.showinfo("Errores", "No hay errores registrados.")
            return

        win = tk.Toplevel(self)
        win.title("Errores Registrados")
        win.configure(bg=BG)
        win.geometry("700x300")

        tk.Label(win, text="ULTIMAS TRANSACCIONES FALLIDAS",
                 font=("Courier", 12, "bold"), fg=RED_LT, bg=BG).pack(pady=10)

        frame = tk.Frame(win, bg=BORDER, padx=1, pady=1)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        style = ttk.Style()
        style.configure("Err.Treeview",
                        background=BG2, foreground=TEXT,
                        fieldbackground=BG2, rowheight=24,
                        font=("Courier", 9))
        style.configure("Err.Treeview.Heading",
                        background=BG3, foreground=RED_LT,
                        font=("Courier", 9, "bold"), relief="flat")

        tbl = ttk.Treeview(frame,
            columns=("id", "tipo", "monto", "titular", "error", "fecha"),
            show="headings", style="Err.Treeview")

        for col, ancho, txt in [
            ("id",      100, "ID"),
            ("tipo",     90, "Tipo"),
            ("monto",    90, "Monto"),
            ("titular",  110, "Titular"),
            ("error",    180, "Error"),
            ("fecha",    130, "Fecha"),
        ]:
            tbl.heading(col, text=txt)
            tbl.column(col, width=ancho, anchor="center")

        for e in errores:
            tbl.insert("", "end", values=(
                e["id"], e["tipo"], f"${e['monto']:,.2f}",
                e["titular"], e["error"], e["timestamp"]))

        sb = ttk.Scrollbar(frame, orient="vertical", command=tbl.yview)
        tbl.configure(yscrollcommand=sb.set)
        tbl.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")


# ─────────────────────────────────────────────────────────────
# CLASE AUXILIAR: Dialogo generico
# ─────────────────────────────────────────────────────────────

class Dialogo:
    def __init__(self, parent, titulo, bg=BG2):
        self._parent  = parent
        self._titulo  = titulo
        self._bg      = bg
        self._campos  = []   # lista de (tipo, label, widget_var, opciones)
        self.valores  = []
        self._ok      = False

    def agregar_campo(self, label, default=""):
        self._campos.append(("entry", label, default, None))

    def agregar_selector(self, label, opciones):
        # opciones = [(texto_visible, valor), ...]
        self._campos.append(("combo", label, None, opciones))

    def mostrar(self):
        win = tk.Toplevel(self._parent)
        win.title(self._titulo)
        win.configure(bg=self._bg)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text=self._titulo, font=("Courier", 12, "bold"),
                 fg=BLUE_LT, bg=self._bg).pack(pady=(14, 8), padx=20)

        widgets = []
        for tipo, label, default, opciones in self._campos:
            row = tk.Frame(win, bg=self._bg)
            row.pack(fill="x", padx=20, pady=4)
            tk.Label(row, text=label, font=("Courier", 10),
                     fg=TEXT, bg=self._bg, width=22, anchor="w").pack(side="left")

            if tipo == "entry":
                var = tk.StringVar(value=default or "")
                e = tk.Entry(row, textvariable=var, bg=BG3, fg=TEXT,
                             insertbackground=TEXT, font=("Courier", 10),
                             relief="flat", width=20)
                e.pack(side="left", padx=(4, 0))
                widgets.append(("entry", var))
            else:
                textos  = [o[0] for o in opciones]
                valores = [o[1] for o in opciones]
                var = tk.StringVar(value=valores[0] if valores else "")
                cb  = ttk.Combobox(row, textvariable=var,
                                   values=textos, state="readonly",
                                   font=("Courier", 10), width=22)
                cb.current(0)
                cb.pack(side="left", padx=(4, 0))
                # guardamos texto->valor
                widgets.append(("combo", var, textos, valores))

        def confirmar():
            self.valores = []
            for item in widgets:
                if item[0] == "entry":
                    self.valores.append(item[1].get())
                else:
                    _, var, textos, valores = item
                    txt = var.get()
                    # buscar el valor real por texto
                    for t, v in zip(textos, valores):
                        if t == txt:
                            self.valores.append(v)
                            break
                    else:
                        self.valores.append(valores[0] if valores else "")
            self._ok = True
            win.destroy()

        def cancelar():
            win.destroy()

        btns = tk.Frame(win, bg=self._bg)
        btns.pack(pady=14, padx=20)
        tk.Button(btns, text="Confirmar", bg=ACCENT, fg=WHITE,
                  font=("Courier", 10, "bold"), relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  command=confirmar).pack(side="left", padx=6)
        tk.Button(btns, text="Cancelar", bg=BG3, fg=TEXT2,
                  font=("Courier", 10), relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  command=cancelar).pack(side="left", padx=6)

        self._parent.wait_window(win)
        return self._ok


# ─────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
