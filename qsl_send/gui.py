"""A small desktop window for qsl-send.

Written for operators who do not use a terminal. Every step the CLI exposes as
a flag is a button here, in the order the job is actually done:

    pick template -> find fields -> pick log -> generate -> review -> send

Deliberate safety properties, mirroring the CLI:
  * Sending is never one click from opening the app: you must generate first,
    then review the recipient list, then confirm a dialog that names the count.
  * A "Send test to myself" path exists and never marks anyone as mailed.
  * Everything long-running happens on a worker thread so the window cannot
    freeze; progress is streamed into the log pane.

Uses only tkinter, which ships with Python on Windows and is bundled by
PyInstaller, so the packaged app needs no extra runtime.
"""

from __future__ import annotations

import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - depends on the Python build
    raise SystemExit(
        "This build of Python has no tkinter, so the window cannot open.\n"
        "On Windows, install Python from python.org (tkinter is included)."
    ) from exc

from qsl_send.config import ConfigError, load_config
from qsl_send.i18n import SUPPORTED, get_language, set_language, t
from qsl_send.userdata import ensure_user_config, resolve_config
from qsl_send.settings_io import (
    SettingsWriteError,
    read_block_scalar,
    update_block_scalar,
    update_settings,
)
from qsl_send.contacts import Contact, ContactsError, load_contacts, save_contacts

APP_TITLE = "QSL Sender"

AUTHOR_CALLSIGN = "LU2AOG"


class _Console:
    """Thread-safe text sink that the worker writes and the UI drains."""

    def __init__(self, widget: tk.Text):
        self.widget = widget
        self.queue: queue.Queue[str] = queue.Queue()

    def write(self, line: str) -> None:
        self.queue.put(line)

    def drain(self) -> None:
        wrote = False
        while True:
            try:
                line = self.queue.get_nowait()
            except queue.Empty:
                break
            self.widget.configure(state="normal")
            self.widget.insert("end", line.rstrip() + "\n")
            wrote = True
        if wrote:
            self.widget.see("end")
            self.widget.configure(state="disabled")


