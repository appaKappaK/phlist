"""Library tab: browse folders and saved lists, load back into combiner."""

import json
import logging
import re as _re
import threading
import tkinter as _tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

import customtkinter as ctk

from ..combiner import ListCombiner
from ..database import Database
from ..remote import push_list as _push_list
from ..server import ListServer
from ..updater import has_fetchable_sources, update_list as _run_update
from .combine_tab import SaveToLibraryDialog, _credit_for_url, _DISPLAY_LIMIT
from .tooltip import Tooltip

_log = logging.getLogger(__name__)

# Max lines shown in the library content viewer; matches _DISPLAY_LIMIT in combine_tab.
_LIB_PREVIEW_LIMIT = _DISPLAY_LIMIT

# ── UI colors (easy to tweak) ────────────────────────────────────────
_CLR_SELECTED = ("gray75", "gray30")          # selected item background (light, dark)
_CLR_UNSELECTED = "transparent"               # default item background
_CLR_BTN_TEXT = ("gray10", "#DCE4EE")         # button text: near-black (light), CTk default (dark)
_CLR_HOST_ON = "#27AE60"          # hosting indicator: active
_CLR_HOST_OFF = "#C0392B"         # hosting indicator: inactive
_CLR_BTN_DEFAULT = ["#3B8ED0", "#1F6AA5"]  # default button (light, dark)
_CLR_BTN_DANGER = ["#C0392B", "#922B21"]   # destructive / stop button


def _slugify(name: str) -> str:
    """Convert a list name to a URL-safe path component."""
    slug = name.lower()
    slug = _re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug or "list"


