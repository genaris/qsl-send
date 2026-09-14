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
from qsl_send.contacts import ContactsError, load_contacts

APP_TITLE = "QSL Sender"


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

        root.title(APP_TITLE)
        root.geometry("760x620")
        root.minsize(680, 560)

        self.template = tk.StringVar()
        self.adif = tk.StringVar()
        self.outdir = tk.StringVar()
        self.status = tk.StringVar(value="Choose a card design and a log file.")

        self._build()
        self._load_config_defaults()
        self._tick()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True)

        # --- inputs ---
        box = ttk.LabelFrame(frm, text="1. Files")
        box.pack(fill="x", **pad)
        self._file_row(box, "Card design", self.template, self._pick_template,
                       [("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        self._file_row(box, "Log file (ADIF)", self.adif, self._pick_adif,
                       [("ADIF logs", "*.adi *.adif"), ("All files", "*.*")])
        self._file_row(box, "Save cards to", self.outdir, self._pick_outdir, None)

        # --- fields ---
        box2 = ttk.LabelFrame(frm, text="2. Card layout")
        box2.pack(fill="x", **pad)
        row = ttk.Frame(box2)
        row.pack(fill="x", padx=8, pady=6)
        self.fields_label = ttk.Label(row, text="Fields not checked yet.")
        self.fields_label.pack(side="left")
        ttk.Button(row, text="Find fields automatically",
                   command=self.on_detect).pack(side="right", padx=4)
        ttk.Button(row, text="Show me…", command=self.on_preview_fields).pack(
            side="right", padx=4)

        # --- actions ---
        box3 = ttk.LabelFrame(frm, text="3. Make and send the cards")
        box3.pack(fill="x", **pad)
        row2 = ttk.Frame(box3)
        row2.pack(fill="x", padx=8, pady=6)
        self.btn_generate = ttk.Button(row2, text="Make the cards",
                                       command=self.on_generate)
        self.btn_generate.pack(side="left")
        self.btn_review = ttk.Button(row2, text="Review who gets one…",
                                     command=self.on_review, state="disabled")
        self.btn_review.pack(side="left", padx=6)
        self.btn_test = ttk.Button(row2, text="Send a test to myself",
                                   command=self.on_send_test, state="disabled")
        self.btn_test.pack(side="left", padx=6)
        self.btn_send = ttk.Button(row2, text="Send the e-mails",
                                   command=self.on_send, state="disabled")
        self.btn_send.pack(side="right")

        # --- log ---
        box4 = ttk.LabelFrame(frm, text="What happened")
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
        ttk.Button(row, text="Choose…", command=command).pack(side="left", padx=6)

    # ------------------------------------------------------------ behaviour

    def _load_config_defaults(self) -> None:
        try:
            cfg = load_config(self.config_path)
        except ConfigError as exc:
            self.log(f"Could not read the settings file: {exc}")
            return
        self.cfg = cfg
        if cfg.template:
            t = cfg.resolve(cfg.template)
            if t:
                self.template.set(str(t))
        if cfg.adif:
            a = cfg.resolve(cfg.adif)
            if a:
                self.adif.set(str(a))
        out = cfg.resolve(cfg.output_dir)
        if out:
            self.outdir.set(str(out))
        if cfg.render.fields:
            self.fields_label.configure(
                text=f"{len(cfg.render.fields)} fields configured.")

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
            messagebox.showinfo(APP_TITLE, "Still working — please wait.")
            return

        def wrapped():
            try:
                fn()
            except Exception as exc:  # surface, never crash the window
                self.log(f"\nSomething went wrong: {exc}")
                self.log(traceback.format_exc())
                self.status.set("Something went wrong — see the log below.")
            finally:
                self.root.after(0, lambda: self._busy(False))

        self._busy(True)
        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()

    # --------------------------------------------------------------- pickers

    def _pick_template(self):
        p = filedialog.askopenfilename(
            title="Choose your QSL card design",
            filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        if p:
            self.template.set(p)

    def _pick_adif(self):
        p = filedialog.askopenfilename(
            title="Choose your log file",
            filetypes=[("ADIF logs", "*.adi *.adif"), ("All files", "*.*")])
        if p:
            self.adif.set(p)

    def _pick_outdir(self):
        p = filedialog.askdirectory(title="Where should the cards be saved?")
        if p:
            self.outdir.set(p)

    # --------------------------------------------------------------- actions

    def on_detect(self):
        template = self.template.get().strip()
        if not template:
            messagebox.showwarning(APP_TITLE, "Choose a card design first.")
            return

        def work():
            from qsl_send.detect import detect_boxes, name_boxes
            self.status.set("Looking for the fields on the card…")
            self.log(f"Looking at {Path(template).name} …")
            d = detect_boxes(template)
            if not d.boxes:
                self.log("No fields found. The boxes may not be a flat colour.")
                self.status.set("No fields found.")
                return
            named = name_boxes(d)
            self.log(f"Found {len(d.boxes)} fields in {d.rows} row(s):")
            for b, n, _v in named:
                self.log(f"    {n:<9} at {b.box}")
            self.log("Names are guessed from left-to-right order — "
                     "use 'Show me…' to check them on the card.")
            self.detected = (d, named)
            self.root.after(0, lambda: self.fields_label.configure(
                text=f"{len(d.boxes)} fields found automatically."))
            self.status.set(f"Found {len(d.boxes)} fields.")

        self._run(work)

    def on_preview_fields(self):
        template = self.template.get().strip()
        if not template:
            messagebox.showwarning(APP_TITLE, "Choose a card design first.")
            return

        def work():
            from qsl_send.detect import detect_boxes, name_boxes
            from PIL import Image, ImageDraw
            d = detect_boxes(template)
            if not d.boxes:
                self.log("Nothing to show — no fields were found.")
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
            self.log(f"Saved a marked-up copy to {out}")
            _open_file(out)

        self._run(work)

    def on_generate(self):
        adif = self.adif.get().strip()
        template = self.template.get().strip()
        outdir = self.outdir.get().strip()
        if not (adif and template and outdir):
            messagebox.showwarning(
                APP_TITLE, "Choose a card design, a log file and a folder first.")
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
                        self.log(f"! Address book problem: {exc}")

            self.status.set("Making the cards…")
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
            self.status.set(
                f"{summary.cards_written} cards made · "
                f"{summary.with_email} ready to e-mail · "
                f"{summary.without_email} with no address")

        self._run(work)

    def on_review(self):
        outdir = Path(self.outdir.get().strip() or ".")
        manifest = outdir / "manifest.csv"
        if not manifest.is_file():
            messagebox.showinfo(APP_TITLE, "Make the cards first.")
            return
        _open_file(manifest)
        self.log(f"Opened {manifest} — check the addresses before sending.")

    def on_send_test(self):
        addr = _ask_string(self.root, "Send a test",
                           "Send one test card to which address?")
        if not addr:
            return

        def work():
            self._deliver(to_override=addr, limit=1, confirm=True)
            self.log("Test sent. Nobody was marked as having received a card.")

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
            "Send the e-mails",
            f"This will e-mail {count} operator(s) — for real.\n\n"
            "Anyone who already received their card will be skipped.\n\n"
            "Send now?",
            default="no", icon="warning")
        if not ok:
            self.log("Cancelled — nothing was sent.")
            return
        self._run(lambda: self._deliver("", None, confirm=True))

    def _deliver(self, to_override: str, limit, confirm: bool) -> int:
        from qsl_send.mailer import SentLog, deliver
        from qsl_send.sending import build_queue, format_preview

        outdir = Path(self.outdir.get().strip() or ".")
        cfg = load_config(self.config_path)
        sent_log = SentLog(outdir / "sent.json")
        q = build_queue(cfg, outdir, to_override=to_override, limit=limit,
                        sent_log=sent_log)
        self.log(format_preview(cfg, q, outdir))
        if not q.items:
            self.log("Nobody left to send to.")
            return 0
        if not confirm:
            return len(q.items)

        self.status.set(f"Sending {len(q.items)} e-mail(s)…")
        outcomes = deliver(
            cfg.smtp, q.items,
            attachment_template=cfg.smtp.attachment_name,
            sent_log=None if q.is_test else sent_log,
            delay=cfg.smtp.delay, progress=self.log)
        sent = sum(1 for o in outcomes if o.status == "sent")
        self.log(f"\nSent {sent} of {len(outcomes)}.")
        self.status.set(f"Sent {sent} of {len(outcomes)}.")
        return sent


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
    config_path = Path(argv[0]) if argv else None
    if config_path is None:
        for name in ("qsl-send.yaml", "qsl-send.yml"):
            p = Path.cwd() / name
            if p.is_file():
                config_path = p
                break
    root = tk.Tk()
    App(root, config_path)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