class App:
    def __init__(self, root: tk.Tk, config_path: Path | None):
        self.root = root
        self.config_path = config_path
        self.worker: threading.Thread | None = None
        self.summary = None  # last generate result

        root.title(self._window_title())
        root.geometry("760x620")
        root.minsize(680, 560)
        # Centred on the screen: Tk defaults to the top-left corner.
        root.after(0, lambda: center_window(root))

        self.template = tk.StringVar()
        self.adif = tk.StringVar()
        self.outdir = tk.StringVar()
        self.status = tk.StringVar(value=t("Choose a card design and a log file."))

        self._build()
        self._load_config_defaults()
        self._tick()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True)

        # --- at-a-glance summary of who this copy is configured as ---
        summary = ttk.Frame(frm)
        summary.pack(fill="x", padx=10, pady=(8, 0))
        self.sum_vars: dict[str, tk.StringVar] = {}
        for i, (key, label) in enumerate([
            ("my_callsign", t("Callsign")),
            ("from_address", t("Sends from")),
            ("language", t("Language")),
            ("output_dir", t("Saving to")),
        ]):
            cell = ttk.Frame(summary)
            cell.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24), pady=1)
            ttk.Label(cell, text=f"{label}:", width=12).pack(side="left")
            var = tk.StringVar(value="—")
            self.sum_vars[key] = var
            ttk.Label(cell, textvariable=var, font=("", 0, "bold")).pack(side="left")
        ttk.Button(summary, text=t("Settings…"), command=self.on_settings).grid(
            row=0, column=2, rowspan=2, sticky="e", padx=4)
        summary.columnconfigure(2, weight=1)

        # --- inputs ---
        box = ttk.LabelFrame(frm, text=t("1. Files"))
        box.pack(fill="x", **pad)
        self._file_row(box, t("Card design"), self.template, self._pick_template,
                       [("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        self._file_row(box, t("Log file (ADIF)"), self.adif, self._pick_adif,
                       [("ADIF logs", "*.adi *.adif"), ("All files", "*.*")])
        self._file_row(box, t("Save cards to"), self.outdir, self._pick_outdir, None)

        # --- fields ---
        box2 = ttk.LabelFrame(frm, text=t("2. Card layout"))
        box2.pack(fill="x", **pad)
        row = ttk.Frame(box2)
        row.pack(fill="x", padx=8, pady=6)
        self.fields_label = ttk.Label(row, text=t("Fields not checked yet."))
        self.fields_label.pack(side="left")
        ttk.Button(row, text=t("Find fields automatically"),
                   command=self.on_detect).pack(side="right", padx=4)
        ttk.Button(row, text=t("Show me…"), command=self.on_preview_fields).pack(
            side="right", padx=4)

        # --- actions ---
        box3 = ttk.LabelFrame(frm, text=t("3. Make and send the cards"))
        box3.pack(fill="x", **pad)
        row2 = ttk.Frame(box3)
        row2.pack(fill="x", padx=8, pady=6)
        self.btn_generate = ttk.Button(row2, text=t("Make the cards"),
                                       command=self.on_generate)
        self.btn_generate.pack(side="left")
        self.btn_review = ttk.Button(row2, text=t("Review who gets one…"),
                                     command=self.on_review, state="disabled")
        self.btn_review.pack(side="left", padx=6)
        self.btn_test = ttk.Button(row2, text=t("Send a test to myself"),
                                   command=self.on_send_test, state="disabled")
        self.btn_test.pack(side="left", padx=6)
        self.btn_send = ttk.Button(row2, text=t("Send the e-mails"),
                                   command=self.on_send, state="disabled")
        self.btn_send.pack(side="right")

        # Shown only when an analysis finds contacts that could be completed.
        self.missing_row = ttk.Frame(box3)
        self.missing_var = tk.StringVar()
        ttk.Label(self.missing_row, textvariable=self.missing_var,
                  foreground="#a05000", wraplength=380,
                  justify="left").pack(side="left", padx=(0, 8))
        ttk.Button(self.missing_row, text=t("Complete the address book…"),
                   command=self.on_fix_contacts).pack(side="right")

        # --- log ---
        box4 = ttk.LabelFrame(frm, text=t("What happened"))
        box4.pack(fill="both", expand=True, **pad)
        self.text = tk.Text(box4, height=12, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(box4, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)
        self.console = _Console(self.text)

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(
            fill="x", padx=12, pady=4)

    def _file_row(self, parent, label, var, command, types):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text=label, width=16).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text=t("Choose…"), command=command).pack(side="left", padx=6)

    # ------------------------------------------------------------ behaviour

    def _load_config_defaults(self, keep_files: bool = False) -> None:
        """Populate the window from the configuration file.

        `keep_files` preserves whatever is currently in the Files section:
        after saving settings those values are already correct, and reloading
        them from disk would discard a file the user had just chosen.
        """
        try:
            cfg = load_config(self.config_path)
        except ConfigError as exc:
            self.log(t("Could not read the settings file: {error}", error=exc))
            return
        self.cfg = cfg
        if cfg.template:
            # Not named `t`: that shadows the translator imported above.
            template_path = cfg.resolve(cfg.template)
            if template_path and not (keep_files and self.template.get().strip()):
                self.template.set(str(template_path))
        if cfg.adif:
            a = cfg.resolve(cfg.adif)
            if a and not (keep_files and self.adif.get().strip()):
                self.adif.set(str(a))
        # A relative "output" resolves against the settings file. For an
        # installed application that file lives in AppData (or Application
        # Support), so the cards would land somewhere nobody would think to
        # look. Offer Documents instead — unless the folder already exists,
        # which means it is genuinely in use.
        from qsl_send.userdata import default_output_dir, user_config_dir

        out = cfg.resolve(cfg.output_dir)
        if out is not None:
            out = Path(out)
            inside_settings_dir = (
                cfg.path is not None
                and not Path(cfg.output_dir).is_absolute()
                and cfg.path.parent == user_config_dir()
            )
            if inside_settings_dir and not out.exists():
                out = default_output_dir()
        if not (keep_files and self.outdir.get().strip()):
            self.outdir.set(str(out or default_output_dir()))
        if cfg.render.fields:
            self.fields_label.configure(
                text=t("{count} fields configured.",
                       count=len(cfg.render.fields)))
        self._refresh_summary(cfg)

    def _window_title(self) -> str:
        """`QSL Sender - by LU2AOG`, crediting the author of the application."""
        return f"{t(APP_TITLE)} - {t('by {callsign}', callsign=AUTHOR_CALLSIGN)}"

    def _refresh_summary(self, cfg) -> None:
        """Mirror the key identity settings into the summary bar."""
        if not hasattr(self, "sum_vars"):
            return
        lang = cfg.language or t("follows the computer")
        self.sum_vars["my_callsign"].set(cfg.my_callsign or "—")
        self.sum_vars["from_address"].set(cfg.smtp.from_address or "—")
        self.sum_vars["language"].set(lang)
        # Read the field the window actually uses, not cfg.output_dir: the two
        # differ when a relative "output" was redirected away from the settings
        # directory, and showing the stale one made the bar disagree with where
        # the cards really go.
        chosen = self.outdir.get().strip()
        self.sum_vars["output_dir"].set(Path(chosen).name if chosen else "—")

    def on_settings(self) -> None:
        # Never refuse to open: if there is no settings file yet, make one from
        # the bundled example. Telling someone there is "nothing to edit" is a
        # dead end when editing is exactly what they are trying to do.
        if not self.config_path:
            created = ensure_user_config()
            if not created.is_file():
                messagebox.showerror(
                    t(APP_TITLE),
                    t("Could not create a settings file at {path}.",
                      path=created.parent))
                return
            self.config_path = created
            self.log(t("Created a settings file at {path}", path=created))
            self._load_config_defaults()
        SettingsDialog(self.root, self)

    def log(self, line: str) -> None:
        self.console.write(line)

    def _tick(self) -> None:
        self.console.drain()
        self.root.after(120, self._tick)

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.btn_generate.configure(state=state)
        if not busy:
            has = self.summary is not None
            self.btn_review.configure(state="normal" if has else "disabled")
            self.btn_send.configure(state="normal" if has else "disabled")
            self.btn_test.configure(state="normal" if has else "disabled")

    def _run(self, fn: Callable[[], None]) -> None:
        """Run `fn` on a worker thread, keeping the window responsive."""
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(t(APP_TITLE), t("Still working — please wait."))
            return

        def wrapped():
            try:
                fn()
            except Exception as exc:  # surface, never crash the window
                self.log(t("Something went wrong: {error}", error=exc))
                self.log(traceback.format_exc())
                self.status.set(t("Something went wrong — see the log below."))
            finally:
                self.root.after(0, lambda: self._busy(False))

        self._busy(True)
        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()

    # --------------------------------------------------------------- pickers

    def _pick_template(self):
        p = filedialog.askopenfilename(
            title=t("Choose your QSL card design"),
            filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        if p:
            self.template.set(p)
            self._offer_redetect(Path(p))

    def _offer_redetect(self, template: Path) -> None:
        """Find the boxes on a newly chosen card, without asking.

        Choosing a card design *is* the request to find its boxes — that is
        what the feature is for. Asking first treated detection as an unusual
        step, when it is the normal one; and saved coordinates belong to one
        particular image, so carrying them over to another card was never
        right.
        """
        self.on_detect(and_save=True)

    def _pick_adif(self):
        p = filedialog.askopenfilename(
            title=t("Choose your log file"),
            filetypes=[("ADIF logs", "*.adi *.adif"), ("All files", "*.*")])
        if p:
            self.adif.set(p)

    def _pick_outdir(self):
        p = filedialog.askdirectory(title=t("Where should the cards be saved?"))
        if p:
            self.outdir.set(p)
            # The summary bar mirrors this field, so it has to follow a manual
            # choice too — otherwise it keeps showing the previous folder while
            # the cards go somewhere else.
            if hasattr(self, "sum_vars"):
                self.sum_vars["output_dir"].set(Path(p).name)

    # --------------------------------------------------------------- actions

    def on_detect(self, and_save: bool = False):
        """Find the field boxes on the current card design.

        With `and_save`, the boxes and the card's pixel size are written to the
        configuration. Without it they are only reported, which is what the
        button on its own does.
        """
        template = self.template.get().strip()
        if not template:
            messagebox.showwarning(t(APP_TITLE), t("Choose a card design first."))
            return

        def work():
            from qsl_send.detect import detect_boxes, name_boxes
            self.status.set(t("Looking for the fields on the card…"))
            self.log(t("Looking at {name} …", name=Path(template).name))
            d = detect_boxes(template)
            if not d.boxes:
                self.log(t("No fields found. The boxes may not be a flat colour."))
                self.status.set(t("No fields found."))
                return
            named = name_boxes(d)
            self.log(t("Found {count} fields in {rows} row(s):",
                       count=len(d.boxes), rows=d.rows))
            for b, n, _v in named:
                self.log(f"    {n:<9} at {b.box}")
            self.log(t("Names are guessed from left-to-right order — "
                       "use 'Show me…' to check them on the card."))
            self.detected = (d, named)
            self.root.after(0, lambda: self.fields_label.configure(
                text=t("{count} fields found automatically.",
                       count=len(d.boxes))))
            self.status.set(t("Found {count} fields.", count=len(d.boxes)))

            if and_save and self.config_path:
                # Write the boxes AND the card's pixel size together. Saving
                # boxes without the size would leave them being scaled from a
                # stale reference, which is the very problem this fixes.
                try:
                    self._write_detected_fields(d, named)
                except Exception as exc:
                    self.log(t("Could not save the field boxes: {error}", error=exc))
                    return
                self.log(t("Saved the field boxes for this card."))
                self._load_config_defaults(keep_files=True)

        self._run(work)

    def _write_detected_fields(self, detection, named) -> None:
        """Replace render.template_size and render.fields in the config."""
        from qsl_send.settings_io import update_render_fields

        update_render_fields(
            self.config_path,
            detection.size,
            [(name, box.box, value) for box, name, value in named],
        )

    def on_preview_fields(self):
        template = self.template.get().strip()
        if not template:
            messagebox.showwarning(t(APP_TITLE), t("Choose a card design first."))
            return

        def work():
            from qsl_send.detect import detect_boxes, name_boxes
            from PIL import Image, ImageDraw
            d = detect_boxes(template)
            if not d.boxes:
                self.log(t("Nothing to show — no fields were found."))
                return
            img = Image.open(template).convert("RGB")
            draw = ImageDraw.Draw(img)
            for i, (b, n, _v) in enumerate(name_boxes(d)):
                x, y, w, h = b.box
                draw.rectangle([x - 2, y - 2, x + w + 2, y + h + 2],
                               outline=(255, 0, 0), width=3)
                draw.text((x + 4, max(0, y - 18)), f"{i} {n}", fill=(255, 0, 0))
            out = Path(self.outdir.get() or ".") / "field-check.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            img.save(out)
            self.log(t("Saved a marked-up copy to {path}", path=out))
            _open_file(out)

        self._run(work)

    def on_generate(self):
        adif = self.adif.get().strip()
        template = self.template.get().strip()
        outdir = self.outdir.get().strip()
        if not (adif and template and outdir):
            messagebox.showwarning(
                t(APP_TITLE), t("Choose a card design, a log file and a folder first."))
            return

        # One folder per activation. Ask before overwriting a different batch,
        # but stay quiet when simply regenerating the same one.
        from qsl_send.workspace import adif_dates, inspect, warning_for

        warning = warning_for(inspect(Path(outdir)), adif_dates(Path(adif)))
        if warning and not messagebox.askyesno(
            t("Check the folder"), warning + "\n\n" + t("Continue anyway?"),
            default="no", icon="warning",
        ):
            self.log(t("Cancelled — nothing was written."))
            return

        def work():
            from qsl_send.pipeline import generate_cards
            from qsl_send.report import format_summary, write_manifest

            cfg = load_config(self.config_path)
            contacts = {}
            if cfg.contacts_file:
                path = cfg.resolve(cfg.contacts_file)
                if path and Path(path).is_file():
                    try:
                        contacts, warns = load_contacts(path)
                        for w in warns:
                            self.log(f"! {w}")
                    except ContactsError as exc:
                        self.log(t("! Address book problem: {error}", error=exc))

            self.status.set(t("Making the cards…"))
            summary = generate_cards(
                cfg,
                adif_path=Path(adif),
                template_path=Path(template),
                output_dir=Path(outdir),
                contacts=contacts,
                progress=self.log,
            )
            write_manifest(summary, Path(outdir))
            self.log(format_summary(summary, Path(outdir)))
            self.summary = summary
            self.status.set(t(
                "{cards} cards made · {ready} ready to e-mail · "
                "{missing} with no address",
                cards=summary.cards_written,
                ready=summary.with_email,
                missing=summary.without_email))
            self.root.after(0, lambda: self._show_missing(summary))

        self._run(work)

    def _show_missing(self, summary) -> None:
        """Offer a direct route to the address book when contacts are lacking."""
        self._missing_calls = list(summary.needing_contacts)
        if not self._missing_calls:
            self.missing_row.pack_forget()
            return
        shown = ", ".join(self._missing_calls[:6])
        if len(self._missing_calls) > 6:
            shown += "…"
        self.missing_var.set(t(
            "{count} contact(s) are missing a name or an address: {calls}",
            count=len(self._missing_calls), calls=shown))
        self.missing_row.pack(fill="x", padx=8, pady=(0, 6))

    def on_fix_contacts(self) -> None:
        """Open the address book, ready to add the callsigns that are lacking."""
        if not self.config_path:
            self.on_settings()
            if not self.config_path:
                return
        SettingsDialog(self.root, self, open_tab="contacts",
                       prefill=list(getattr(self, "_missing_calls", [])))

    def on_review(self):
        outdir = Path(self.outdir.get().strip() or ".")
        manifest = outdir / "manifest.csv"
        if not manifest.is_file():
            messagebox.showinfo(t(APP_TITLE), t("Make the cards first."))
            return
        _open_file(manifest)
        self.log(t("Opened {path} — check the addresses before sending.",
                   path=manifest))

    def on_send_test(self):
        addr = _ask_string(self.root, t("Send a test"),
                           t("Send one test card to which address?"))
        if not addr:
            return

        def work():
            self._deliver(to_override=addr, limit=1, confirm=True)
            self.log(t("Test sent. Nobody was marked as having received a card."))

        self._run(work)

    def on_send(self):
        outdir = Path(self.outdir.get().strip() or ".")

        def work_preview():
            count = self._deliver(to_override="", limit=None, confirm=False)
            if not count:
                return
            self.root.after(0, lambda: self._confirm_and_send(count, outdir))

        self._run(work_preview)

    def _confirm_and_send(self, count: int, outdir: Path) -> None:
        ok = messagebox.askyesno(
            t("Send the e-mails"),
            f"This will e-mail {count} operator(s) — for real.\n\n"
            "Anyone who already received their card will be skipped.\n\n"
            "Send now?",
            default="no", icon="warning")
        if not ok:
            self.log(t("Cancelled — nothing was sent."))
            return
        self._run(lambda: self._deliver("", None, confirm=True))

    def _check_credentials(self, cfg) -> bool:
        """Warn before contacting the server, rather than after it refuses.

        A missing password produces "530 Authentication Required", which says
        nothing about what to fix or where.
        """
        missing = None
        if not cfg.smtp.from_address.strip():
            missing = t("your own e-mail address")
        elif cfg.smtp.username.strip() and not cfg.smtp.password.strip():
            missing = t("your password")
        elif cfg.smtp.username.strip().startswith(("myemail@", "your", "user@")):
            missing = t("your own sign-in address")

        if missing is None:
            return True

        if messagebox.askyesno(
            t("E-mail settings"),
            t("Before sending, {missing} is needed in Settings.\n\n"
              "Open Settings now?", missing=missing),
            default="yes",
        ):
            self.on_settings()
        return False

    def _deliver(self, to_override: str, limit, confirm: bool) -> int:
        from qsl_send.mailer import SentLog, deliver
        from qsl_send.sending import build_queue, format_preview

        outdir = Path(self.outdir.get().strip() or ".")
        cfg = load_config(self.config_path)
        if confirm and not self._check_credentials(cfg):
            return 0
        sent_log = SentLog(outdir / "sent.json")
        q = build_queue(cfg, outdir, to_override=to_override, limit=limit,
                        sent_log=sent_log)
        self.log(format_preview(cfg, q, outdir))
        if not q.items:
            self.log(t("Nobody left to send to."))
            return 0
        if not confirm:
            return len(q.items)

        self.status.set(t("Sending {count} e-mail(s)…", count=len(q.items)))
        outcomes = deliver(
            cfg.smtp, q.items,
            attachment_template=cfg.smtp.attachment_name,
            sent_log=None if q.is_test else sent_log,
            delay=cfg.smtp.delay, progress=self.log)
        sent = sum(1 for o in outcomes if o.status == "sent")
        self.log("\n" + t("Sent {sent} of {total}.",
                          sent=sent, total=len(outcomes)))
        self.status.set(t("Sent {sent} of {total}.",
                          sent=sent, total=len(outcomes)))
        return sent


class SettingsDialog(tk.Toplevel):
    """Edit the settings a non-technical user legitimately needs to change.

    Deliberately excludes field boxes, fonts and colours: `detect-fields`
    already handles the card layout, and a wrong number there silently ruins
    every card in a batch.
    """

    def __init__(self, parent: tk.Misc, app: "App", *,
                 open_tab: str | None = None,
                 prefill: list[str] | None = None):
        super().__init__(parent)
        self.app = app
        self._prefill = list(prefill or [])
        self.title(t("Settings"))
        self.transient(parent)
        self.resizable(False, False)

        cfg = load_config(app.config_path)
        self.cfg = cfg
        self.vars: dict[str, tk.Variable] = {}

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        nb.add(self._tab_identity(nb), text=t("You"))
        nb.add(self._tab_email(nb), text=t("E-mail"))
        nb.add(self._tab_message(nb), text=t("Message"))
        contacts_tab = self._tab_contacts(nb)
        nb.add(contacts_tab, text=t("Address book"))
        if open_tab == "contacts":
            nb.select(contacts_tab)
            self.after(120, self._offer_prefill)
        nb.add(self._tab_behaviour(nb), text=t("Behaviour"))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(buttons, text=t("Cancel"), command=self.destroy).pack(side="right")
        ttk.Button(buttons, text=t("Save"), command=self.on_save).pack(
            side="right", padx=6)

        # Make the dialog modal only once it is actually on screen.
        #
        # wait_visibility() blocks until the window is mapped, and a transient
        # child of a hidden or minimised parent may never map — which would
        # hang the app with no error message. grab_set() has the same problem
        # if called before mapping. Deferring both to <Map> keeps the dialog
        # usable no matter what state the main window is in.
        self.bind("<Map>", self._on_mapped)
        self.focus_set()

    def _on_mapped(self, _event=None) -> None:
        self.unbind("<Map>")
        center_window(self, self.master)
        try:
            self.grab_set()
        except tk.TclError:
            pass  # a grab is a nicety, never worth failing over
        self.focus_set()

    # -- tabs ----------------------------------------------------------

    def _row(self, parent, label, key, value, *, width=34, show=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Label(row, text=label, width=18).pack(side="left")
        var = tk.StringVar(value="" if value is None else str(value))
        self.vars[key] = var
        entry = ttk.Entry(row, textvariable=var, width=width, show=show)
        entry.pack(side="left", fill="x", expand=True)
        return row, entry

    def _tab_identity(self, nb):
        f = ttk.Frame(nb)
        self._row(f, t("Your callsign"), "my_callsign", self.cfg.my_callsign)

        row = ttk.Frame(f)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Label(row, text=t("Language"), width=18).pack(side="left")
        lang = tk.StringVar(value=self.cfg.language or "auto")
        self.vars["language"] = lang
        ttk.Combobox(row, textvariable=lang, width=20, state="readonly",
                     values=["auto", *SUPPORTED]).pack(side="left")
        ttk.Label(f, text=t("'auto' follows the computer's own language."),
                  foreground="#666").pack(anchor="w", padx=10)
        return f

    def _tab_email(self, nb):
        f = ttk.Frame(nb)
        self._row(f, t("Server"), "smtp.host", self.cfg.smtp.host)
        self._row(f, t("Port"), "smtp.port", self.cfg.smtp.port, width=10)
        self._row(f, t("Your name"), "smtp.from_name", self.cfg.smtp.from_name)
        self._row(f, t("Your address"), "smtp.from_address",
                  self.cfg.smtp.from_address)
        self._row(f, t("Sign in as"), "smtp.username", self.cfg.smtp.username)

        # Password: masked by default, revealed by the checkbox.
        row, entry = self._row(f, t("Password"), "smtp.password",
                               self.cfg.smtp.password, show="\u2022")
        self._pw_entry = entry
        self._pw_shown = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text=t("Show"), variable=self._pw_shown,
                        command=self._toggle_password).pack(side="left", padx=6)
        ttk.Label(
            f,
            text=t("For Gmail this is a 16-character App Password, "
                   "not your normal password."),
            foreground="#666", wraplength=430, justify="left",
        ).pack(anchor="w", padx=10, pady=(2, 6))
        return f

    def _toggle_password(self) -> None:
        self._pw_entry.configure(show="" if self._pw_shown.get() else "\u2022")

    def _tab_message(self, nb):
        """Subject and body of the e-mail, with a live preview."""
        f = ttk.Frame(nb)
        self._row(f, t("Subject"), "smtp.subject", self.cfg.smtp.subject, width=44)

        ttk.Label(f, text=t("Message text")).pack(anchor="w", padx=10, pady=(8, 2))
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True, padx=10)
        self.body_text = tk.Text(wrap, height=10, width=58, wrap="word")
        body_scroll = ttk.Scrollbar(wrap, command=self.body_text.yview)
        self.body_text.configure(yscrollcommand=body_scroll.set)
        self.body_text.pack(side="left", fill="both", expand=True)
        body_scroll.pack(side="right", fill="y")

        # Read the block from the file: cfg.smtp.body is the same text, but
        # reading it back keeps this tab honest about what is actually stored.
        stored = None
        if self.app.config_path:
            try:
                stored = read_block_scalar(self.app.config_path, "smtp.body")
            except Exception:
                stored = None
        self.body_text.insert("1.0", stored if stored is not None else self.cfg.smtp.body)

        ttk.Label(
            f,
            text=t("You can use: {placeholders}"
                   ).replace("{placeholders}",
                             "{name_first} {callsign} {date} {utc} {qrg} "
                             "{mode} {rst} {my_callsign}"),
            foreground="#666", wraplength=430, justify="left",
        ).pack(anchor="w", padx=10, pady=(4, 0))

        ttk.Button(f, text=t("Preview…"), command=self._preview_message).pack(
            anchor="w", padx=10, pady=6)
        return f

    def _preview_message(self) -> None:
        """Fill the subject and body with a real QSO, so wording can be checked."""
        subject = self.vars["smtp.subject"].get()
        body = self.body_text.get("1.0", "end").rstrip("\n")

        values = None
        adif = self.app.adif.get().strip()
        if adif and Path(adif).is_file():
            try:
                from qsl_send.adif import read_adif
                from qsl_send.fields import placeholders

                qsos = read_adif(Path(adif))
                if qsos:
                    values = placeholders(
                        qsos[0],
                        date_format=self.cfg.date_format,
                        time_format=self.cfg.time_format,
                        qrg_decimals=self.cfg.qrg_decimals,
                        my_callsign=self.vars["my_callsign"].get()
                        or self.cfg.my_callsign,
                    )
            except Exception:
                values = None
        if values is None:
            values = {
                "name_first": "Ana", "callsign": "AA1AA", "date": "13/09/2026",
                "utc": "17:49", "qrg": "7.133", "mode": "SSB", "rst": "59",
                "my_callsign": self.cfg.my_callsign or "MY1CLL",
            }

        from qsl_send.fields import format_template

        win = tk.Toplevel(self)
        win.title(t("Preview"))
        win.transient(self)
        win.bind("<Map>", lambda _e: (win.unbind("<Map>"), center_window(win, self)))
        box = ttk.Frame(win)
        box.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(box, text=t("Subject") + ": " + format_template(subject, values),
                  font=("", 0, "bold"), wraplength=460,
                  justify="left").pack(anchor="w", pady=(0, 8))
        preview = tk.Text(box, height=12, width=58, wrap="word")
        preview.insert("1.0", format_template(body, values))
        preview.configure(state="disabled")
        preview.pack(fill="both", expand=True)
        ttk.Button(box, text=t("Close"), command=win.destroy).pack(anchor="e", pady=(8, 0))

    def _tab_contacts(self, nb):
        """Edit contacts.yaml: addresses and names the log and QRZ do not have."""
        f = ttk.Frame(nb)
        ttk.Label(
            f,
            text=t("Addresses and names you looked up yourself. These win over "
                   "the log and QRZ."),
            foreground="#666", wraplength=440, justify="left",
        ).pack(anchor="w", padx=10, pady=(8, 4))

        cols = ("callsign", "email", "name")
        self.contacts_tree = ttk.Treeview(
            f, columns=cols, show="headings", height=8, selectmode="browse")
        for col, title, width in (
            ("callsign", t("Callsign"), 90),
            ("email", t("E-mail"), 210),
            ("name", t("Name"), 130),
        ):
            self.contacts_tree.heading(col, text=title)
            self.contacts_tree.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(f, command=self.contacts_tree.yview)
        self.contacts_tree.configure(yscrollcommand=scroll.set)
        self.contacts_tree.pack(side="top", fill="both", expand=True, padx=(10, 0))
        self.contacts_tree.bind("<Double-1>", lambda _e: self._edit_contact())

        self._contacts: dict[str, Contact] = {}
        self._contacts_path = None
        self._load_contacts_into_tree()

        row = ttk.Frame(f)
        row.pack(fill="x", padx=10, pady=6)
        ttk.Button(row, text=t("Add…"), command=self._add_contact).pack(side="left")
        ttk.Button(row, text=t("Edit…"), command=self._edit_contact).pack(
            side="left", padx=6)
        ttk.Button(row, text=t("Remove"), command=self._remove_contact).pack(side="left")
        return f

    def _offer_prefill(self) -> None:
        """Walk the user through the callsigns the analysis flagged."""
        pending = [c for c in self._prefill if c not in self._contacts]
        if not pending:
            return
        if not messagebox.askyesno(
            t("Address book"),
            t("Add the {count} missing contact(s) now?", count=len(pending)),
            default="yes",
        ):
            return
        for call in pending:
            self._add_contact(prefill=call)

    def _load_contacts_into_tree(self) -> None:
        # Fall back to contacts.yaml beside the settings file. Leaving this as
        # None when the config does not name one meant the save was skipped in
        # silence: edits looked accepted and were simply thrown away.
        if self.cfg.contacts_file:
            path = self.cfg.resolve(self.cfg.contacts_file)
        elif self.app.config_path is not None:
            path = Path(self.app.config_path).parent / "contacts.yaml"
        else:
            path = None
        self._contacts_path = path
        self._contacts = {}
        if path and Path(path).is_file():
            try:
                self._contacts, warns = load_contacts(path)
                for w in warns:
                    self.app.log(f"! {w}")
            except ContactsError as exc:
                self.app.log(str(exc))
        self._refresh_contacts_tree()

    def _refresh_contacts_tree(self) -> None:
        self.contacts_tree.delete(*self.contacts_tree.get_children())
        for call in sorted(self._contacts):
            entry = self._contacts[call]
            self.contacts_tree.insert(
                "", "end", iid=call, values=(call, entry.email, entry.name))

    def _contact_form(self, call="", email="", name=""):
        """Ask for one entry. Returns a Contact, or None if cancelled."""
        win = tk.Toplevel(self)
        win.title(t("Contact"))
        win.transient(self)
        win.resizable(False, False)
        vars_ = {}
        for label, key, value in (
            (t("Callsign"), "callsign", call),
            (t("E-mail"), "email", email),
            (t("Name"), "name", name),
        ):
            r = ttk.Frame(win)
            r.pack(fill="x", padx=12, pady=5)
            ttk.Label(r, text=label, width=12).pack(side="left")
            v = tk.StringVar(value=value)
            vars_[key] = v
            entry = ttk.Entry(r, textvariable=v, width=32)
            entry.pack(side="left")
            if key == "callsign" and call:
                entry.configure(state="disabled")  # the callsign is the key

        result: dict[str, Contact | None] = {"value": None}

        def ok():
            from qsl_send.qrz import valid_email
            from qsl_send.adif import base_callsign

            cs = base_callsign(vars_["callsign"].get().strip())
            em = vars_["email"].get().strip()
            nm = vars_["name"].get().strip()
            if not cs:
                messagebox.showwarning(t("Contact"), t("Enter a callsign."))
                return
            if em and not valid_email(em):
                messagebox.showwarning(
                    t("Contact"), t("That does not look like an e-mail address."))
                return
            if not em and not nm:
                messagebox.showwarning(
                    t("Contact"), t("Enter an e-mail address, a name, or both."))
                return
            result["value"] = Contact(callsign=cs, email=em, name=nm)
            win.destroy()

        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(buttons, text=t("Cancel"), command=win.destroy).pack(side="right")
        ttk.Button(buttons, text=t("OK"), command=ok).pack(side="right", padx=6)
        win.bind("<Map>", lambda _e: (win.unbind("<Map>"), win.grab_set(),
                                      center_window(win, self)))
        self.wait_window(win)
        return result["value"]

    def _add_contact(self, prefill: str = "") -> None:
        entry = self._contact_form(call=prefill)
        if entry:
            self._contacts[entry.callsign] = entry
            self._refresh_contacts_tree()
            self.contacts_tree.selection_set(entry.callsign)
            self.contacts_tree.see(entry.callsign)

    def _edit_contact(self) -> None:
        sel = self.contacts_tree.selection()
        if not sel:
            return
        call = sel[0]
        current = self._contacts[call]
        entry = self._contact_form(call, current.email, current.name)
        if entry:
            self._contacts[call] = entry
            self._refresh_contacts_tree()

    def _remove_contact(self) -> None:
        sel = self.contacts_tree.selection()
        if not sel:
            return
        call = sel[0]
        if messagebox.askyesno(
            t("Address book"),
            t("Remove {callsign} from the address book?", callsign=call),
            default="no",
        ):
            self._contacts.pop(call, None)
            self._refresh_contacts_tree()

    def _tab_behaviour(self, nb):
        f = ttk.Frame(nb)
        self._row(f, t("Save cards to"), "output_dir", self.cfg.output_dir)
        self._row(f, t("Address book"), "contacts_file", self.cfg.contacts_file)
        self._row(f, t("Pause between e-mails"), "smtp.delay",
                  self.cfg.smtp.delay, width=10)

        skip = tk.BooleanVar(value=self.cfg.skip_without_email)
        self.vars["skip_without_email"] = skip
        ttk.Checkbutton(
            f, text=t("Skip contacts with no e-mail address"), variable=skip,
        ).pack(anchor="w", padx=10, pady=6)
        return f

    # -- saving --------------------------------------------------------

    def on_save(self) -> None:
        changes: dict[str, object] = {}
        for key, var in self.vars.items():
            value = var.get()
            if key == "language":
                value = "" if value == "auto" else value
            elif key == "smtp.port":
                try:
                    value = int(str(value).strip())
                except ValueError:
                    messagebox.showwarning(
                        t("Settings"), t("The port must be a whole number."))
                    return
            elif key == "smtp.delay":
                try:
                    value = float(str(value).strip())
                except ValueError:
                    messagebox.showwarning(
                        t("Settings"),
                        t("The pause must be a number of seconds."))
                    return
            changes[key] = value

        # Never let an empty password box wipe a stored password. The box can
        # legitimately come up empty — for instance when the config points at
        # ${SMTP_PASSWORD} and no .env is present — and saving then would
        # silently destroy a working setup.
        allow_pw = True
        if not str(changes.get("smtp.password", "")).strip():
            changes.pop("smtp.password", None)
            allow_pw = False

        # The Files section is edited on the main window, not in this dialog,
        # so its values must be carried into the same save. Otherwise they are
        # lost when the application closes — and, worse, overwritten by the
        # reload at the end of this method.
        for key, var in (
            ("template", self.app.template),
            ("adif", self.app.adif),
            ("output_dir", self.app.outdir),
        ):
            chosen = var.get().strip()
            if chosen:
                changes[key] = chosen

        # Record the address book path when it came from the fallback, so the
        # next run finds it through the configuration rather than by guessing.
        if getattr(self, "_contacts_path", None) and not self.cfg.contacts_file:
            changes["contacts_file"] = "contacts.yaml"

        # Fields this window offers to edit must actually save. They ship as
        # ${VAR} placeholders in the example config, and the guard that
        # protects placeholders was silently discarding the write — the window
        # said it saved and then forgot the value.
        replaceable = {"smtp.username", "smtp.from_address", "smtp.from_name"}
        if allow_pw:
            replaceable.add("smtp.password")

        try:
            written = update_settings(
                self.app.config_path,
                changes,
                # Only the keys this window edits. Any other ${VAR} in the file
                # stays exactly as written.
                allow_replacing_placeholders=replaceable,
            )
        except SettingsWriteError as exc:
            messagebox.showerror(t("Settings"), str(exc))
            return

        # The body is a multi-line block, so it is written separately; a
        # normal line replacement would orphan its text and corrupt the file.
        try:
            body = self.body_text.get("1.0", "end").rstrip("\n")
            if update_block_scalar(self.app.config_path, "smtp.body", body):
                written = list(written) + ["smtp.body"]
        except SettingsWriteError as exc:
            messagebox.showerror(t("Settings"), str(exc))
            return

        # The address book lives in its own file, so it saves separately.
        if getattr(self, "_contacts_path", None):
            try:
                save_contacts(self._contacts_path, self._contacts)
            except ContactsError as exc:
                messagebox.showerror(t("Address book"), str(exc))
                return

        if "language" in written:
            set_language(changes["language"] or None)  # type: ignore[arg-type]
            messagebox.showinfo(
                t("Settings"),
                t("The new language will be used next time you open the window."))

        self.app.log(t("Saved {count} setting(s).", count=len(written)))
        self.app._load_config_defaults(keep_files=True)
        self.destroy()


def center_window(window: tk.Misc, parent: tk.Misc | None = None) -> None:
    """Place `window` in the middle of its parent, or of the screen.

    Tk otherwise puts every window at the top-left corner, which looks broken
    on a wide screen and hides dialogs behind the main window.
    """
    window.update_idletasks()
    width = window.winfo_width() or window.winfo_reqwidth()
    height = window.winfo_height() or window.winfo_reqheight()

    if parent is not None and parent.winfo_viewable() and parent.winfo_width() > 1:
        base_x = parent.winfo_rootx()
        base_y = parent.winfo_rooty()
        base_w = parent.winfo_width()
        base_h = parent.winfo_height()
    else:
        base_x = base_y = 0
        base_w = window.winfo_screenwidth()
        base_h = window.winfo_screenheight()

    x = base_x + (base_w - width) // 2
    y = base_y + (base_h - height) // 3      # slightly above centre reads better

    # Never place it off-screen, which can happen on a multi-monitor setup.
    x = max(0, min(x, window.winfo_screenwidth() - width))
    y = max(0, min(y, window.winfo_screenheight() - height))
    window.geometry(f"+{x}+{y}")


def _ask_string(parent, title, prompt) -> str:
    from tkinter import simpledialog
    return simpledialog.askstring(title, prompt, parent=parent) or ""


def _open_file(path: Path) -> None:
    """Open a file with whatever the desktop uses. Best effort only."""
    import subprocess
    try:
        if sys.platform.startswith("win"):
            import os
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # An installed application is launched from the Start menu, so the working
    # directory is not where it lives. resolve_config() falls back to a
    # per-user file, creating it on first run, so the window always has real
    # settings to show and Settings… always has something to edit.
    config_path = resolve_config(argv[0] if argv else None)
    # Language comes from the config if it names one, otherwise from the OS.
    language = None
    if config_path and Path(config_path).is_file():
        try:
            language = load_config(Path(config_path)).language or None
        except ConfigError:
            language = None
    set_language(language)

    root = tk.Tk()
    App(root, config_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
