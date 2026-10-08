from __future__ import annotations

import asyncio
import queue
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, simpledialog, ttk

import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from snmp_monitor.alerts import alert_messages, send_email
from snmp_monitor.config import APP_DIR, DATABASE_PATH, AppConfig
from snmp_monitor.models import InterfaceInfo, Sample
from snmp_monitor.repository import SampleRepository
from snmp_monitor.snmp_client import SnmpClient


BG = "#111a1d"
PANEL = "#182529"
PANEL_ALT = "#203237"
TEXT = "#e8f0ed"
MUTED = "#9ab0aa"
ACCENT = "#63d6b4"
ORANGE = "#f3a765"
GRID = "#34494b"


class MonitorApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Observatório SNMP | Monitor de roteador")
        self.root.geometry("1320x900")
        self.root.minsize(720, 600)
        self.root.configure(bg=BG)
        self.config = AppConfig.load()
        self.repository = SampleRepository(DATABASE_PATH)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.samples: list[Sample] = []
        self.interfaces: list[InterfaceInfo] = []
        self.previous_alert_state = {"cpu": False, "traffic": False}
        self.interface_by_label: dict[str, InterfaceInfo] = {}
        self.responsive_forms: dict[ttk.Frame, list[ttk.Frame]] = {}
        self.chart_frames: dict[str, ttk.Frame] = {}
        self.last_layout_mode: str | None = None
        self._build_styles()
        self._build_layout()
        self.root.bind("<Configure>", self._on_resize)
        self.root.after_idle(lambda: self._relayout(self.root.winfo_width()))
        self.root.after(150, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("DejaVu Sans", 10))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("DejaVu Sans", 19, "bold"))
        style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=("DejaVu Sans", 11, "bold"))
        style.configure("TButton", padding=(10, 7), background=PANEL_ALT, foreground=TEXT)
        style.map("TButton", background=[("active", "#2d4849")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#10201c", font=("DejaVu Sans", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#8ce8ca")])
        style.configure("TEntry", fieldbackground="#0f181a", foreground=TEXT, insertcolor=TEXT, padding=6)
        style.configure("TCombobox", fieldbackground="#0f181a", foreground=TEXT, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#0f181a")], foreground=[("readonly", TEXT)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL_ALT, foreground=TEXT, padding=(15, 8))
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", ACCENT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)

    def _build_layout(self) -> None:
        shell = ttk.Frame(self.root, padding=(20, 16))
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="Observatório SNMP", style="Title.TLabel").pack(side="left")
        self.status_var = tk.StringVar(value="Desconectado")
        ttk.Label(header, textvariable=self.status_var, foreground=MUTED).pack(side="right", padx=8)
        self.status_dot = tk.Label(header, text="●", fg="#899a95", bg=BG, font=("DejaVu Sans", 11))
        self.status_dot.pack(side="right")

        self._build_connection(shell)
        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill="both", expand=True, pady=(12, 0))
        live_tab = ttk.Frame(self.notebook, padding=10)
        history_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(live_tab, text="  Tempo real  ")
        self.notebook.add(history_tab, text="  Histórico  ")
        self.live_traffic = self._build_chart(live_tab, "live_traffic", "Tráfego da interface", [ACCENT, ORANGE], ["Entrada", "Saída"])
        self.live_cpu = self._build_chart(live_tab, "live_cpu", "Uso da CPU", [ACCENT], ["CPU média"])
        self.history_traffic = self._build_chart(history_tab, "history_traffic", "Histórico de tráfego", [ACCENT, ORANGE], ["Entrada", "Saída"])
        self.history_cpu = self._build_chart(history_tab, "history_cpu", "Histórico de CPU", [ACCENT], ["CPU média"])
        self._build_history_controls(history_tab)

    def _panel(self, parent: ttk.Frame, title: str, column: int) -> ttk.Frame:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        panel.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 6 if column == 0 else 0), pady=4)
        ttk.Label(panel, text=title, style="Section.TLabel").grid(row=0, column=0, sticky="w", columnspan=4, pady=(0, 8))
        return panel

    def _build_connection(self, parent: ttk.Frame) -> None:
        row = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        row.pack(fill="x")

        self.host_var = tk.StringVar(value=self.config.router_host)
        self.community_var = tk.StringVar(value=self.config.community)
        self.port_var = tk.StringVar(value=str(self.config.port))
        self.interval_var = tk.StringVar(value=str(self.config.interval_seconds))
        self.interface_var = tk.StringVar()
        self.cpu_limit_var = tk.StringVar(value=str(self.config.alert_cpu_percent))
        self.traffic_limit_var = tk.StringVar(value=str(self.config.alert_traffic_bytes_sec / 1_000_000))
        self.alert_mode_var = tk.StringVar(value=self.config.alert_mode)
        self.email_var = tk.StringVar(value=self.config.email_to)
        self.smtp_host_var = tk.StringVar(value=self.config.smtp_host)
        self.smtp_port_var = tk.StringVar(value=str(self.config.smtp_port))
        self.smtp_user_var = tk.StringVar(value=self.config.smtp_username)
        self.email_from_var = tk.StringVar(value=self.config.email_from)

        self._field(row, "IP / host do roteador", self.host_var, 0, 0)
        self._field(row, "Comunidade SNMP", self.community_var, 1, 0, show="•")
        self._field(row, "Porta", self.port_var, 2, 0)
        self.interface_combo = self._labeled(
            row,
            "Interface ligada ao computador",
            lambda group: ttk.Combobox(group, textvariable=self.interface_var, state="readonly"),
            3,
            0,
        )
        self._field(row, "Coleta (segundos)", self.interval_var, 7, 0)
        actions = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 0, 12, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="Descobrir", command=self._discover).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Iniciar", style="Accent.TButton", command=self._start).pack(side="left", padx=6)
        ttk.Button(actions, text="Parar", command=self._stop).pack(side="left", padx=6)

        settings = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 8))
        settings.pack(fill="x", pady=(8, 0))
        self._field(settings, "Alerta CPU (%)", self.cpu_limit_var, 0, 0)
        self._field(settings, "Alerta tráfego (MB/s)", self.traffic_limit_var, 1, 0)
        self._labeled(
            settings,
            "Tipo de alerta",
            lambda group: ttk.Combobox(
                group,
                textvariable=self.alert_mode_var,
                values=("popup", "email"),
                state="readonly",
            ),
            2,
            0,
        )
        self._field(settings, "Destinatário email", self.email_var, 3, 0)
        self._field(settings, "Servidor SMTP", self.smtp_host_var, 4, 0)
        self._field(settings, "Porta SMTP", self.smtp_port_var, 5, 0)
        self._field(settings, "Usuário SMTP", self.smtp_user_var, 6, 0)
        self._field(settings, "Remetente", self.email_from_var, 7, 0)

    def _labeled(self, parent: ttk.Frame, label: str, widget_factory, column: int, row: int):
        group = ttk.Frame(parent, style="Panel.TFrame")
        ttk.Label(group, text=label, style="Muted.TLabel").pack(anchor="w", padx=4)
        widget = widget_factory(group)
        widget.pack(fill="x", padx=4, pady=(2, 4))
        group.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
        self.responsive_forms.setdefault(parent, []).append(group)
        return widget

    def _field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, column: int, row: int, show: str = "") -> None:
        self._labeled(
            parent,
            label,
            lambda group: ttk.Entry(group, textvariable=variable, show=show),
            column,
            row,
        )

    def _build_chart(self, parent: ttk.Frame, chart_id: str, title: str, colors: list[str], labels: list[str]):
        holder = ttk.Frame(parent, style="Panel.TFrame", padding=(9, 7))
        self.chart_frames[chart_id] = holder
        ttk.Label(holder, text=title, style="Section.TLabel").pack(anchor="w")
        figure = Figure(figsize=(6, 3.0), dpi=100, facecolor=PANEL)
        axis = figure.add_subplot(111)
        self._style_axis(axis)
        lines = [axis.plot([], [], color=color, linewidth=2, label=label)[0] for color, label in zip(colors, labels)]
        axis.legend(loc="upper left", frameon=False, labelcolor=TEXT)
        figure.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(figure, master=holder)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        return axis, lines, canvas

    def _on_resize(self, event: tk.Event) -> None:
        if event.widget is self.root:
            self._relayout(event.width)

    def _relayout(self, width: int) -> None:
        if width >= 1100:
            mode, form_columns, charts_side_by_side = "wide", 4, True
        elif width >= 760:
            mode, form_columns, charts_side_by_side = "medium", 2, False
        else:
            mode, form_columns, charts_side_by_side = "narrow", 1, False
        if mode == self.last_layout_mode:
            return
        self.last_layout_mode = mode

        for parent, groups in self.responsive_forms.items():
            for column in range(4):
                parent.columnconfigure(column, weight=1 if column < form_columns else 0)
            for index, group in enumerate(groups):
                group.grid_configure(row=index // form_columns, column=index % form_columns)

        for traffic_id, cpu_id in (("live_traffic", "live_cpu"), ("history_traffic", "history_cpu")):
            traffic_frame = self.chart_frames[traffic_id]
            cpu_frame = self.chart_frames[cpu_id]
            tab = traffic_frame.master
            traffic_frame.grid_forget()
            cpu_frame.grid_forget()
            tab.columnconfigure(0, weight=1)
            tab.columnconfigure(1, weight=1 if charts_side_by_side else 0)
            tab.rowconfigure(0, weight=1)
            tab.rowconfigure(1, weight=0 if charts_side_by_side else 1)
            if charts_side_by_side:
                traffic_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)
                cpu_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=4)
            else:
                traffic_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
                cpu_frame.grid(row=1, column=0, sticky="nsew")

        history_tab = self.chart_frames["history_traffic"].master
        history_tab.rowconfigure(2, weight=0)
        if hasattr(self, "history_controls"):
            self.history_controls.grid_configure(
                row=1 if charts_side_by_side else 2,
                column=0,
                columnspan=2 if charts_side_by_side else 1,
            )

    @staticmethod
    def _style_axis(axis) -> None:
        axis.set_facecolor(PANEL)
        axis.tick_params(colors=MUTED, labelsize=8)
        axis.grid(color=GRID, linewidth=0.6, alpha=0.8)
        axis.spines["bottom"].set_color(GRID)
        axis.spines["left"].set_color(GRID)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    def _build_history_controls(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        controls.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.history_controls = controls
        now = datetime.now()
        self.history_start_var = tk.StringVar(value=(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"))
        self.history_end_var = tk.StringVar(value=now.strftime("%Y-%m-%d %H:%M"))
        ttk.Label(controls, text="De (AAAA-MM-DD HH:MM)", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        ttk.Entry(controls, textvariable=self.history_start_var, width=18).pack(side="left", padx=(0, 12))
        ttk.Label(controls, text="Até", style="Muted.TLabel").pack(side="left", padx=(0, 5))
        ttk.Entry(controls, textvariable=self.history_end_var, width=18).pack(side="left", padx=(0, 12))
        ttk.Button(controls, text="Aplicar intervalo", command=self._refresh_history).pack(side="left")
        self.history_count_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self.history_count_var, style="Muted.TLabel").pack(side="right")

    def _config_from_fields(self) -> AppConfig:
        interval = int(self.interval_var.get())
        port = int(self.port_var.get())
        smtp_port = int(self.smtp_port_var.get())
        cpu_limit = float(self.cpu_limit_var.get())
        traffic_limit = float(self.traffic_limit_var.get())
        if interval < 1 or not 1 <= port <= 65535 or not 1 <= smtp_port <= 65535:
            raise ValueError("Intervalo deve ser maior que zero e portas devem estar entre 1 e 65535.")
        if not 0 <= cpu_limit <= 100 or traffic_limit <= 0:
            raise ValueError("CPU deve estar entre 0 e 100% e o limite de tráfego deve ser positivo.")
        selected = self.interface_by_label.get(self.interface_var.get())
        return AppConfig(
            router_host=self.host_var.get().strip(),
            community=self.community_var.get(),
            port=port,
            interval_seconds=interval,
            interface_index=selected.index if selected else self.config.interface_index,
            cpu_oid=self.config.cpu_oid,
            alert_cpu_percent=cpu_limit,
            alert_traffic_bytes_sec=traffic_limit * 1_000_000,
            alert_mode=self.alert_mode_var.get(),
            email_to=self.email_var.get().strip(),
            smtp_host=self.smtp_host_var.get().strip(),
            smtp_port=smtp_port,
            smtp_username=self.smtp_user_var.get().strip(),
            email_from=self.email_from_var.get().strip(),
        )

    def _save_config(self) -> AppConfig:
        config = self._config_from_fields()
        if not config.router_host:
            raise ValueError("Informe o IP ou nome do roteador.")
        if config.alert_mode == "email" and not (config.email_to and config.smtp_host and config.email_from):
            raise ValueError("Para alertas por email, preencha destinatário, servidor SMTP e remetente.")
        config.save()
        self.config = config
        return config

    def _discover(self) -> None:
        try:
            config = self._save_config()
        except (ValueError, OSError) as error:
            messagebox.showerror("Configuração", str(error), parent=self.root)
            return
        self.status_var.set("Consultando interfaces via SNMP...")
        threading.Thread(target=self._discover_worker, args=(config,), daemon=True).start()

    def _discover_worker(self, config: AppConfig) -> None:
        client = SnmpClient(config.router_host, config.community, config.port)
        try:
            interfaces, preferred = asyncio.run(client.discover_interfaces())
            self.events.put(("interfaces", interfaces, preferred))
        except Exception as error:
            self.events.put(("error", f"Falha ao consultar SNMP: {error}"))
        finally:
            client.close()

    def _start(self) -> None:
        try:
            config = self._save_config()
        except (ValueError, OSError) as error:
            messagebox.showerror("Configuração", str(error), parent=self.root)
            return
        if config.interface_index <= 0:
            messagebox.showerror("Interface", "Descubra e selecione uma interface antes de iniciar.", parent=self.root)
            return
        self.stop_event.set()
        self.stop_event = threading.Event()
        self.samples.clear()
        self.previous_alert_state = {"cpu": False, "traffic": False}
        self.status_var.set("Conectando via SNMP...")
        self.worker = threading.Thread(target=self._monitor_worker, args=(config, self.stop_event), daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("Monitoramento parado")
        self.status_dot.configure(fg="#899a95")

    def _monitor_worker(self, config: AppConfig, stop_event: threading.Event) -> None:
        try:
            asyncio.run(self._monitor_loop(config, stop_event))
        except Exception as error:
            self.events.put(("error", f"Falha SNMP: {error}"))

    async def _monitor_loop(self, config: AppConfig, stop_event: threading.Event) -> None:
        client = SnmpClient(config.router_host, config.community, config.port)
        previous: Sample | None = None
        self.events.put(("status", "Monitorando"))
        try:
            while not stop_event.is_set():
                sample = await client.sample(config.interface_index, config.cpu_oid, previous)
                previous = sample
                self.events.put(("sample", sample))
                await asyncio.sleep(config.interval_seconds)
        finally:
            client.close()

    def _process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "interfaces":
                    _, interfaces, preferred = event
                    self.interfaces = interfaces
                    self.interface_by_label = {interface.label: interface for interface in interfaces}
                    labels = list(self.interface_by_label)
                    self.interface_combo.configure(values=labels)
                    chosen = next((item for item in interfaces if item.index == preferred), None)
                    if chosen is None and self.config.interface_index:
                        chosen = next((item for item in interfaces if item.index == self.config.interface_index), None)
                    if chosen is None and interfaces:
                        chosen = interfaces[0]
                    if chosen:
                        self.interface_var.set(chosen.label)
                        self.config.interface_index = chosen.index
                    self.status_var.set(f"{len(interfaces)} interface(s) encontrada(s)")
                    if not interfaces:
                        messagebox.showwarning("Interfaces", "Nenhuma interface IPv4 foi encontrada; verifique SNMP e MIBs do roteador.", parent=self.root)
                elif event[0] == "sample":
                    self._handle_sample(event[1])
                elif event[0] == "status":
                    self.status_var.set(event[1])
                    self.status_dot.configure(fg=ACCENT)
                elif event[0] == "error":
                    self.status_var.set("Erro na comunicação SNMP")
                    self.status_dot.configure(fg=ORANGE)
                    messagebox.showerror("Monitor SNMP", event[1], parent=self.root)
        except queue.Empty:
            pass
        self.root.after(150, self._process_events)

    def _handle_sample(self, sample: Sample) -> None:
        self.samples.append(sample)
        cutoff = sample.timestamp - 600
        self.samples = [item for item in self.samples if item.timestamp >= cutoff]
        self.repository.add(sample)
        self._draw_live()
        self._check_alerts(sample)

    def _draw(
        self,
        chart,
        timestamps: list[float],
        values: list[list[float]],
        ylabel: str,
        limit: tuple[float, float] | None = None,
        sliding: bool = True,
    ) -> None:
        axis, lines, canvas = chart
        dates = [datetime.fromtimestamp(timestamp) for timestamp in timestamps]
        for line, series in zip(lines, values):
            line.set_data(dates, series)
        axis.set_ylabel(ylabel, color=MUTED, fontsize=8)
        if dates:
            if sliding:
                axis.set_xlim(max(dates[0], dates[-1] - timedelta(minutes=10)), dates[-1] + timedelta(seconds=1))
            elif dates[0] == dates[-1]:
                axis.set_xlim(dates[0] - timedelta(seconds=30), dates[-1] + timedelta(seconds=30))
            else:
                axis.set_xlim(dates[0], dates[-1])
            maximum = max((max(series) for series in values if series), default=1)
            axis.set_ylim(0, limit[1] if limit else max(1, maximum * 1.2))
        else:
            axis.set_xlim(datetime.now() - timedelta(minutes=10), datetime.now())
            axis.set_ylim(0, limit[1] if limit else 100)
        canvas.draw_idle()

    def _draw_live(self) -> None:
        timestamps = [sample.timestamp for sample in self.samples]
        self._draw(self.live_traffic, timestamps, [[sample.rx_bytes_sec for sample in self.samples], [sample.tx_bytes_sec for sample in self.samples]], "Bytes/s")
        self._draw(self.live_cpu, timestamps, [[sample.cpu_percent for sample in self.samples]], "%", (0, 100))

    def _refresh_history(self) -> None:
        try:
            start = datetime.strptime(self.history_start_var.get(), "%Y-%m-%d %H:%M").timestamp()
            end = datetime.strptime(self.history_end_var.get(), "%Y-%m-%d %H:%M").timestamp()
        except ValueError:
            messagebox.showerror("Intervalo", "Use o formato AAAA-MM-DD HH:MM.", parent=self.root)
            return
        if start > end:
            messagebox.showerror("Intervalo", "A data inicial deve ser anterior à data final.", parent=self.root)
            return
        history = self.repository.between(start, end)
        timestamps = [sample.timestamp for sample in history]
        self._draw(self.history_traffic, timestamps, [[sample.rx_bytes_sec for sample in history], [sample.tx_bytes_sec for sample in history]], "Bytes/s", sliding=False)
        self._draw(self.history_cpu, timestamps, [[sample.cpu_percent for sample in history]], "%", (0, 100), sliding=False)
        self.history_count_var.set(f"{len(history)} amostras")

    def _check_alerts(self, sample: Sample) -> None:
        cpu_active = sample.cpu_percent >= self.config.alert_cpu_percent
        traffic_active = max(sample.rx_bytes_sec, sample.tx_bytes_sec) >= self.config.alert_traffic_bytes_sec
        newly_active = []
        if cpu_active and not self.previous_alert_state["cpu"]:
            newly_active.extend(alert_messages(sample, self.config)[:1])
        if traffic_active and not self.previous_alert_state["traffic"]:
            messages = alert_messages(sample, self.config)
            if len(messages) > (1 if cpu_active else 0):
                newly_active.append(messages[-1])
        self.previous_alert_state = {"cpu": cpu_active, "traffic": traffic_active}
        if not newly_active:
            return
        body = "\n".join(newly_active)
        if self.config.alert_mode == "email":
            password = ""
            if self.config.smtp_username:
                password = simpledialog.askstring("Autenticação SMTP", "Senha SMTP (não será armazenada):", show="*", parent=self.root) or ""
            threading.Thread(target=self._send_alert_worker, args=(body, password), daemon=True).start()
            self.status_var.set("Enviando alerta por email...")
        else:
            messagebox.showwarning("Alerta do roteador", body, parent=self.root)

    def _send_alert_worker(self, body: str, password: str) -> None:
        try:
            send_email(self.config, "Alerta de monitoramento SNMP", body, password)
            self.events.put(("status", "Alerta enviado por email"))
        except Exception as error:
            self.events.put(("error", f"Não foi possível enviar o email: {error}"))

    def _close(self) -> None:
        self.stop_event.set()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()