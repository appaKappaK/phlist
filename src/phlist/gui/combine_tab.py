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
from ..server import ListServer
from .tooltip import Tooltip

_log = logging.getLogger(__name__)

# ── UI colors (easy to tweak) ────────────────────────────────────────
_CLR_HOST_ON = "#27AE60"
_CLR_HOST_OFF = "#C0392B"
_CLR_BTN_DEFAULT = ["#3B8ED0", "#1F6AA5"]
_CLR_BTN_DANGER = ["#C0392B", "#922B21"]

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
        self._folder_var = ctk.StringVar(value="Root")
        self._folder_menu = ctk.CTkOptionMenu(
            self, variable=self._folder_var, values=["Root"],
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
        options = ["Root"] + list(self._folder_map.keys()) + ["+ New Folder"]
        self._folder_menu.configure(values=options)
        if select and select in self._folder_map:
            self._folder_var.set(select)

    def _on_folder_change(self, value: str) -> None:
        if value != "+ New Folder":
            return
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if name and name.strip():
            if name.strip().lower() == "root":
                messagebox.showwarning("Reserved name", '"Root" is reserved — choose a different name.', parent=self)
                self._folder_var.set("Root")
                return
            self._db.create_folder(name.strip())
            self._refresh_folder_menu(select=name.strip())
        else:
            self._folder_var.set("Root")

    def _on_save(self) -> None:
        name = self._name_entry.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please enter a list name.", parent=self)
            return
        chosen = self._folder_var.get()
        if chosen == "+ New Folder":
            self._folder_var.set("Root")
            chosen = "Root"
        self.result_name = name
        self.result_folder_id = self._folder_map.get(chosen)  # None = root
        self.destroy()


class CombineTab(ctk.CTkFrame):
    """The Combine tab: add sources, combine, view/copy/save output."""

    def __init__(self, parent, db: Database, switch_to_library_cb, server: ListServer,
                 list_type_var: ctk.StringVar) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._switch_to_library = switch_to_library_cb
        self._server = server
        self._list_type_var = list_type_var

        # Whether the Combine tab is currently hosting; tracks the active path
        self._serving: bool = False
        self._serving_path: str = ""

        # url → credit name, populated by _extract_urls()
        self._url_credits: dict[str, str] = {}

        # Set by _run_combine(); guarded by check before first combine
        self._last_result: str = ""
        self._last_stats: dict = {}

        # Set by SettingsTab after Test Connection; resets on settings save
        self._server_reachable: bool = False

        # List of (label, content_or_None) tuples.
        # content is None for URL/file paths (fetched on combine); str for pasted text.
        self._sources: list[tuple[str, Optional[str]]] = []

        # In-memory fetch cache: label → fetched content (session-scoped)
        self._fetch_cache: dict[str, str] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1, minsize=340)
        self.columnconfigure(1, weight=2)
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
        add_url_btn = ctk.CTkButton(url_row, text="+", width=36, command=self._add_url)
        add_url_btn.grid(row=0, column=1)
        Tooltip(add_url_btn, "Add this URL as a blocklist source.")

        # Browse file button
        browse_btn = ctk.CTkButton(
            left, text="Browse File...", command=self._browse_file, anchor="w"
        )
        browse_btn.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 0))
        Tooltip(browse_btn, "Select a local .txt blocklist file to add as a source.")

        # Paste area
        self._paste_box = ctk.CTkTextbox(left, height=120, text_color=("gray10", "gray90"))
        self._paste_box.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        self._paste_placeholder = "Paste raw blocklist text or URLs here..."
        self._paste_box.insert("1.0", self._paste_placeholder)
        self._paste_box.configure(text_color="gray60")
        self._paste_has_placeholder = True
        self._paste_box.bind("<FocusIn>", self._paste_focus_in)
        self._paste_box.bind("<FocusOut>", self._paste_focus_out)
        paste_btn_row = ctk.CTkFrame(left, fg_color="transparent")
        paste_btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(6, 0))
        paste_btn_row.columnconfigure(0, weight=1)
        paste_btn_row.columnconfigure(1, weight=1)
        add_btn = ctk.CTkButton(
            paste_btn_row, text="Add as Blocklist", command=self._add_pasted
        )
        add_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        Tooltip(add_btn, "Treats pasted text as a single raw blocklist and adds it as one source.")

        extract_btn = ctk.CTkButton(
            paste_btn_row, text="Extract URLs", command=self._extract_urls
        )
        extract_btn.grid(row=0, column=1, sticky="ew")
        Tooltip(extract_btn, "Pulls all URLs from pasted text and adds each as a separate source.")

        # Sources list
        ctk.CTkLabel(left, text="Sources added:").grid(
            row=5, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 2)
        )
        self._sources_frame = ctk.CTkScrollableFrame(left, height=130)
        self._sources_frame.grid(
            row=6, column=0, columnspan=2, sticky="nsew", padx=10
        )
        left.rowconfigure(6, weight=1)
        # Auto-hide scrollbar when content fits; re-check on resize
        self._sources_frame._parent_canvas.bind(
            "<Configure>", lambda _: self.after(0, self._update_sources_scrollbar)
        )

        combine_row = ctk.CTkFrame(left, fg_color="transparent")
        combine_row.grid(row=7, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        combine_row.columnconfigure(0, weight=3)
        combine_row.columnconfigure(1, weight=1)

        self._combine_btn = ctk.CTkButton(
            combine_row,
            text="COMBINE ALL",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._combine,
        )
        self._combine_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        clear_btn = ctk.CTkButton(
            combine_row, text="Clear All", height=40, command=self._clear_sources,
            fg_color=_CLR_BTN_DANGER,
        )
        clear_btn.grid(row=0, column=1, sticky="ew")
        Tooltip(clear_btn, "Remove all sources from the list.")

        self._progress_bar = ctk.CTkProgressBar(left)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=8, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        self._progress_bar.grid_remove()

        self._progress_label = ctk.CTkLabel(left, text="", text_color=("gray15", "gray60"), anchor="w", wraplength=0)
        self._progress_label.grid(row=9, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))
        self._progress_label.grid_remove()
        self._progress_label.grid_propagate(False)

        # ── Right panel ─────────────────────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="OUTPUT", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, pady=(10, 6), padx=10, sticky="w"
        )

        self._output_box = ctk.CTkTextbox(right, state="disabled", wrap="none",
                                          text_color=("gray10", "gray90"))
        self._output_box.grid(row=1, column=0, sticky="nsew", padx=10)

        # Stats row
        stats_row = ctk.CTkFrame(right, fg_color="transparent")
        stats_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._domains_label = ctk.CTkLabel(stats_row, text="Domains: 0")
        self._domains_label.pack(side="left", padx=(0, 16))
        self._dupes_label = ctk.CTkLabel(stats_row, text="Duplicates removed: 0")
        self._dupes_label.pack(side="left")

        # Action buttons
        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="w", padx=10, pady=(10, 4))
        copy_btn = ctk.CTkButton(btn_row, text="Copy to Clipboard", width=145, command=self._copy)
        copy_btn.pack(side="left", padx=(0, 8))
        Tooltip(copy_btn, "Copy the combined output to the clipboard.")

        save_file_btn = ctk.CTkButton(btn_row, text="Save File...", width=100, command=self._save_file)
        save_file_btn.pack(side="left", padx=(0, 8))
        Tooltip(save_file_btn, "Export the combined list as a .txt file to disk.")

        save_lib_btn = ctk.CTkButton(
            btn_row, text="Save to Library", width=130, command=self._save_to_library
        )
        save_lib_btn.pack(side="left", padx=(0, 8))
        Tooltip(save_lib_btn, "Save to the app's built-in library for later use.")

        self._push_btn = ctk.CTkButton(
            btn_row, text="Push to Server", width=130, state="disabled", command=self._push_to_server
        )
        self._push_btn.pack(side="left")
        Tooltip(self._push_btn, "Upload the combined list to your phlist-server instance.")

        # Host row — host the list over HTTP for Pi-hole to pull
        serve_row = ctk.CTkFrame(right, fg_color="transparent")
        serve_row.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._serve_indicator = ctk.CTkLabel(
            serve_row, text="●", text_color=_CLR_HOST_OFF, width=16
        )
        self._serve_indicator.pack(side="left", padx=(0, 4))
        self._serve_btn = ctk.CTkButton(
            serve_row, text="Host List", width=110, command=self._toggle_serve
        )
        self._serve_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._serve_btn, "Host the combined list over HTTP so Pi-hole can pull it directly.")

        self._serve_name_entry = ctk.CTkEntry(
            serve_row, placeholder_text="blocklist", width=120
        )
        # Pre-fill with saved default filename
        default_fname = self._db.get_setting("default_host_filename", "")
        if default_fname:
            self._serve_name_entry.insert(0, default_fname)
        self._serve_name_entry.pack(side="left", padx=(0, 4))
        Tooltip(self._serve_name_entry, "Name the hosted file to create unique URLs for Pi-hole group management. Leave blank for 'blocklist.txt'.")

        ctk.CTkLabel(serve_row, text=".txt", text_color=("gray15", "gray60")).pack(
            side="left", padx=(0, 8)
        )
        self._serve_url_var = ctk.StringVar()
        self._serve_url_entry = ctk.CTkEntry(
            serve_row, textvariable=self._serve_url_var, width=280, state="disabled",
        )
        self._serve_copy_btn = ctk.CTkButton(
            serve_row, text="Copy URL", width=80, command=self._copy_serve_url
        )
        Tooltip(self._serve_copy_btn, "Copy the URL to add on Pi-hole's Lists tab.")
        # URL entry + copy button hidden until hosting starts

    # ── Paste placeholder ────────────────────────────────────────────

    def _paste_focus_in(self, _event=None) -> None:
        if self._paste_has_placeholder:
            self._paste_box.delete("1.0", "end")
            self._paste_box.configure(text_color=("gray10", "gray90"))
            self._paste_has_placeholder = False

    def _paste_focus_out(self, _event=None) -> None:
        if not self._paste_box.get("1.0", "end").strip():
            self._paste_box.insert("1.0", self._paste_placeholder)
            self._paste_box.configure(text_color="gray60")
            self._paste_has_placeholder = True

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

    def _add_pasted(self) -> None:
        if self._paste_has_placeholder:
            return
        text = self._paste_box.get("1.0", "end").strip()
        if not text:
            return
        label = f"[pasted #{len(self._sources) + 1}]"
        self._sources.append((label, text))
        self._paste_box.delete("1.0", "end")
        self._paste_focus_out()  # restore placeholder
        self._refresh_sources_list()

    def _extract_urls(self) -> None:
        """Extract all http/https URLs from the paste box and add as URL sources.

        Also records a credit name for each URL (from surrounding line text or
        the GitHub username in the URL) for inclusion in the combined list header.
        """
        if self._paste_has_placeholder:
            messagebox.showinfo("No URLs found", "No http/https URLs were found in the pasted text.")
            return
        text = self._paste_box.get("1.0", "end")
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
            messagebox.showinfo("No URLs found", "No http/https URLs were found in the pasted text.")
            return
        self._paste_box.delete("1.0", "end")
        self._paste_focus_out()  # restore placeholder
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

        Tooltip(lbl, full_text)
        row = lbl.master  # the CTkFrame row containing this label and the X button

        def _fit(event=None) -> None:
            # Use row width; subtract X button (width=28) + side padding (~10px)
            row_w = event.width if event is not None else row.winfo_width()
            w = max(1, row_w - 38)
            if w <= 4:
                return
            try:
                inner = getattr(lbl, '_label', None) or getattr(lbl, '_text_label', None)
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
            except Exception:
                pass

        row.bind("<Configure>", _fit)
        # Store so _refit_all_source_labels() can call this after geometry settles
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
        canvas = self._sources_frame._parent_canvas
        scrollbar = self._sources_frame._scrollbar
        bbox = canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
            scrollbar.grid()
        else:
            scrollbar.grid_remove()

    def _bind_scroll(self, widget) -> None:
        """Forward mouse wheel events from *widget* to the sources scrollable frame.

        Uses fractional yview_moveto so the visible distance per tick stays
        constant (~3 rows) regardless of how many sources are in the list.
        """
        canvas = self._sources_frame._parent_canvas
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
        # Display sorted alphabetically by label; map display index → real index
        sorted_indices = sorted(range(len(self._sources)),
                                key=lambda i: self._sources[i][0].lower())
        for pos, real_idx in enumerate(sorted_indices):
            if pos >= _SOURCES_DISPLAY_LIMIT:
                break
            label, _ = self._sources[real_idx]
            row = ctk.CTkFrame(self._sources_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            btn = ctk.CTkButton(
                row,
                text="✕",
                width=28,
                height=24,
                command=lambda idx=real_idx: self._remove_source(idx),
            )
            btn.pack(side="right")
            lbl = ctk.CTkLabel(row, text=label, anchor="w", width=1)
            lbl.pack(side="left", fill="x", expand=True)
            self._bind_label_truncate(lbl, label)
            for w in (row, lbl, btn):
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

    def _remove_source(self, index: int) -> None:
        self._sources.pop(index)
        self._refresh_sources_list()

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
        fetcher = ListFetcher(timeout=timeout)
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
        self._output_box.configure(state="normal")
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
        self._dupes_label.configure(
            text=f"Duplicates removed: {stats['duplicates_removed']}"
        )
        self._combine_btn.configure(state="normal", text="COMBINE ALL")
        self.refresh_push_btn_state()
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
            self._switch_to_library()

    def refresh_push_btn_state(self) -> None:
        """Enable Push to Server only when combined output, server settings, and reachability all pass."""
        has_result = bool(self._last_result)
        has_url = bool(self._db.get_setting("remote_server_url", ""))
        has_key = bool(self._db.get_setting("remote_server_key", ""))
        state = "normal" if (has_result and has_url and has_key and self._server_reachable) else "disabled"
        self._push_btn.configure(state=state)

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
            "Slug for this list (e.g. blocklist):",
            initialvalue=default_slug,
            parent=self,
        )
        if not slug or not slug.strip():
            return
        slug = slug.strip()
        content = self._last_result
        self._push_btn.configure(state="disabled", text="Pushing...")

        def _worker():
            ok, msg = _push_list(base_url, api_key, slug, content)

            def _done():
                self._push_btn.configure(state="normal", text="Push to Server")
                if ok:
                    messagebox.showinfo(
                        "Pushed",
                        f"{msg}\n\nPi-hole URL:\n{base_url}/lists/{slug}.txt",
                    )
                else:
                    messagebox.showerror("Push failed", msg)

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Host over HTTP ───────────────────────────────────────────────

    def _serve_path_from_name(self) -> str:
        """Build a URL path from the filename entry, defaulting to ``/blocklist.txt``."""
        raw = self._serve_name_entry.get().strip()
        if not raw:
            return "/blocklist.txt"
        # Strip .txt if user typed it, we add it ourselves
        if raw.lower().endswith(".txt"):
            raw = raw[:-4]
        slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', raw).strip('-')
        return f"/{slug or 'blocklist'}.txt"

    def _toggle_serve(self) -> None:
        if self._serving:
            self._server.remove_path(self._serving_path)
            self._serving = False
            self._serving_path = ""
            self._serve_indicator.configure(text_color=_CLR_HOST_OFF)
            self._serve_btn.configure(text="Host List", fg_color=_CLR_BTN_DEFAULT)
            self._serve_name_entry.configure(state="normal")
            self._serve_url_entry.pack_forget()
            self._serve_copy_btn.pack_forget()
        else:
            content = self._last_result or self._output_box.get("1.0", "end").strip()
            if not content:
                messagebox.showwarning("Nothing to host", "Combine sources first.")
                return
            path = self._serve_path_from_name()
            try:
                url = self._server.add_path(path, content)
            except OSError as exc:
                messagebox.showerror("Server error", f"Could not start server:\n{exc}")
                return
            self._serving = True
            self._serving_path = path
            self._serve_url_var.set(url)
            self._serve_name_entry.configure(state="disabled")
            self._serve_url_entry.pack(side="left", padx=(0, 8))
            self._serve_copy_btn.pack(side="left")
            self._serve_indicator.configure(text_color=_CLR_HOST_ON)
            self._serve_btn.configure(text="Stop Hosting", fg_color=_CLR_BTN_DANGER)

    def _copy_serve_url(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(self._serve_url_var.get())
        except Exception:
            messagebox.showerror("Clipboard error", "Could not copy to clipboard.")
            return
        messagebox.showinfo("Copied", "URL copied — add it on Pi-hole's Lists tab,\nthen run gravity.")

    def load_content_as_source(self, label: str, content: str) -> None:
        """Called by LibraryTab to inject a saved list as an in-memory source."""
        self._sources.append((label, content))
        self._refresh_sources_list()

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

    def load_sources_from_library(self, name: str, sources: list, content: str) -> None:
        """Restore individual URL/file sources from a saved library list.

        URL sources are added directly (re-fetchable). Missing file sources and
        paste-text sources that cannot be restored fall back to the saved content blob.
        """
        need_fallback = not sources
        for s in sources:
            if s["type"] == "url":
                self._sources.append((s["label"], None))
            elif s["type"] == "file" and Path(s["label"]).exists():
                self._sources.append((s["label"], None))
            else:
                need_fallback = True  # missing file or originally pasted text
        if need_fallback:
            self._sources.append((f"[library] {name}", content))
        self._refresh_sources_list()
