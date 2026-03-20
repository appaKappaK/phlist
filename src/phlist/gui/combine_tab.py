"""Combine tab and Save-to-Library dialog.

Note: updater.update_list() has a similar fetch→combine pipeline used for
re-fetching saved library lists.  This module adds session-scoped caching and
credit extraction on top, so the two pipelines are kept separate intentionally.
"""

import json
import logging
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

import customtkinter as ctk

from ..combiner import ListCombiner
from ..database import Database
from ..fetcher import ListFetcher
from ..remote import push_list as _push_list
from .ctk_helpers import (
    get_canvas, get_inner_window_id, get_label_inner, get_scrollbar, get_underlying_textbox,
)
from .tooltip import Tooltip

_log = logging.getLogger(__name__)

# ── UI colors (easy to tweak) ────────────────────────────────────────
_CLR_BTN_DEFAULT       = ["#3B8ED0", "#1F6AA5"]
_CLR_BTN_DEFAULT_HOVER = ["#36719F", "#144870"]
_CLR_BTN_DANGER        = ["#C0392B", "#922B21"]
_CLR_BTN_DANGER_HOVER  = ["#A93226", "#7B241C"]
_CLR_BTN_SUCCESS       = ["#27AE60", "#1E8449"]
_CLR_BTN_SUCCESS_HOVER = ["#219A52", "#196F3D"]

# Matches any http/https URL in arbitrary text (e.g. Pi-hole dashboard paste).
# Excludes backtick, pipe, and angle-bracket characters that appear in markdown
# table formatting but are never valid unencoded URL characters.
_URL_RE = re.compile(r'https?://[^\s`|<>"\']+')

# Max lines rendered in the output preview; full content is preserved in _last_result.
_DISPLAY_LIMIT = 100

# Max source rows rendered in the sources panel; prevents X11 resource exhaustion
# when loading a combined result built from many URL sources.
_SOURCES_DISPLAY_LIMIT = 30

# Extracts the username/author from common code-hosting URL patterns
_FORGE_USER_RE = re.compile(
    r'https?://(?:'
    r'(?:raw\.githubusercontent|github)\.com/([^/]+)/'   # github.com / raw
    r'|cdn\.jsdelivr\.net/gh/([^/]+)/'                   # jsDelivr GitHub CDN
    r'|([^./]+)\.(?:github|gitlab)\.io/'                  # username.github.io / username.gitlab.io
    r'|gitlab\.com/([^/]+)/'                             # gitlab.com
    r'|bitbucket\.org/([^/]+)/'                          # bitbucket.org
    r'|codeberg\.org/([^/]+)/'                           # codeberg.org
    r'|([^./]+)\.codeberg\.page/'                        # username.codeberg.page
    r')'
)

# Characters/words that are noise when extracting credit text from a pasted table row
_NOISE_RE = re.compile(r'[✓✗☑☐✔✘]|\b(enabled|disabled|true|false|yes|no|url|link|http|https|address|list|name|id)\b', re.I)


def _credit_for_url(url: str, line: str) -> Optional[str]:
    """Return a credit name for *url* by examining *line* or the URL itself."""
    # 1. Strip the URL and table/markdown noise from the line
    remaining = _URL_RE.sub('', line)
    remaining = _NOISE_RE.sub(' ', remaining)
    remaining = re.sub(r'[`*_]', '', remaining)          # strip markdown formatting chars
    remaining = re.sub(r'\s+', ' ', remaining).strip(' \t|,;:')
    remaining = re.sub(r'^\d+\s*|\s*\d+$', '', remaining).strip()  # leading/trailing IDs
    # Accept line text only if it looks like a name/tag (≤ 5 words) rather
    # than a description sentence from a markdown table or comment block.
    # Count actual word tokens (split on spaces AND hyphens) so hyphenated
    # descriptors like "low-malware-false-positive" don't sneak past the limit.
    if remaining and len(re.findall(r'\b\w+\b', remaining)) <= 5:
        return remaining
    # 2. Fall back to username extracted from known code-hosting URL patterns
    m = _FORGE_USER_RE.search(url)
    if m:
        return next(g for g in m.groups() if g is not None)
    return None


