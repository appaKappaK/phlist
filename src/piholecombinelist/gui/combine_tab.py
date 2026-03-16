"""Combine tab and Save-to-Library dialog."""

import json
import re
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

import customtkinter as ctk

from ..combiner import ListCombiner
from ..database import Database
from ..fetcher import ListFetcher
from ..server import ListServer
from .tooltip import Tooltip

# Matches any http/https URL in arbitrary text (e.g. Pi-hole dashboard paste).
# Excludes backtick, pipe, and angle-bracket characters that appear in markdown
# table formatting but are never valid unencoded URL characters.
_URL_RE = re.compile(r'https?://[^\s`|<>"\']+')

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
_NOISE_RE = re.compile(r'[✓✗☑☐✔✘]|\b(enabled|disabled|true|false|yes|no)\b', re.I)


def _credit_for_url(url: str, line: str) -> Optional[str]:
    """Return a credit name for *url* by examining *line* or the URL itself."""
    # 1. Strip the URL and table/markdown noise from the line
    remaining = _URL_RE.sub('', line)
    remaining = _NOISE_RE.sub(' ', remaining)
    remaining = re.sub(r'[`*_]', '', remaining)          # strip markdown formatting chars
    remaining = re.sub(r'\s+', ' ', remaining).strip(' \t|,;')
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

        # Whether the Combine tab is currently serving; tracks the active path
        self._serving: bool = False
        self._serving_path: str = ""

        # url → credit name, populated by _extract_urls()
        self._url_credits: dict[str, str] = {}

        # Set by _run_combine(); guarded by check before first combine
        self._last_result: str = ""
        self._last_stats: dict = {}

        # List of (label, content_or_None) tuples.
        # content is None for URL/file paths (fetched on combine); str for pasted text.
        self._sources: list[tuple[str, Optional[str]]] = []

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1, minsize=340)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        # ── Left panel ──────────────────────────────────────────────
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="SOURCES", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, pady=(10, 6), padx=10, sticky="w"
        )

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
        self._paste_box = ctk.CTkTextbox(left, height=120)
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

        self._combine_btn = ctk.CTkButton(
            left,
            text="COMBINE ALL",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._combine,
        )
        self._combine_btn.grid(row=7, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        self._progress_bar = ctk.CTkProgressBar(left)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=8, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 4))
        self._progress_bar.grid_remove()

        self._progress_label = ctk.CTkLabel(left, text="", text_color="gray60", anchor="w")
        self._progress_label.grid(row=9, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))
        self._progress_label.grid_remove()

        # ── Right panel ─────────────────────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="OUTPUT", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, pady=(10, 6), padx=10, sticky="w"
        )

        self._output_box = ctk.CTkTextbox(right, state="disabled", wrap="none")
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
        btn_row.grid(row=3, column=0, sticky="ew", padx=10, pady=(10, 4))
        copy_btn = ctk.CTkButton(btn_row, text="Copy to Clipboard", command=self._copy)
        copy_btn.pack(side="left", padx=(0, 8))
        Tooltip(copy_btn, "Copy the combined output to the clipboard.")

        save_file_btn = ctk.CTkButton(btn_row, text="Save File...", command=self._save_file)
        save_file_btn.pack(side="left", padx=(0, 8))
        Tooltip(save_file_btn, "Export the combined list as a .txt file to disk.")

        save_lib_btn = ctk.CTkButton(
            btn_row, text="Save to Library", command=self._save_to_library
        )
        save_lib_btn.pack(side="left")
        Tooltip(save_lib_btn, "Save to the app's built-in library for later use.")

        # Serve row — host the list over HTTP for Pi-hole to pull
        serve_row = ctk.CTkFrame(right, fg_color="transparent")
        serve_row.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        self._serve_indicator = ctk.CTkLabel(
            serve_row, text="●", text_color="#C0392B", width=16
        )
        self._serve_indicator.pack(side="left", padx=(0, 4))
        self._serve_btn = ctk.CTkButton(
            serve_row, text="Serve List", width=110, command=self._toggle_serve
        )
        self._serve_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._serve_btn, "Host the combined list over HTTP so Pi-hole can pull it directly.")

        self._serve_name_entry = ctk.CTkEntry(
            serve_row, placeholder_text="blocklist", width=120
        )
        self._serve_name_entry.pack(side="left", padx=(0, 4))
        Tooltip(self._serve_name_entry, "Name the hosted file to create unique URLs for Pi-hole group management. Leave blank for 'blocklist.txt'.")

        ctk.CTkLabel(serve_row, text=".txt", text_color="gray60").pack(
            side="left", padx=(0, 8)
        )
        self._serve_url_var = ctk.StringVar()
        self._serve_url_entry = ctk.CTkEntry(
            serve_row, textvariable=self._serve_url_var, width=280, state="disabled",
        )
        self._serve_copy_btn = ctk.CTkButton(
            serve_row, text="Copy URL", width=80, command=self._copy_serve_url
        )
        Tooltip(self._serve_copy_btn, "Copy the URL to paste into Pi-hole's Adlists page.")
        # URL entry + copy button hidden until server starts

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

    def _add_url(self) -> None:
        url = self._url_entry.get().strip()
        if not url:
            return
        self._sources.append((url, None))
        self._url_entry.delete(0, "end")
        self._refresh_sources_list()

    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select blocklist file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
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
        added = 0
        for line in text.splitlines():
            for url in _URL_RE.findall(line):
                credit = _credit_for_url(url, line)
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
        messagebox.showinfo("URLs added", f"Added {added} URL(s) as sources.")

    def _refresh_sources_list(self) -> None:
        for widget in self._sources_frame.winfo_children():
            widget.destroy()
        for i, (label, _) in enumerate(self._sources):
            row = ctk.CTkFrame(self._sources_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=label, anchor="w", wraplength=220).pack(
                side="left", fill="x", expand=True
            )
            ctk.CTkButton(
                row,
                text="✕",
                width=28,
                height=24,
                command=lambda idx=i: self._remove_source(idx),
            ).pack(side="right")

    def _remove_source(self, index: int) -> None:
        self._sources.pop(index)
        self._refresh_sources_list()

    # ── Combine ──────────────────────────────────────────────────────

    def _combine(self) -> None:
        if not self._sources:
            messagebox.showinfo("No sources", "Add at least one source first.")
            return
        self._combine_btn.configure(state="disabled", text="Combining...")
        self._progress_bar.set(0)
        self._progress_bar.grid()
        self._progress_label.configure(text="Starting...")
        self._progress_label.grid()
        threading.Thread(target=self._run_combine, daemon=True).start()

    def _set_progress(self, value: float, text: str) -> None:
        self._progress_bar.set(value)
        self._progress_label.configure(text=text)

    def _run_combine(self) -> None:
        fetcher = ListFetcher()
        combiner = ListCombiner()
        failed_sources: list[str] = []
        total = len(self._sources)

        for i, (label, content) in enumerate(self._sources):
            short = label if len(label) <= 55 else label[:52] + "..."
            self.after(0, lambda p=i / total, t=f"[{i + 1}/{total}]  {short}": self._set_progress(p, t))

            if content is not None:
                combiner.add_list(content, label)
            else:
                fetched = fetcher.fetch(label)
                if fetched:
                    combiner.add_list(fetched, label)
                else:
                    failed_sources.append(label)

        # Collect credits only for sources still present in the run
        active_labels = {label for label, _ in self._sources}
        credits = list(dict.fromkeys(
            name for url, name in self._url_credits.items() if url in active_labels
        ))
        result = combiner.get_combined(list_type=self._list_type_var.get(), credits=credits or None)
        stats = combiner.get_stats()

        self._last_result = result
        self._last_stats = stats

        self.after(0, lambda: self._update_output(result, stats, failed_sources))

    def _update_output(self, result: str, stats: dict, failed: Optional[list[str]] = None) -> None:
        self._output_box.configure(state="normal")
        self._output_box.delete("1.0", "end")
        self._output_box.insert("1.0", result)
        self._output_box.configure(state="disabled")
        self._domains_label.configure(text=f"Domains: {stats['unique_domains']}")
        self._dupes_label.configure(
            text=f"Duplicates removed: {stats['duplicates_removed']}"
        )
        self._combine_btn.configure(state="normal", text="COMBINE ALL")
        self._progress_bar.grid_remove()
        self._progress_label.grid_remove()
        if failed:
            messagebox.showwarning(
                "Some sources failed",
                f"{len(failed)} source(s) could not be fetched:\n\n" + "\n".join(failed),
            )

    # ── Output actions ───────────────────────────────────────────────

    def _copy(self) -> None:
        text = self._output_box.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", "Output copied to clipboard.")

    def _save_file(self) -> None:
        text = self._output_box.get("1.0", "end").strip()
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
                {"type": "url" if label.startswith("http") else "file", "label": label}
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

    # ── Serve over HTTP ──────────────────────────────────────────────

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
            self._serve_indicator.configure(text_color="#C0392B")
            self._serve_btn.configure(text="Serve List", fg_color=["#3B8ED0", "#1F6AA5"])
            self._serve_name_entry.configure(state="normal")
            self._serve_url_entry.pack_forget()
            self._serve_copy_btn.pack_forget()
        else:
            content = self._output_box.get("1.0", "end").strip()
            if not content:
                messagebox.showwarning("Nothing to serve", "Combine sources first.")
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
            self._serve_indicator.configure(text_color="#27AE60")
            self._serve_btn.configure(text="Stop Serving", fg_color=["#C0392B", "#922B21"])

    def _copy_serve_url(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._serve_url_var.get())
        messagebox.showinfo("Copied", "URL copied — paste it into Pi-hole's Adlists page,\nthen run gravity.")

    def load_content_as_source(self, label: str, content: str) -> None:
        """Called by LibraryTab to inject a saved list as an in-memory source."""
        self._sources.append((label, content))
        self._refresh_sources_list()

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