class LibraryTab(ctk.CTkFrame):
    """The Library tab: browse folders and saved lists, load back into combiner."""

    def __init__(self, parent, db: Database, get_combine_tab_cb, switch_to_combine_cb,
                 server: ListServer, list_type_var: ctk.StringVar) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._get_combine_tab = get_combine_tab_cb
        self._switch_to_combine = switch_to_combine_cb
        self._server = server
        self._list_type_var = list_type_var
        self._selected_folder_id: Optional[int] = None  # None = root
        self._selected_list_ids: set[int] = set()  # multi-select (Ctrl+click)
        # list_id → URL path currently being hosted (e.g. "/my-general-list.txt")
        self._served_paths: dict[int, str] = {}
        self._updating = False

        self._build_ui()
        self.refresh()

    @property
    def _selected_list_id(self) -> Optional[int]:
        """Primary selected list (first in selection set). Used by single-action methods."""
        return next(iter(self._selected_list_ids), None)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1, minsize=200)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(0, weight=1)

        # ── Left panel (folders + lists) ────────────────────────────
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left, text="FOLDERS", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

        self._folders_frame = ctk.CTkScrollableFrame(left, height=150)
        self._folders_frame.grid(row=1, column=0, sticky="nsew", padx=10)
        left.rowconfigure(1, weight=1)

        folder_btn_row = ctk.CTkFrame(left, fg_color="transparent")
        folder_btn_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 0))
        new_folder_btn = ctk.CTkButton(
            folder_btn_row, text="+ New Folder", width=100, command=self._new_folder
        )
        new_folder_btn.pack(side="left", padx=(0, 4))
        Tooltip(new_folder_btn, "Create a new folder to organize your saved lists.")

        rename_btn = ctk.CTkButton(
            folder_btn_row, text="Rename", width=80, command=self._rename_folder
        )
        rename_btn.pack(side="left", padx=(0, 4))
        Tooltip(rename_btn, "Rename the selected folder.")

        del_folder_btn = ctk.CTkButton(
            folder_btn_row, text="Delete", width=70, command=self._delete_folder,
            fg_color=_CLR_BTN_DANGER,
        )
        del_folder_btn.pack(side="left")
        Tooltip(del_folder_btn, "Delete the selected folder. Lists inside are moved to Root.")

        ctk.CTkLabel(
            left, text="LISTS", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=3, column=0, sticky="w", padx=10, pady=(12, 4))

        self._lists_frame = ctk.CTkScrollableFrame(left, height=150)
        self._lists_frame.grid(row=4, column=0, sticky="nsew", padx=10)
        left.rowconfigure(4, weight=1)

        list_btn_row = ctk.CTkFrame(left, fg_color="transparent")
        list_btn_row.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 10))
        list_btn_row.columnconfigure(0, weight=1)
        list_btn_row.columnconfigure(1, weight=1)

        rename_list_btn = ctk.CTkButton(
            list_btn_row, text="Rename", command=self._rename_list
        )
        rename_list_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        Tooltip(rename_list_btn, "Rename the selected list.")

        del_list_btn = ctk.CTkButton(
            list_btn_row, text="Delete", command=self._delete_list,
            fg_color=_CLR_BTN_DANGER,
        )
        del_list_btn.grid(row=0, column=1, sticky="ew")
        Tooltip(del_list_btn, "Permanently delete the selected list from the library.")

        self._combine_sel_btn = ctk.CTkButton(
            left, text="Combine Selected", command=self._combine_selected,
            state="disabled",
        )
        self._combine_sel_btn.grid(row=6, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._combine_sel_btn, "Merge 2+ selected lists into a new combined list (Ctrl+click to multi-select).")

        self._refetch_btn = ctk.CTkButton(
            left, text="Re-fetch Sources", command=self._refetch_selected
        )
        self._refetch_btn.grid(row=7, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._refetch_btn, "Re-fetch all sources and rebuild the selected lists with fresh data.")

        self._refresh_credits_btn = ctk.CTkButton(
            left, text="Refresh Credits", command=self._refresh_credits
        )
        self._refresh_credits_btn.grid(row=8, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._refresh_credits_btn, "Re-extract credit info from source URLs for all saved lists.")

        self._progress_label = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11))
        self._progress_bar = ctk.CTkProgressBar(left)
        # Progress widgets hidden until Re-fetch Sources is running

        # ── Right panel (content viewer) ────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right, text="LIST CONTENTS", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))

        self._content_box = ctk.CTkTextbox(right, state="disabled", wrap="none")
        self._content_box.grid(row=1, column=0, sticky="nsew", padx=10)

        # Right-click context menu for the content viewer
        self._ctx_menu = _tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="Copy", command=lambda: self._copy_content(selection_only=True))
        self._ctx_menu.add_command(label="Select All", command=self._ctx_select_all)
        self._content_box.bind("<Button-3>", self._show_ctx_menu)

        stats_row = ctk.CTkFrame(right, fg_color="transparent")
        stats_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._lib_domains_label = ctk.CTkLabel(stats_row, text="Domains: —")
        self._lib_domains_label.pack(side="left", padx=(0, 16))
        self._lib_dupes_label = ctk.CTkLabel(stats_row, text="Duplicates removed: —")
        self._lib_dupes_label.pack(side="left")

        timestamp_row = ctk.CTkFrame(right, fg_color="transparent")
        timestamp_row.grid(row=2, column=0, sticky="e", padx=10, pady=(6, 0))
        self._lib_timestamp_label = ctk.CTkLabel(
            timestamp_row, text="", text_color=("gray15", "gray60"), font=ctk.CTkFont(size=11)
        )
        self._lib_timestamp_label.pack(side="right")

        action_row = ctk.CTkFrame(right, fg_color="transparent")
        action_row.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        open_btn = ctk.CTkButton(action_row, text="Open", command=self._open_list)
        open_btn.pack(side="left", padx=(0, 8))
        Tooltip(open_btn, "Load the selected list's content into the viewer.")

        export_btn = ctk.CTkButton(action_row, text="Export File...", command=self._export)
        export_btn.pack(side="left", padx=(0, 8))
        Tooltip(export_btn, "Export the list as a .txt file to disk.")

        load_btn = ctk.CTkButton(
            action_row,
            text="Load into Combiner",
            command=self._load_into_combiner,
        )
        load_btn.pack(side="left", padx=(0, 8))
        Tooltip(load_btn, "Add this list as a source in the Combine tab to merge with other lists.")

        self._push_btn = ctk.CTkButton(
            action_row, text="Push to Server", command=self._push_to_server, state="disabled",
        )
        self._push_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._push_btn,
                "Upload this list to the configured remote phlist-server via HTTP PUT.")

        # Move + Host row
        move_row = ctk.CTkFrame(right, fg_color="transparent")
        move_row.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkLabel(move_row, text="Move to folder:").pack(side="left", padx=(0, 8))
        self._move_folder_var = ctk.StringVar(value="🏠 Root")
        self._move_menu = ctk.CTkOptionMenu(
            move_row, variable=self._move_folder_var, values=["🏠 Root"], width=160
        )
        self._move_menu.pack(side="left", padx=(0, 8))
        move_btn = ctk.CTkButton(move_row, text="Move", width=70, command=self._move_list)
        move_btn.pack(side="left", padx=(0, 8))
        Tooltip(move_btn, "Move the selected list to a different folder. Doesn't change content.")

        copy_btn = ctk.CTkButton(move_row, text="Copy", width=70, command=self._copy_content)
        copy_btn.pack(side="left", padx=(0, 8))
        Tooltip(copy_btn, "Copy the list contents to the clipboard.")

        self._lib_serve_indicator = ctk.CTkLabel(
            move_row, text="●", text_color=_CLR_HOST_OFF, width=16
        )
        self._lib_serve_indicator.pack(side="left", padx=(0, 4))
        self._lib_serve_btn = ctk.CTkButton(
            move_row, text="Host", width=90, command=self._toggle_lib_serve
        )
        self._lib_serve_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._lib_serve_btn, "Host this list over HTTP so Pi-hole can pull it directly.")

        self._lib_serve_url_var = ctk.StringVar()
        self._lib_serve_url_entry = ctk.CTkEntry(
            move_row, textvariable=self._lib_serve_url_var, width=280, state="disabled",
        )
        self._lib_serve_copy_btn = ctk.CTkButton(
            move_row, text="Copy URL", width=80, command=self._copy_lib_serve_url
        )
        Tooltip(self._lib_serve_copy_btn, "Copy the URL to add on Pi-hole's Lists tab.")
        # URL entry + copy button hidden until a list is being hosted

    # ── Refresh helpers ──────────────────────────────────────────────

    def refresh(self) -> None:
        self._refresh_folders()
        self._refresh_lists()
        self._refresh_move_menu()

    def _refresh_folders(self) -> None:
        for w in self._folders_frame.winfo_children():
            w.destroy()

        # Virtual root entry (unfiled lists, not a real DB folder)
        root_btn = ctk.CTkButton(
            self._folders_frame,
            text="🏠 Root",
            anchor="w",
            fg_color=(
                _CLR_SELECTED if self._selected_folder_id is None else _CLR_UNSELECTED
            ),
            text_color=_CLR_BTN_TEXT,
            command=lambda: self._select_folder(None),
        )
        root_btn.pack(fill="x", pady=1)

        # Show list names nested under Root only when Root is selected
        if self._selected_folder_id is None:
            for item in self._db.get_lists(folder_id=None):
                lbl = ctk.CTkLabel(
                    self._folders_frame,
                    text=f"    {item['name']}",
                    anchor="w",
                    text_color=("gray15", "gray60"),
                    font=ctk.CTkFont(size=11),
                    height=24,
                )
                lbl.pack(fill="x", pady=0)

        for folder in self._db.get_folders():
            fid = folder["id"]
            is_selected = self._selected_folder_id == fid
            arrow = "▼" if is_selected else "▶"
            btn = ctk.CTkButton(
                self._folders_frame,
                text=f"{arrow} 📁 {folder['name']}",
                anchor="w",
                fg_color=(
                    _CLR_SELECTED if is_selected else _CLR_UNSELECTED
                ),
                text_color=_CLR_BTN_TEXT,
                command=lambda f=fid: self._select_folder(f),
            )
            btn.pack(fill="x", pady=1)

            # Show nested list names only when this folder is selected
            if is_selected:
                for item in self._db.get_lists(folder_id=fid):
                    lbl = ctk.CTkLabel(
                        self._folders_frame,
                        text=f"    {item['name']}",
                        anchor="w",
                        text_color=("gray15", "gray60"),
                        font=ctk.CTkFont(size=11),
                        height=24,
                    )
                    lbl.pack(fill="x", pady=0)

    @staticmethod
    def _fmt_date(iso_str: str, short: bool = False) -> str:
        """Format an ISO timestamp into MM/DD/YY or MM/DD/YY hh:mm AM/PM."""
        if not iso_str:
            return ""
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(iso_str)
            if short:
                return dt.strftime("%-m/%d/%y")
            return dt.strftime("%-m/%d/%y %-I:%M %p")
        except Exception:
            return iso_str

    def _refresh_lists(self) -> None:
        for w in self._lists_frame.winfo_children():
            w.destroy()

        for item in self._db.get_lists(self._selected_folder_id):
            lid = item["id"]
            date_str = self._fmt_date(item.get("updated_at") or item.get("created_at", ""))
            label = f"{item['name']}  ({date_str})" if date_str else item["name"]
            btn = ctk.CTkButton(
                self._lists_frame,
                text=label,
                anchor="w",
                fg_color=(
                    _CLR_SELECTED if lid in self._selected_list_ids else _CLR_UNSELECTED
                ),
                text_color=_CLR_BTN_TEXT,
                command=lambda i=lid: self._select_list(i),
            )
            # Ctrl+click for multi-select
            btn.bind("<Control-Button-1>", lambda e, i=lid: self._toggle_select_list(i))
            btn.pack(fill="x", pady=1)

    def _refresh_move_menu(self) -> None:
        folders = self._db.get_folders()
        names = ["🏠 Root"] + [f["name"] for f in folders]
        self._move_folder_map = {"🏠 Root": None, **{f["name"]: f["id"] for f in folders}}
        self._move_menu.configure(values=names)

    # ── Folder actions ───────────────────────────────────────────────

    def _select_folder(self, folder_id: Optional[int]) -> None:
        self._selected_folder_id = folder_id
        self._selected_list_ids.clear()
        self._refresh_folders()
        self._refresh_lists()
        self._update_combine_btn()


    def _new_folder(self) -> None:
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if name and name.strip():
            if name.strip().lower() == "root":
                messagebox.showwarning("Reserved name", '"Root" is reserved — choose a different name.', parent=self)
                return
            self._db.create_folder(name.strip())
            self.refresh()

    def _rename_folder(self) -> None:
        if self._selected_folder_id is None:
            messagebox.showinfo("Select a folder", "Select a folder to rename.")
            return
        new_name = simpledialog.askstring("Rename Folder", "New name:", parent=self)
        if new_name and new_name.strip():
            if new_name.strip().lower() == "root":
                messagebox.showwarning("Reserved name", '"Root" is reserved — choose a different name.', parent=self)
                return
            self._db.rename_folder(self._selected_folder_id, new_name.strip())
            self.refresh()

    def _delete_folder(self) -> None:
        if self._selected_folder_id is None:
            messagebox.showinfo("Select a folder", 'Select a folder to delete.\n\n"🏠 Root" is the default location and cannot be deleted.')
            return
        if messagebox.askyesno(
            "Delete folder",
            "Delete this folder? Lists inside will be moved to 🏠 Root.",
            parent=self,
        ):
            self._db.delete_folder(self._selected_folder_id)
            self._selected_folder_id = None
            self.refresh()

    # ── List actions ─────────────────────────────────────────────────

    def _select_list(self, list_id: int) -> None:
        """Single-click: select one list (clears others). Does NOT load content."""
        self._selected_list_ids = {list_id}
        self._refresh_lists()
        self._sync_host_indicator(list_id)
        self._update_combine_btn()
        remote_url = self._db.get_setting("remote_server_url", "")
        self._push_btn.configure(state="normal" if remote_url else "disabled")

    def _toggle_select_list(self, list_id: int) -> None:
        """Ctrl+click: toggle a list in/out of the multi-selection."""
        if list_id in self._selected_list_ids:
            self._selected_list_ids.discard(list_id)
        else:
            self._selected_list_ids.add(list_id)
        self._refresh_lists()
        primary = self._selected_list_id
        if primary is not None:
            self._sync_host_indicator(primary)
        self._update_combine_btn()

    def _update_combine_btn(self) -> None:
        """Enable Combine Selected when 2+ lists are selected."""
        state = "normal" if len(self._selected_list_ids) >= 2 else "disabled"
        self._combine_sel_btn.configure(state=state)

    def _sync_host_indicator(self, list_id: int) -> None:
        """Update Host indicator for *list_id*."""
        if list_id in self._served_paths:
            self._lib_serve_indicator.configure(text_color=_CLR_HOST_ON)
            self._lib_serve_btn.configure(text="Stop Hosting", fg_color=_CLR_BTN_DANGER)
            self._lib_serve_url_var.set(self._server.url_for(self._served_paths[list_id]))
            self._lib_serve_url_entry.pack(side="left", padx=(0, 8))
            self._lib_serve_copy_btn.pack(side="left")
        else:
            self._lib_serve_indicator.configure(text_color=_CLR_HOST_OFF)
            self._lib_serve_btn.configure(text="Host", fg_color=_CLR_BTN_DEFAULT)
            self._lib_serve_url_entry.pack_forget()
            self._lib_serve_copy_btn.pack_forget()

    def _open_list(self) -> None:
        """Load the selected list's content into the viewer."""
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list first, then click Open.")
            return
        row = self._db.get_list(self._selected_list_id)
        if not row:
            return
        self._content_box.configure(state="normal")
        self._content_box.delete("1.0", "end")
        content = row["content"]
        lines = content.split("\n")
        if len(lines) > _LIB_PREVIEW_LIMIT:
            display = "\n".join(lines[:_LIB_PREVIEW_LIMIT])
            display += f"\n\n# ... ({len(lines) - _LIB_PREVIEW_LIMIT:,} more lines not shown)"
            display += "\n# Full list preserved — use Copy or Export to get all domains."
        else:
            display = content
        self._content_box.insert("1.0", display)
        self._content_box.configure(state="disabled")
        self._lib_domains_label.configure(text=f"Domains: {row['domain_count']}")
        self._lib_dupes_label.configure(
            text=f"Duplicates removed: {row['duplicates_removed']}"
        )
        created = self._fmt_date(row.get("created_at", ""))
        updated = self._fmt_date(row.get("updated_at", ""))
        if updated:
            self._lib_timestamp_label.configure(text=f"Created: {created}  |  Updated: {updated}")
        elif created:
            self._lib_timestamp_label.configure(text=f"Created: {created}")
        else:
            self._lib_timestamp_label.configure(text="")

    def _rename_list(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to rename.")
            return
        new_name = simpledialog.askstring("Rename List", "New name:", parent=self)
        if new_name and new_name.strip():
            self._db.rename_list(self._selected_list_id, new_name.strip())
            self._refresh_lists()

    def _delete_list(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to delete.")
            return
        if messagebox.askyesno("Delete list", "Delete this list?", parent=self):
            lid = self._selected_list_id
            # Stop hosting this list if it's active
            if lid in self._served_paths:
                self._server.remove_path(self._served_paths.pop(lid))
            self._db.delete_list(lid)
            self._selected_list_ids.discard(lid)
            self._content_box.configure(state="normal")
            self._content_box.delete("1.0", "end")
            self._content_box.configure(state="disabled")
            self._lib_domains_label.configure(text="Domains: —")
            self._lib_dupes_label.configure(text="Duplicates removed: —")
            self._refresh_lists()
            self._update_combine_btn()

    def _show_ctx_menu(self, event) -> None:
        self._ctx_menu.tk_popup(event.x_root, event.y_root)

    def _copy_content(self, *, selection_only: bool = False) -> None:
        """Copy text to clipboard. When *selection_only* is True (context menu),
        copies only the highlighted selection; otherwise fetches full content
        from the DB (the viewer may be truncated for large lists).
        """
        text = ""
        if selection_only:
            try:
                text = self._content_box.selection_get()
            except _tk.TclError:
                pass  # no selection — fall through to full content
        if not text:
            if self._selected_list_id is not None:
                row = self._db.get_list(self._selected_list_id)
                text = row["content"] if row else ""
            else:
                text = self._content_box.get("1.0", "end").strip()
        if not text:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            messagebox.showerror("Clipboard error", "Could not copy to clipboard.")
            return
        messagebox.showinfo("Copied", "Copied to clipboard.")

    def _ctx_select_all(self) -> None:
        self._content_box.configure(state="normal")
        self._content_box.tag_add("sel", "1.0", "end")
        self._content_box.configure(state="disabled")

    def _export(self) -> None:
        # Fetch full content from DB (viewer may be truncated)
        if self._selected_list_id is not None:
            row = self._db.get_list(self._selected_list_id)
            text = row["content"] if row else ""
        else:
            text = self._content_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Nothing to export", "Select a list first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            Path(path).write_text(text, encoding="utf-8")
            messagebox.showinfo("Exported", f"Saved to {path}")

    def _push_to_server(self) -> None:
        if self._selected_list_id is None:
            messagebox.showwarning("No list selected", "Select a list first.")
            return
        url = self._db.get_setting("remote_server_url", "").rstrip("/")
        key = self._db.get_setting("remote_server_key", "")
        if not url:
            messagebox.showwarning(
                "No server configured",
                "Enter a server URL in Settings → REMOTE SERVER first.",
            )
            return
        row = self._db.get_list(self._selected_list_id)
        if not row or not row.get("content"):
            messagebox.showwarning("Empty list", "This list has no content to push.")
            return
        slug = _slugify(row["name"])
        content = row["content"]

        self._push_btn.configure(state="disabled", text="Pushing…")

        def _worker():
            ok, msg = _push_list(url, key, slug, content)
            def _done():
                self._push_btn.configure(state="normal", text="Push to Server")
                if ok:
                    messagebox.showinfo("Pushed", f"{row['name']} → {url}/lists/{slug}.txt")
                else:
                    messagebox.showerror("Push failed", msg)
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _load_into_combiner(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to load.")
            return
        row = self._db.get_list(self._selected_list_id)
        if not row:
            return
        combine_tab = self._get_combine_tab()
        sources_json = row.get("sources") or ""
        if sources_json:
            combine_tab.load_sources_from_library(
                row["name"], json.loads(sources_json), row["content"]
            )
        else:
            combine_tab.load_content_as_source(f"[library] {row['name']}", row["content"])
        self._switch_to_combine()

    # ── Update from sources ────────────────────────────────────────

    def _set_updating(self, active: bool) -> None:
        self._updating = active
        state = "disabled" if active else "normal"
        self._refetch_btn.configure(state=state)

    def _refetch_selected(self) -> None:
        if self._updating:
            return
        if not self._selected_list_ids:
            messagebox.showinfo("Select lists", "Select one or more lists first.")
            return
        rows = [self._db.get_list(lid) for lid in self._selected_list_ids]
        rows = [r for r in rows if r]
        updatable = [row for row in rows if has_fetchable_sources(row.get("sources") or "")]
        if not updatable:
            messagebox.showinfo("Nothing to update", "The selected lists have no URL or file sources.")
            return
        _log.info("Re-fetch started: %d list(s)", len(updatable))
        self._set_updating(True)
        self._progress_label.grid(row=9, column=0, sticky="ew", padx=10, pady=(4, 0))
        self._progress_bar.grid(row=10, column=0, sticky="ew", padx=10, pady=(2, 8))
        self._progress_bar.set(0)

        timeout = int(self._db.get_setting("fetch_timeout", "30"))

        def _worker():
            results = []
            for i, row in enumerate(updatable):
                lid = row["id"]
                name = row["name"]
                self.after(0, lambda i=i, n=name: (
                    self._progress_label.configure(text=f"[{i + 1}/{len(updatable)}] Updating \"{n}\"..."),
                    self._progress_bar.set((i + 1) / len(updatable)),
                ))
                sources_json = row.get("sources") or ""
                result = _run_update(sources_json, self._list_type_var.get(), timeout=timeout)
                results.append((lid, name, result))
            self.after(0, lambda: self._on_refetch_done(results))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_refetch_done(self, results: list) -> None:
        self._progress_label.grid_forget()
        self._progress_bar.grid_forget()
        self._set_updating(False)

        updated = 0
        all_failures = []
        for lid, name, (content, domain_count, duplicates_removed, failed) in results:
            if content and self._db.get_list(lid):
                self._db.update_list(lid, content, domain_count, duplicates_removed)
                if lid in self._served_paths:
                    self._server.add_path(self._served_paths[lid], content)
                updated += 1
                if failed:
                    all_failures.append(f"{name}: {', '.join(failed)}")
            else:
                all_failures.append(f"{name}: all sources failed")

        # Refresh viewer if current list was among those updated
        if self._selected_list_id is not None:
            self._select_list(self._selected_list_id)

        _log.info("Re-fetch complete: %d/%d updated", updated, len(results))
        msg = f"Updated {updated}/{len(results)} lists."
        if all_failures:
            msg += "\n\nIssues:\n" + "\n".join(f"  • {f}" for f in all_failures)
            messagebox.showwarning("Re-fetch complete", msg)
        else:
            messagebox.showinfo("Re-fetch complete", msg)

    # ── Host from Library ──────────────────────────────────────────

    def _make_path(self, list_id: int, name: str) -> str:
        """Return a unique ``/slug.txt`` path for *list_id*, avoiding collisions."""
        base = _slugify(name)
        candidate = f"/{base}.txt"
        for lid, p in self._served_paths.items():
            if p == candidate and lid != list_id:
                candidate = f"/{base}-{list_id}.txt"
                break
        return candidate

    def _toggle_lib_serve(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to host.")
            return
        lid = self._selected_list_id
        if lid in self._served_paths:
            # Stop hosting this list
            self._server.remove_path(self._served_paths.pop(lid))
            self._lib_serve_indicator.configure(text_color=_CLR_HOST_OFF)
            self._lib_serve_btn.configure(text="Host", fg_color=_CLR_BTN_DEFAULT)
            self._lib_serve_url_entry.pack_forget()
            self._lib_serve_copy_btn.pack_forget()
        else:
            row = self._db.get_list(lid)
            if not row:
                return
            path = self._make_path(lid, row["name"])
            try:
                url = self._server.add_path(path, row["content"])
            except OSError as exc:
                messagebox.showerror("Server error", f"Could not start server:\n{exc}")
                return
            self._served_paths[lid] = path
            self._lib_serve_url_var.set(url)
            self._lib_serve_url_entry.pack(side="left", padx=(0, 8))
            self._lib_serve_copy_btn.pack(side="left")
            self._lib_serve_indicator.configure(text_color=_CLR_HOST_ON)
            self._lib_serve_btn.configure(text="Stop Hosting", fg_color=_CLR_BTN_DANGER)

    def _copy_lib_serve_url(self) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(self._lib_serve_url_var.get())
        except Exception:
            messagebox.showerror("Clipboard error", "Could not copy to clipboard.")
            return
        messagebox.showinfo("Copied", "URL copied — add it on Pi-hole's Lists tab,\nthen run gravity.")

    def _move_list(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to move.")
            return
        folder_name = self._move_folder_var.get()
        folder_id = self._move_folder_map.get(folder_name)
        self._db.move_list(self._selected_list_id, folder_id)
        self._refresh_lists()
        messagebox.showinfo("Moved", f"List moved to {folder_name}.")

    # ── Refresh Credits ────────────────────────────────────────────────

    def _refresh_credits(self) -> None:
        """Re-extract credits from source URLs for selected lists."""
        if not self._selected_list_ids:
            messagebox.showinfo("Select lists", "Select one or more lists first.")
            return
        rows = [self._db.get_list(lid) for lid in self._selected_list_ids]
        rows = [r for r in rows if r]
        updated = 0       # credits written/updated
        already_had = 0   # already had credits — nothing to do
        no_sources = 0    # paste-only list, no URLs to extract from
        no_credits = 0    # had URLs but couldn't extract any credit names

        for row in rows:
            sources_json = row.get("sources") or ""
            if not sources_json:
                no_sources += 1
                continue

            try:
                sources = json.loads(sources_json)
            except (json.JSONDecodeError, TypeError):
                no_sources += 1
                continue

            # Extract credits from URLs
            credits: list[str] = []
            for src in sources:
                label = src.get("label", "")
                if label.startswith(("http://", "https://")):
                    credit = _credit_for_url(label, label)
                    if credit and credit not in credits:
                        credits.append(credit)

            if not credits:
                no_credits += 1
                continue

            content = row["content"]

            # Check if content already has a non-empty Credits line
            existing = _re.search(r'^# Credits:\s*(.+)$', content, _re.MULTILINE)
            if existing and existing.group(1).strip():
                already_had += 1
                continue

            # Update/insert the Credits line in the header
            credit_line = f"# Credits: {', '.join(credits)}"
            if existing:
                content = content[:existing.start()] + credit_line + content[existing.end():]
            elif content.startswith("#"):
                lines = content.split("\n")
                insert_idx = 0
                for i, line in enumerate(lines):
                    if line.startswith("#"):
                        insert_idx = i + 1
                    else:
                        break
                lines.insert(insert_idx, credit_line)
                content = "\n".join(lines)
            else:
                content = credit_line + "\n" + content

            self._db.update_list(row["id"], content, row["domain_count"], row["duplicates_removed"])
            updated += 1

        _log.info("Refresh Credits: %d updated, %d already had, %d no sources, %d no credits found",
                  updated, already_had, no_sources, no_credits)

        parts = []
        if updated:
            parts.append(f"✓  {updated} updated")
        if already_had:
            parts.append(f"-  {already_had} already had credits")
        if no_credits:
            parts.append(f"✗  {no_credits} couldn't extract credits from URLs")
        if no_sources:
            parts.append(f"·  {no_sources} paste-only (no URLs to read from)")

        messagebox.showinfo("Refresh Credits", "\n".join(parts) if parts else "No lists found.")

    # ── Combine Selected ──────────────────────────────────────────────

    def _combine_selected(self) -> None:
        """Merge 2+ selected lists into a new deduplicated list."""
        if len(self._selected_list_ids) < 2:
            messagebox.showinfo("Select lists", "Ctrl+click to select 2 or more lists to combine.")
            return

        combiner = ListCombiner()
        all_sources: list[dict] = []
        credits: list[str] = []

        for lid in self._selected_list_ids:
            row = self._db.get_list(lid)
            if not row:
                continue
            combiner.add_list(row["content"], row["name"])

            # Collect sources from each input list
            sources_json = row.get("sources") or ""
            if sources_json:
                try:
                    sources = json.loads(sources_json)
                    all_sources.extend(sources)
                    # Extract credits from source URLs
                    for src in sources:
                        label = src.get("label", "")
                        if label.startswith(("http://", "https://")):
                            credit = _credit_for_url(label, label)
                            if credit and credit not in credits:
                                credits.append(credit)
                except (json.JSONDecodeError, TypeError):
                    pass

        stats = combiner.get_stats()
        if stats["unique_domains"] == 0:
            messagebox.showinfo("No domains", "The selected lists contain no domains.")
            return

        result = combiner.get_combined(
            list_type=self._list_type_var.get(),
            credits=credits or None,
        )

        # Open save dialog
        dialog = SaveToLibraryDialog(self, self._db)
        self.wait_window(dialog)
        if not dialog.result_name:
            return

        # Deduplicate merged sources
        seen: set[str] = set()
        unique_sources: list[dict] = []
        for src in all_sources:
            key = src.get("label", "").lower().rstrip("/")
            if key not in seen:
                seen.add(key)
                unique_sources.append(src)

        sources_json = json.dumps(unique_sources) if unique_sources else ""
        self._db.save_list(
            name=dialog.result_name,
            content=result,
            domain_count=stats["unique_domains"],
            duplicates_removed=stats["duplicates_removed"],
            folder_id=dialog.result_folder_id,
            sources=sources_json,
        )
        _log.info("Combined %d lists into '%s': %d domains",
                   len(self._selected_list_ids), dialog.result_name, stats["unique_domains"])
        self.refresh()
        self._get_combine_tab().load_library_result(
            dialog.result_name, unique_sources, result, stats,
        )
        self._switch_to_combine()