class _ConfirmRemoveDialog(ctk.CTkToplevel):
    """Ask once before removing a source; optional 'don't ask again' checkbox."""

    def __init__(self, parent, label: str) -> None:
        super().__init__(parent)
        self.transient(parent)
        self.title("Remove Source")
        self.geometry("360x180")
        self.resizable(False, False)

        self.confirmed = False
        self.dont_ask_again = False

        short = label if len(label) <= 52 else label[:49] + "…"
        ctk.CTkLabel(self, text="Remove this source?",
                     font=ctk.CTkFont(weight="bold")).pack(pady=(18, 4), padx=20)
        ctk.CTkLabel(self, text=short, text_color="gray60",
                     wraplength=320, anchor="w").pack(padx=20, pady=(0, 10))

        self._dna_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Don't ask again",
                        variable=self._dna_var).pack(padx=24, anchor="w", pady=(0, 14))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        ctk.CTkButton(btn_row, text="Remove", fg_color=_CLR_BTN_DANGER,
                      command=self._on_remove).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(btn_row, text="Cancel",
                      command=self.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.update_idletasks()
        self.lift()
        self.focus_force()
        self.grab_set()

    def _on_remove(self) -> None:
        self.confirmed = True
        self.dont_ask_again = self._dna_var.get()
        self.destroy()


class _ConfirmCombineDialog(ctk.CTkToplevel):
    """First-time confirmation before combining; optional 'don't ask again' checkbox."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.transient(parent)
        self.title("Combine All")
        self.geometry("360x175")
        self.resizable(False, False)

        self.confirmed = False
        self.dont_ask_again = False

        ctk.CTkLabel(self, text="Combine all sources?",
                     font=ctk.CTkFont(weight="bold")).pack(pady=(18, 6), padx=20)
        ctk.CTkLabel(self, text="This may take a while if sources need to be fetched.",
                     text_color="gray60", wraplength=320).pack(padx=20)

        self._dna_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Don't ask again",
                        variable=self._dna_var).pack(padx=24, anchor="w", pady=(12, 10))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        ctk.CTkButton(btn_row, text="Combine",
                      command=self._on_combine).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(btn_row, text="Cancel",
                      command=self.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.update_idletasks()
        self.lift()
        self.focus_force()
        self.grab_set()

    def _on_combine(self) -> None:
        self.confirmed = True
        self.dont_ask_again = self._dna_var.get()
        self.destroy()


class SaveToLibraryDialog(ctk.CTkToplevel):
    """Modal dialog: enter a name and choose a folder before saving to the library."""

    def __init__(self, parent, db: Database) -> None:
        super().__init__(parent)
        self.transient(parent)
        self.title("Save to Library")
        self.geometry("360x200")
        self.resizable(False, False)

        self._db = db
        self.result_name: Optional[str] = None
        self.result_folder_id: Optional[int] = None

        ctk.CTkLabel(self, text="List name:").pack(padx=20, pady=(20, 4), anchor="w")
        self._name_entry = ctk.CTkEntry(self, width=320)
        self._name_entry.pack(padx=20)

        ctk.CTkLabel(self, text="Folder:").pack(padx=20, pady=(12, 4), anchor="w")
        self._folder_map: dict = {}
        self._folder_var = ctk.StringVar(value="🏠 Home")
        self._folder_menu = ctk.CTkOptionMenu(
            self, variable=self._folder_var, values=["🏠 Home"],
            width=320, command=self._on_folder_change,
        )
        self._folder_menu.pack(padx=20)
        self._refresh_folder_menu()

        ctk.CTkButton(self, text="Save", command=self._on_save, width=320).pack(
            padx=20, pady=16
        )

        # Flush draw queue before grabbing events — prevents black window on Linux
        self.update_idletasks()
        self.lift()
        self.focus_force()
        self.grab_set()

    def _refresh_folder_menu(self, select: Optional[str] = None) -> None:
        folders = self._db.get_folders()
        self._folder_map = {f["name"]: f["id"] for f in folders}
        options = ["🏠 Home"] + list(self._folder_map.keys()) + ["+ New Folder"]
        self._folder_menu.configure(values=options)
        if select and select in self._folder_map:
            self._folder_var.set(select)

    def _on_folder_change(self, value: str) -> None:
        if value != "+ New Folder":
            return
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if name and name.strip():
            if name.strip().lower() in ("root", "home"):
                messagebox.showwarning("Reserved name", '"Home" is reserved — choose a different name.', parent=self)
                self._folder_var.set("🏠 Home")
                return
            self._db.create_folder(name.strip())
            self._refresh_folder_menu(select=name.strip())
        else:
            self._folder_var.set("🏠 Home")

    def _on_save(self) -> None:
        name = self._name_entry.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please enter a list name.", parent=self)
            return
        chosen = self._folder_var.get()
        if chosen == "+ New Folder":
            self._folder_var.set("🏠 Home")
            chosen = "🏠 Home"
        self.result_name = name
        self.result_folder_id = self._folder_map.get(chosen)  # None = Home/root
        self.destroy()


class CombineTab(ctk.CTkFrame):
    """The Combine tab: add sources, combine, view/copy/save output."""

    def __init__(self, parent, db: Database, switch_to_library_cb,
                 list_type_var: ctk.StringVar) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._switch_to_library = switch_to_library_cb
        self._list_type_var = list_type_var

        # url → credit name, populated by _extract_urls()
        self._url_credits: dict[str, str] = {}

        # Set by _run_combine(); guarded by check before first combine
        self._last_result: str = ""
        self._last_stats: dict = {}

        # Set by SettingsTab after Test Connection; resets on settings save
        self._server_reachable: bool = False

        # True once real combine output is present (guards placeholder cursor/selection)
        self._output_has_content: bool = False

        # List of (label, content_or_None) tuples.
        # content is None for URL/file paths (fetched on combine); str for pasted text.
        self._sources: list[tuple[str, Optional[str]]] = []

        # In-memory fetch cache: label → fetched content (session-scoped)
        self._fetch_cache: dict[str, str] = {}

        self._build_ui()
        self._refresh_sources_list()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0, minsize=290)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ── Left panel ──────────────────────────────────────────────
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)

        hdr_row = ctk.CTkFrame(left, fg_color="transparent")
        hdr_row.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))
        ctk.CTkLabel(hdr_row, text="SOURCES", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        type_toggle = ctk.CTkSegmentedButton(
            hdr_row, values=["Blocklist", "Allowlist"],
            variable=self._list_type_var, width=180,
        )
        type_toggle.pack(side="right")
        Tooltip(type_toggle, "Cosmetic only — affects the .txt header and window title.")

        # URL row
        url_row = ctk.CTkFrame(left, fg_color="transparent")
        url_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10)
        url_row.columnconfigure(0, weight=1)
        self._url_entry = ctk.CTkEntry(url_row, placeholder_text="https://...")
        self._url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._url_entry.bind("<Return>", lambda _: self._add_url())
        self._add_url_btn = ctk.CTkButton(url_row, text="+", width=36, command=self._add_url,
                                          state="disabled", fg_color=("gray75", "gray30"),
                                          hover_color=("gray65", "gray40"))
        self._add_url_btn.grid(row=0, column=1)
        Tooltip(self._add_url_btn, "Add this URL as a blocklist source.")
        self._url_entry.bind("<KeyRelease>", lambda _: self._refresh_add_url_btn())

        # Browse file button
        browse_btn = ctk.CTkButton(
            left, text="Browse File", command=self._browse_file, anchor="w"
        )
        browse_btn.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 0))
        Tooltip(browse_btn, "Select a local .txt blocklist file to add as a source.")

        # Extract URLs from clipboard
        extract_btn = ctk.CTkButton(
            left, text="Extract URLs from Clipboard",
            command=self._extract_urls, anchor="w",
        )
        extract_btn.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 0))
        Tooltip(extract_btn, "Reads your clipboard and adds every http/https URL found as a separate source.")

        # Sources toolbar (row 4)
        sources_toolbar = ctk.CTkFrame(left, fg_color="transparent")
        sources_toolbar.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        sources_toolbar.columnconfigure(0, weight=1)
        self._copy_sources_btn = ctk.CTkButton(
            sources_toolbar, text="Copy Sources", width=110, height=26,
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
            font=ctk.CTkFont(size=12), command=self._copy_sources,
        )
        self._copy_sources_btn.grid(row=0, column=1)
        Tooltip(self._copy_sources_btn, "Copy all source labels to the clipboard.")

        # Sources list (row 5 removed — label replaced by in-frame placeholder)
        self._sources_frame = ctk.CTkScrollableFrame(left, height=130)
        self._sources_frame.grid(
            row=5, column=0, columnspan=2, sticky="nsew", padx=10, pady=(4, 0)
        )
        left.rowconfigure(5, weight=1)
        # Auto-hide scrollbar + refit labels on canvas resize (window resize)
        def _on_canvas_resize(_):
            self.after(0, self._update_sources_scrollbar)
            self.after(0, self._refit_all_source_labels)
            if not self._sources:
                c = get_canvas(self._sources_frame)
                c.itemconfigure(get_inner_window_id(self._sources_frame),
                                height=c.winfo_height(), width=c.winfo_width())
        get_canvas(self._sources_frame).bind("<Configure>", _on_canvas_resize)

        combine_row = ctk.CTkFrame(left, fg_color="transparent")
        combine_row.grid(row=6, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        combine_row.columnconfigure(0, weight=3)
        combine_row.columnconfigure(1, weight=1)

        self._combine_btn = ctk.CTkButton(
            combine_row,
            text="COMBINE ALL",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            state="disabled",
            command=self._combine,
        )
        self._combine_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._clear_btn = ctk.CTkButton(
            combine_row, text="Clear All", height=40, command=self._clear_sources,
            fg_color=("gray60", "gray40"), state="disabled",
        )
        self._clear_btn.grid(row=0, column=1, sticky="ew")
        Tooltip(self._clear_btn, "Remove all sources from the list.")

        self._progress_bar = ctk.CTkProgressBar(left)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=7, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        self._progress_bar.grid_remove()

        self._progress_label = ctk.CTkLabel(left, text="", text_color=("gray15", "gray60"), anchor="w", wraplength=0)
        self._progress_label.grid(row=8, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))
        self._progress_label.grid_remove()
        self._progress_label.grid_propagate(False)

        # ── Right panel ─────────────────────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self._output_box = ctk.CTkTextbox(right, wrap="none", text_color="gray50", cursor="arrow")
        self._output_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        self._output_box.tag_config("placeholder", justify="center")
        self._output_box.insert("1.0", "Combine sources to see output here", "placeholder")
        self._output_box.configure(state="disabled")
        self._output_box.bind("<B1-Motion>",
                              lambda e: "break" if not self._output_has_content else None, add="+")
        self._output_box.bind("<Configure>", self._on_output_box_resize, add="+")

        # Stats row
        stats_row = ctk.CTkFrame(right, fg_color="transparent")
        stats_row.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._domains_label = ctk.CTkLabel(stats_row, text="Domains: 0")
        self._domains_label.pack(side="left", padx=(0, 16))
        self._dupes_label = ctk.CTkLabel(stats_row, text="Duplicates removed: 0")
        self._dupes_label.pack(side="left", padx=(0, 16))
        self._lines_label = ctk.CTkLabel(stats_row, text="Lines: 0")
        self._lines_label.pack(side="left")

        # Action buttons
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="w", padx=10, pady=(10, 4))
        self._copy_btn = ctk.CTkButton(btn_row, text="Copy", width=70, state="disabled", command=self._copy)
        self._copy_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._copy_btn, "Copy the combined output to the clipboard.")

        self._save_file_btn = ctk.CTkButton(btn_row, text="Save File", width=75, state="disabled", command=self._save_file)
        self._save_file_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._save_file_btn, "Export the combined list as a .txt file to disk.")

        self._save_lib_btn = ctk.CTkButton(
            btn_row, text="Save to Library", width=110, state="disabled", command=self._save_to_library
        )
        self._save_lib_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._save_lib_btn, "Save to the app's built-in library for later use.")

        self._push_btn = ctk.CTkButton(
            btn_row, text="Push", width=70, state="disabled", command=self._push_to_server
        )
        self._push_btn.pack(side="left")
        Tooltip(self._push_btn, "Upload the combined list to your phlist-server instance.")

    # ── Source management ────────────────────────────────────────────

    @staticmethod
    def _normalize_label(label: str) -> str:
        """Lowercase and strip trailing slashes for dedup comparison."""
        return label.lower().rstrip("/")

    def _is_duplicate(self, label: str) -> bool:
        """Check if *label* already exists in sources (case-insensitive)."""
        norm = self._normalize_label(label)
        return any(self._normalize_label(l) == norm for l, _ in self._sources)

    def _add_url(self) -> None:
        url = self._url_entry.get().strip()
        if not url:
            return
        if self._is_duplicate(url):
            messagebox.showinfo("Duplicate", "This source is already in the list.")
            return
        self._sources.append((url, None))
        credit = _credit_for_url(url, url)
        if credit:
            self._url_credits[url] = credit
        self._url_entry.delete(0, "end")
        self._refresh_add_url_btn()
        self._refresh_sources_list()

    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select blocklist file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            if self._is_duplicate(path):
                messagebox.showinfo("Duplicate", "This file is already in the list.")
                return
            self._sources.append((path, None))
            self._refresh_sources_list()

    def _extract_urls(self) -> None:
        """Read the clipboard and add every http/https URL found as a separate source."""
        try:
            text = self.clipboard_get()
        except Exception as exc:
            _log.debug("clipboard_get failed: %s", exc)
            text = ""
        if not text or not text.strip():
            messagebox.showinfo("Clipboard empty", "Nothing found in the clipboard.")
            return
        lines = text.splitlines()
        added = 0
        skipped = 0
        for i, line in enumerate(lines):
            for url in _URL_RE.findall(line):
                if self._is_duplicate(url):
                    skipped += 1
                    continue
                # Build context from surrounding lines for credit extraction
                # (YAML configs put name: on the line after url:)
                context = line
                for offset in (1, -1):
                    adj = i + offset
                    if 0 <= adj < len(lines):
                        context += " " + lines[adj]
                credit = _credit_for_url(url, context)
                if credit:
                    self._url_credits[url] = credit
                self._sources.append((url, None))
                added += 1
        if not added:
            messagebox.showinfo("No URLs found", "No http/https URLs were found in the clipboard.")
            return
        self._refresh_sources_list()
        msg = f"Added {added} URL(s) as sources."
        if skipped:
            msg += f"\n{skipped} duplicate(s) skipped."
        messagebox.showinfo("URLs added", msg)

    def _bind_label_truncate(self, lbl: ctk.CTkLabel, full_text: str) -> None:
        """Truncate label text with … to fit its allocated width; tooltip shows full text.

        Binds to the *row* frame's <Configure> rather than the label itself so that
        geometry is always available (the row fills the canvas width; the label with
        width=1 may report winfo_width()=1 until geometry fully propagates).
        """
        import tkinter.font as _tkfont

        Tooltip(lbl, f"{full_text}\n\nDouble-click to remove")
        row = lbl.master  # the CTkFrame row containing this label

        def _fit(event=None) -> None:
            row_w = event.width if event is not None else row.winfo_width()
            w = max(1, row_w - 8)
            if w <= 4:
                return
            try:
                inner = get_label_inner(lbl)
                f = _tkfont.Font(font=inner.cget("font")) if inner else _tkfont.nametofont("TkDefaultFont")
                t = full_text
                if f.measure(t) <= w:
                    new_text = t
                else:
                    while t and f.measure(t + "…") > w:
                        t = t[:-1]
                    new_text = t + "…"
                if lbl.cget("text") != new_text:
                    lbl.configure(text=new_text)
            except Exception as exc:
                _log.debug("Label refit failed: %s", exc)

        # Store so _refit_all_source_labels() can call this after geometry settles.
        # Do NOT bind <Configure> on the row — it fires many times during initial
        # layout and creates a letter-by-letter animation.  Refit is triggered
        # by _refit_all_source_labels() (canvas resize or after(50) on refresh).
        lbl._phlist_refit = _fit  # type: ignore[attr-defined]

    def _refit_all_source_labels(self) -> None:
        """Re-apply truncation to every source label (call after geometry settles)."""
        for row_widget in self._sources_frame.winfo_children():
            for child in row_widget.winfo_children():
                refit = getattr(child, '_phlist_refit', None)
                if refit is not None:
                    refit()

    def _update_sources_scrollbar(self) -> None:
        """Show the scrollbar only when content exceeds the visible area."""
        canvas = get_canvas(self._sources_frame)
        scrollbar = get_scrollbar(self._sources_frame)
        bbox = canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
            scrollbar.grid()
        else:
            scrollbar.grid_remove()

    def _show_output_placeholder(self) -> None:
        """Insert vertically + horizontally centered placeholder in the output box."""
        import tkinter.font as _tkfont
        text = "Combine sources to see output here"
        self._output_box.configure(state="normal")
        self._output_box.delete("1.0", "end")
        box_h = get_underlying_textbox(self._output_box).winfo_height()
        try:
            f = _tkfont.Font(font=get_underlying_textbox(self._output_box).cget("font"))
            line_h = f.metrics("linespace")
        except Exception as exc:
            _log.debug("Font metric fallback: %s", exc)
            line_h = 16
        blank = max(0, (box_h // max(line_h, 1)) // 2 - 1) if box_h > line_h else 0
        self._output_box.insert("1.0", "\n" * blank + text, "placeholder")
        self._output_box.configure(state="disabled")

    def _on_output_box_resize(self, _event=None) -> None:
        if self._output_has_content:
            return
        if hasattr(self, "_output_ph_after"):
            self.after_cancel(self._output_ph_after)
        self._output_ph_after = self.after(50, self._show_output_placeholder)

    def _bind_scroll(self, widget) -> None:
        """Forward mouse wheel events from *widget* to the sources scrollable frame.

        Uses fractional yview_moveto so the visible distance per tick stays
        constant (~3 rows) regardless of how many sources are in the list.
        """
        canvas = get_canvas(self._sources_frame)
        _ROW_PX = 26  # approximate row height (button height=24 + pady=1 each side)

        def _scroll(direction: int) -> None:
            bbox = canvas.bbox("all")
            if not bbox:
                return
            total_h = max(1, bbox[3] - bbox[1])
            visible_h = max(1, canvas.winfo_height())
            if total_h <= visible_h:
                return
            fraction = (3 * _ROW_PX) / total_h
            new_top = max(0.0, min(1.0 - visible_h / total_h,
                                   canvas.yview()[0] + direction * fraction))
            canvas.yview_moveto(new_top)

        widget.bind("<Button-4>", lambda _: _scroll(-1), add="+")
        widget.bind("<Button-5>", lambda _: _scroll(1), add="+")
        widget.bind("<MouseWheel>", lambda e: _scroll(-1 if e.delta > 0 else 1), add="+")

    def _refresh_sources_list(self) -> None:
        for widget in self._sources_frame.winfo_children():
            widget.destroy()
        # Reset inner frame to content-driven height
        get_canvas(self._sources_frame).itemconfigure(
            get_inner_window_id(self._sources_frame), height=0)
        if not self._sources:
            ctk.CTkLabel(
                self._sources_frame,
                text="No sources added yet",
                text_color="gray50",
                anchor="center",
                justify="center",
            ).pack(expand=True, fill="both")
            # Stretch inner frame to fill canvas so expand=True centers the label
            def _stretch():
                c = get_canvas(self._sources_frame)
                c.itemconfigure(get_inner_window_id(self._sources_frame),
                                height=c.winfo_height(), width=c.winfo_width())
            self.after(0, _stretch)
            self.after(0, self._update_sources_scrollbar)
            self._update_btn_states()
            return
        # Display sorted alphabetically by label; map display index → real index
        sorted_indices = sorted(range(len(self._sources)),
                                key=lambda i: self._sources[i][0].lower())
        for pos, real_idx in enumerate(sorted_indices):
            if pos >= _SOURCES_DISPLAY_LIMIT:
                break
            label, _ = self._sources[real_idx]
            row = ctk.CTkFrame(self._sources_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            lbl = ctk.CTkLabel(row, text=label, anchor="w", width=1, cursor="hand2")
            lbl.pack(fill="x", expand=True)
            self._bind_label_truncate(lbl, label)
            lbl.bind("<Double-Button-1>", lambda _, idx=real_idx: self._remove_source(idx))
            row.bind("<Double-Button-1>", lambda _, idx=real_idx: self._remove_source(idx))
            for w in (row, lbl):
                self._bind_scroll(w)
        overflow = len(self._sources) - _SOURCES_DISPLAY_LIMIT
        if overflow > 0:
            ctk.CTkButton(
                self._sources_frame,
                text=f"... and {overflow} more — View all sources",
                anchor="w",
                fg_color="transparent",
                text_color=("gray15", "gray60"),
                hover_color=("gray80", "gray20"),
                font=ctk.CTkFont(size=11),
                height=22,
                command=self._view_all_sources,
            ).pack(fill="x", pady=(4, 1))
        self.after(0, self._update_sources_scrollbar)
        self.after(50, self._refit_all_source_labels)
        self._update_btn_states()

    def _remove_source(self, index: int) -> None:
        if self._db.get_setting("sources_remove_confirm", "1") == "1":
            label, _ = self._sources[index]
            dlg = _ConfirmRemoveDialog(self, label)
            self.wait_window(dlg)
            if not dlg.confirmed:
                return
            if dlg.dont_ask_again:
                self._db.set_setting("sources_remove_confirm", "0")
        self._sources.pop(index)
        self._refresh_sources_list()

    def _copy_sources(self) -> None:
        """Copy all source labels to the clipboard."""
        if not self._sources:
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(label for label, _ in self._sources))
        messagebox.showinfo("Copied", f"Copied {len(self._sources)} source(s) to clipboard.")

    def _view_all_sources(self) -> None:
        """Write all source labels to a temp file and open in the system text editor."""
        lines = [label for label, _ in self._sources]
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", prefix="phlist_sources_",
                delete=False, encoding="utf-8"
            ) as f:
                f.write("\n".join(lines))
                tmp = f.name
            subprocess.Popen(["xdg-open", tmp])
        except Exception as exc:
            messagebox.showerror("Could not open", f"Failed to open source list:\n{exc}")

    def _clear_sources(self) -> None:
        if not self._sources:
            return
        if messagebox.askyesno(
            "Clear all sources",
            f"Remove all {len(self._sources)} source(s)?",
            parent=self,
        ):
            self._sources.clear()
            self._url_credits.clear()
            self._fetch_cache.clear()
            self._refresh_sources_list()

    # ── Combine ──────────────────────────────────────────────────────

    def _combine(self) -> None:
        if not self._sources:
            messagebox.showinfo("No sources", "Add at least one source first.")
            return
        if self._db.get_setting("combine_confirm", "1") == "1":
            dlg = _ConfirmCombineDialog(self)
            self.wait_window(dlg)
            if not dlg.confirmed:
                return
            if dlg.dont_ask_again:
                self._db.set_setting("combine_confirm", "0")
        _log.info("Combine started: %d source(s)", len(self._sources))
        self._combine_btn.configure(state="disabled", text="Combining...")
        self._progress_bar.set(0)
        self._progress_bar.grid()
        self._progress_label.configure(text="Starting...")
        self._progress_label.grid()
        self.winfo_toplevel().configure(cursor="watch")
        threading.Thread(target=self._run_combine, daemon=True).start()

    def _set_progress(self, value: float, text: str) -> None:
        self._progress_bar.set(value)
        self._progress_label.configure(text=text)

    def _run_combine(self) -> None:
        timeout = int(self._db.get_setting("fetch_timeout", "30"))
        max_mb  = int(self._db.get_setting("max_fetch_mb", "50"))
        fetcher = ListFetcher(timeout=timeout, max_bytes=max_mb * 1024 * 1024)
        combiner = ListCombiner()
        failed_sources: list[str] = []
        total = len(self._sources)
        cache_hits = 0

        for i, (label, content) in enumerate(self._sources):
            short = label if len(label) <= 35 else label[:32] + "..."

            if content is not None:
                # Pasted text — use inline, no caching needed
                self.after(0, lambda p=i / total, t=f"[{i + 1}/{total}]  {short}": self._set_progress(p, t))
                combiner.add_list(content, label)
            elif label in self._fetch_cache:
                # Cache hit
                cache_hits += 1
                self.after(0, lambda p=i / total, t=f"[{i + 1}/{total}] (cached) {short}": self._set_progress(p, t))
                combiner.add_list(self._fetch_cache[label], label)
            else:
                # Cache miss — fetch and store
                self.after(0, lambda p=i / total, t=f"[{i + 1}/{total}]  {short}": self._set_progress(p, t))
                fetched = fetcher.fetch(label)
                if fetched:
                    self._fetch_cache[label] = fetched
                    combiner.add_list(fetched, label)
                else:
                    failed_sources.append(label)

        _log.info("Cache: %d hits, %d misses", cache_hits, total - cache_hits)

        # Collect credits only for sources still present in the run
        active_labels = {label for label, _ in self._sources}
        credits = list(dict.fromkeys(
            name for url, name in self._url_credits.items() if url in active_labels
        ))
        result = combiner.get_combined(list_type=self._list_type_var.get(), credits=credits or None)
        stats = combiner.get_stats()

        self._last_result = result
        self._last_stats = stats
        _log.info("Combine done: %d domains, %d duplicates, %d failed",
                   stats["unique_domains"], stats["duplicates_removed"], len(failed_sources))

        self.after(0, lambda: self._update_output(result, stats, failed_sources))

    def _update_output(self, result: str, stats: dict, failed: Optional[list[str]] = None, reset_cursor: bool = True) -> None:
        self._output_has_content = True
        self._output_box.configure(state="normal", text_color=("gray10", "gray90"), cursor="")
        self._output_box.delete("1.0", "end")
        # Find the _DISPLAY_LIMIT-th newline without splitting the entire string
        pos = 0
        for _ in range(_DISPLAY_LIMIT):
            idx = result.find("\n", pos)
            if idx == -1:
                break
            pos = idx + 1
        else:
            # Reached the limit — count remaining lines without allocating a list
            remaining = result.count("\n", pos)
            display = (
                result[:pos]
                + f"\n# ... ({remaining:,} more lines not shown)"
                + "\n# Full list preserved — use Copy, Save, or Host to get all domains."
            )
            self._output_box.insert("1.0", display)
            self._output_box.configure(state="disabled")
            self._finish_output_ui(stats, failed, reset_cursor=reset_cursor)
            return
        self._output_box.insert("1.0", result)
        self._output_box.configure(state="disabled")
        self._finish_output_ui(stats, failed, reset_cursor=reset_cursor)

    def _finish_output_ui(self, stats: dict, failed: Optional[list[str]], reset_cursor: bool = True) -> None:
        if reset_cursor:
            self.winfo_toplevel().configure(cursor="")
        self._domains_label.configure(text=f"Domains: {stats['unique_domains']}")
        self._dupes_label.configure(text=f"Duplicates removed: {stats['duplicates_removed']}")
        self._lines_label.configure(text=f"Lines: {len(self._last_result.splitlines())}")
        failed_bool = bool(failed)
        if not failed_bool:
            flash_color, flash_hover, flash_text = _CLR_BTN_SUCCESS, _CLR_BTN_SUCCESS_HOVER, "Done ✓"
        else:
            flash_color, flash_hover = _CLR_BTN_DANGER, _CLR_BTN_DANGER_HOVER
            flash_text = "⚠ Partial" if self._last_result else "⚠ Failed"

        self._combine_btn.configure(
            state="normal" if self._sources else "disabled",
            text=flash_text,
            fg_color=flash_color,
            hover_color=flash_hover,
        )

        def _reset_combine_btn():
            self._combine_btn.configure(
                text="COMBINE ALL",
                fg_color=_CLR_BTN_DEFAULT,
                hover_color=_CLR_BTN_DEFAULT_HOVER,
            )
            self._update_btn_states()

        self.after(2000, _reset_combine_btn)
        self._update_btn_states()
        self._progress_bar.grid_remove()
        self._progress_label.grid_remove()
        if failed:
            messagebox.showwarning(
                "Some sources failed",
                f"{len(failed)} source(s) could not be fetched:\n\n" + "\n".join(failed),
            )

    # ── Output actions ───────────────────────────────────────────────

    def _copy(self) -> None:
        text = self._last_result or self._output_box.get("1.0", "end").strip()
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            messagebox.showerror("Clipboard error", "Could not copy to clipboard.")
            return
        messagebox.showinfo("Copied", "Output copied to clipboard.")

    def _save_file(self) -> None:
        text = self._last_result or self._output_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to save", "Combine sources first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            messagebox.showinfo("Saved", f"Saved to {path}")

    def _save_to_library(self) -> None:
        if not self._last_result:
            messagebox.showwarning("Nothing to save", "Combine sources first.")
            return
        dialog = SaveToLibraryDialog(self, self._db)
        self.wait_window(dialog)
        if dialog.result_name:
            # Serialize non-paste sources so they can be restored later
            sources_data = [
                {"type": "url" if label.startswith(("http://", "https://")) else "file", "label": label}
                for label, content in self._sources
                if content is None
            ]
            sources_json = json.dumps(sources_data) if sources_data else ""
            self._db.save_list(
                name=dialog.result_name,
                content=self._last_result,
                domain_count=self._last_stats["unique_domains"],
                duplicates_removed=self._last_stats["duplicates_removed"],
                folder_id=dialog.result_folder_id,
                sources=sources_json,
            )
            messagebox.showinfo("Saved", f'"{dialog.result_name}" saved to library.')

    def _refresh_add_url_btn(self) -> None:
        has_text = bool(self._url_entry.get().strip())
        self._add_url_btn.configure(
            state="normal" if has_text else "disabled",
            fg_color=("gray75", "gray30") if not has_text else ["#3B8ED0", "#1F6AA5"],
            hover_color=("gray65", "gray40") if not has_text else ["#36719F", "#144870"],
        )

    def _update_btn_states(self) -> None:
        """Enable/disable buttons based on whether sources and output are present."""
        has_sources = bool(self._sources)
        has_result = bool(self._last_result)
        self._combine_btn.configure(state="normal" if has_sources else "disabled")
        self._clear_btn.configure(
            state="normal" if has_sources else "disabled",
            fg_color=_CLR_BTN_DANGER if has_sources else ("gray60", "gray40"),
            hover_color=_CLR_BTN_DANGER_HOVER if has_sources else ("gray55", "gray35"),
        )
        self._copy_sources_btn.configure(state="normal" if has_sources else "disabled")
        self._copy_btn.configure(state="normal" if has_result else "disabled")
        self._save_file_btn.configure(state="normal" if has_result else "disabled")
        self._save_lib_btn.configure(state="normal" if has_result else "disabled")
        self.refresh_push_btn_state()

    def refresh_push_btn_state(self) -> None:
        """Enable Push only when output, server settings, and reachability all pass."""
        has_result = bool(self._last_result)
        has_url = bool(self._db.get_setting("remote_server_url", ""))
        has_key = bool(self._db.get_setting("remote_server_key", ""))
        ready = has_result and has_url and has_key and self._server_reachable
        if ready:
            self._push_btn.configure(state="normal", fg_color=_CLR_BTN_SUCCESS, hover_color=_CLR_BTN_SUCCESS_HOVER)
        else:
            self._push_btn.configure(state="disabled", fg_color=("gray60", "gray40"))

    def set_server_reachable(self, ok: bool) -> None:
        """Called by SettingsTab after a connection test completes."""
        self._server_reachable = ok
        self.refresh_push_btn_state()

    def _push_to_server(self) -> None:
        if not self._last_result:
            return
        base_url = self._db.get_setting("remote_server_url", "").rstrip("/")
        api_key = self._db.get_setting("remote_server_key", "")
        if not base_url:
            messagebox.showwarning(
                "No server configured",
                "Add a remote server URL in Settings → Remote Server.",
            )
            return
        default_slug = self._db.get_setting("default_host_filename", "") or "blocklist"
        slug = simpledialog.askstring(
            "Push to Server",
            "List name (e.g. blocklist) — saved as <name>.txt on the server:",
            initialvalue=default_slug,
            parent=self,
        )
        if not slug or not slug.strip():
            return
        slug = re.sub(r'[^a-z0-9]+', '-', slug.strip().lower()).strip('-')
        if not slug:
            return
        content = self._last_result
        self._push_btn.configure(state="disabled", text="Pushing...")

        def _worker():
            push_timeout = int(self._db.get_setting("push_timeout", "300"))
            ok, msg = _push_list(base_url, api_key, slug, content, timeout=push_timeout)

            def _done():
                if ok:
                    self._db.set_setting("default_host_filename", slug)
                    self._push_btn.configure(text="Push")
                    self.refresh_push_btn_state()
                    pi_url = f"{base_url}/lists/{slug}.txt"
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(pi_url)
                    except Exception:
                        pass
                    messagebox.showinfo(
                        "Pushed",
                        f"{msg}\n\nPi-hole URL (copied to clipboard):\n{pi_url}",
                    )
                else:
                    self._push_btn.configure(
                        state="normal", text="Push",
                        fg_color=_CLR_BTN_DANGER, hover_color=_CLR_BTN_DANGER_HOVER,
                    )
                    self.after(2000, self.refresh_push_btn_state)
                    messagebox.showerror("Push failed", msg)

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def load_library_result(self, name: str, sources: list, content: str, stats: dict) -> None:
        """Load a pre-combined library result: populate sources panel and output box."""
        self._sources.clear()
        self._fetch_cache.clear()
        self._url_credits.clear()
        need_fallback = not sources
        for s in sources:
            if s["type"] == "url":
                self._sources.append((s["label"], None))
            elif s["type"] == "file" and Path(s["label"]).exists():
                self._sources.append((s["label"], None))
            else:
                need_fallback = True
        if need_fallback:
            self._sources.append((f"[library] {name}", content))
        self._refresh_sources_list()
        self._last_result = content
        self._last_stats = stats
        self._update_output(content, stats, reset_cursor=False)  # library caller owns cursor

