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
from ..server import ListServer
from ..updater import has_fetchable_sources, update_list as _run_update
from .combine_tab import SaveToLibraryDialog, _credit_for_url
from .tooltip import Tooltip

_log = logging.getLogger(__name__)

# ── UI colors (easy to tweak) ────────────────────────────────────────
_CLR_SELECTED = "gray30"          # selected item background
_CLR_UNSELECTED = "transparent"   # default item background
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
            folder_btn_row, text="Delete", width=70, command=self._delete_folder
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
            list_btn_row, text="Delete", command=self._delete_list
        )
        del_list_btn.grid(row=0, column=1, sticky="ew")
        Tooltip(del_list_btn, "Permanently delete the selected list from the library.")

        self._combine_sel_btn = ctk.CTkButton(
            left, text="Combine Selected", command=self._combine_selected,
            state="disabled",
        )
        self._combine_sel_btn.grid(row=6, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._combine_sel_btn, "Merge 2+ selected lists into a new combined list (Ctrl+click to multi-select).")

        self._update_all_btn = ctk.CTkButton(
            left, text="Update All Lists", command=self._update_all
        )
        self._update_all_btn.grid(row=7, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._update_all_btn, "Re-fetch sources and update every saved list that has URLs.")

        self._refresh_credits_btn = ctk.CTkButton(
            left, text="Refresh Credits", command=self._refresh_credits
        )
        self._refresh_credits_btn.grid(row=8, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._refresh_credits_btn, "Re-extract credit info from source URLs for all saved lists.")

        self._progress_label = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11))
        self._progress_bar = ctk.CTkProgressBar(left)
        # Progress widgets hidden until Update All is running

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
        self._ctx_menu.add_command(label="Copy", command=self._ctx_copy)
        self._ctx_menu.add_command(label="Select All", command=self._ctx_select_all)
        self._content_box.bind("<Button-3>", self._show_ctx_menu)

        stats_row = ctk.CTkFrame(right, fg_color="transparent")
        stats_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._lib_domains_label = ctk.CTkLabel(stats_row, text="Domains: —")
        self._lib_domains_label.pack(side="left", padx=(0, 16))
        self._lib_dupes_label = ctk.CTkLabel(stats_row, text="Duplicates removed: —")
        self._lib_dupes_label.pack(side="left")

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

        self._update_btn = ctk.CTkButton(
            action_row, text="Update", command=self._update_list, state="disabled",
        )
        self._update_btn.pack(side="left")
        Tooltip(self._update_btn, "Re-fetch all sources and update this saved list.")

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

        copy_btn = ctk.CTkButton(move_row, text="Copy", width=70, command=self._copy)
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
                    text_color="gray60",
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
                        text_color="gray60",
                        font=ctk.CTkFont(size=11),
                        height=24,
                    )
                    lbl.pack(fill="x", pady=0)

    def _refresh_lists(self) -> None:
        for w in self._lists_frame.winfo_children():
            w.destroy()

        for item in self._db.get_lists(self._selected_folder_id):
            lid = item["id"]
            btn = ctk.CTkButton(
                self._lists_frame,
                text=item["name"],
                anchor="w",
                fg_color=(
                    _CLR_SELECTED if lid in self._selected_list_ids else _CLR_UNSELECTED
                ),
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
        self._update_list_ui_state(list_id)
        self._update_combine_btn()

    def _toggle_select_list(self, list_id: int) -> None:
        """Ctrl+click: toggle a list in/out of the multi-selection."""
        if list_id in self._selected_list_ids:
            self._selected_list_ids.discard(list_id)
        else:
            self._selected_list_ids.add(list_id)
        self._refresh_lists()
        # Update UI for the primary (first) selected list
        primary = self._selected_list_id
        if primary is not None:
            self._update_list_ui_state(primary)
        self._update_combine_btn()

    def _update_combine_btn(self) -> None:
        """Enable Combine Selected when 2+ lists are selected."""
        state = "normal" if len(self._selected_list_ids) >= 2 else "disabled"
        self._combine_sel_btn.configure(state=state)

    def _update_list_ui_state(self, list_id: int) -> None:
        """Refresh Update button and Host indicator for *list_id*."""
        row = self._db.get_list(list_id)
        if not row:
            return
        sources_json = row.get("sources") or ""
        if has_fetchable_sources(sources_json) and not self._updating:
            self._update_btn.configure(state="normal")
        else:
            self._update_btn.configure(state="disabled")

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

    _DISPLAY_LIMIT = 10_000  # max lines to render in the viewer

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
        if len(lines) > self._DISPLAY_LIMIT:
            display = "\n".join(lines[:self._DISPLAY_LIMIT])
            display += f"\n\n# ... ({len(lines) - self._DISPLAY_LIMIT:,} more lines not shown)"
            display += "\n# Full list preserved — use Copy or Export to get all domains."
        else:
            display = content
        self._content_box.insert("1.0", display)
        self._content_box.configure(state="disabled")
        self._lib_domains_label.configure(text=f"Domains: {row['domain_count']}")
        self._lib_dupes_label.configure(
            text=f"Duplicates removed: {row['duplicates_removed']}"
        )

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

    def _ctx_copy(self) -> None:
        try:
            text = self._content_box.selection_get()
        except _tk.TclError:
            text = self._content_box.get("1.0", "end").strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _ctx_select_all(self) -> None:
        self._content_box.configure(state="normal")
        self._content_box.tag_add("sel", "1.0", "end")
        self._content_box.configure(state="disabled")

    def _copy(self) -> None:
        # Fetch full content from DB (viewer may be truncated)
        if self._selected_list_id is not None:
            row = self._db.get_list(self._selected_list_id)
            text = row["content"] if row else ""
        else:
            text = self._content_box.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", "Copied to clipboard.")

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
        self._update_btn.configure(state=state)
        self._update_all_btn.configure(state=state)

    def _update_list(self) -> None:
        if self._selected_list_id is None or self._updating:
            return
        row = self._db.get_list(self._selected_list_id)
        if not row:
            return
        sources_json = row.get("sources") or ""
        if not has_fetchable_sources(sources_json):
            messagebox.showinfo("No sources", "This list has no URL or file sources to update.")
            return
        lid = self._selected_list_id
        self._set_updating(True)

        def _worker():
            result = _run_update(sources_json, self._list_type_var.get())
            self.after(0, lambda: self._on_update_done(lid, result))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_done(self, list_id: int, result: tuple) -> None:
        content, domain_count, duplicates_removed, failed = result

        if not content:
            self._set_updating(False)
            messagebox.showerror(
                "Update failed",
                "All sources failed to fetch. The saved list was not changed.\n\n"
                + "Failed:\n" + "\n".join(f"  • {s}" for s in failed),
            )
            return

        # List may have been deleted while the update was running
        if not self._db.get_list(list_id):
            self._set_updating(False)
            return

        self._db.update_list(list_id, content, domain_count, duplicates_removed)

        # Auto-refresh hosted content
        if list_id in self._served_paths:
            self._server.add_path(self._served_paths[list_id], content)

        # Refresh viewer if this list is still selected
        if self._selected_list_id == list_id:
            self._select_list(list_id)

        self._set_updating(False)

        if failed:
            messagebox.showwarning(
                "Partial update",
                f"Updated, but {len(failed)} source(s) failed:\n"
                + "\n".join(f"  • {s}" for s in failed),
            )
        else:
            messagebox.showinfo("Updated", f"List updated — {domain_count:,} domains.")

    def _update_all(self) -> None:
        if self._updating:
            return
        all_lists = self._db.get_all_lists()
        updatable = [
            row for row in all_lists
            if has_fetchable_sources(row.get("sources") or "")
        ]
        if not updatable:
            messagebox.showinfo("Nothing to update", "No saved lists have URL or file sources.")
            return
        _log.info("Update All started: %d list(s)", len(updatable))
        self._set_updating(True)
        self._progress_label.grid(row=9, column=0, sticky="ew", padx=10, pady=(4, 0))
        self._progress_bar.grid(row=10, column=0, sticky="ew", padx=10, pady=(2, 8))
        self._progress_bar.set(0)

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
                result = _run_update(sources_json, self._list_type_var.get())
                results.append((lid, name, result))
            self.after(0, lambda: self._on_update_all_done(results))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_all_done(self, results: list) -> None:
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

        _log.info("Update All complete: %d/%d updated", updated, len(results))
        msg = f"Updated {updated}/{len(results)} lists."
        if all_failures:
            msg += "\n\nIssues:\n" + "\n".join(f"  • {f}" for f in all_failures)
            messagebox.showwarning("Update All complete", msg)
        else:
            messagebox.showinfo("Update All complete", msg)

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
        self.clipboard_clear()
        self.clipboard_append(self._lib_serve_url_var.get())
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
        """Re-extract credits from source URLs for all saved lists."""
        all_lists = self._db.get_all_lists()
        refreshed = 0
        skipped = 0

        for row in all_lists:
            sources_json = row.get("sources") or ""
            if not sources_json:
                skipped += 1
                continue

            try:
                sources = json.loads(sources_json)
            except (json.JSONDecodeError, TypeError):
                skipped += 1
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
                skipped += 1
                continue

            # Fetch full content from DB (get_all_lists doesn't select content)
            full_row = self._db.get_list(row["id"])
            if not full_row:
                skipped += 1
                continue
            content = full_row["content"]

            # Check if content already has a non-empty Credits line
            existing = _re.search(r'^# Credits:\s*(.+)$', content, _re.MULTILINE)
            if existing and existing.group(1).strip():
                skipped += 1
                continue

            # Update/insert the Credits line in the header
            credit_line = f"# Credits: {', '.join(credits)}"
            if existing:
                # Replace the empty Credits line
                content = content[:existing.start()] + credit_line + content[existing.end():]
            elif content.startswith("#"):
                # Insert after the last header comment line
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
                # No header — prepend
                content = credit_line + "\n" + content

            self._db.update_list(row["id"], content, full_row["domain_count"], full_row["duplicates_removed"])
            refreshed += 1

        _log.info("Refresh Credits: %d refreshed, %d skipped", refreshed, skipped)
        messagebox.showinfo(
            "Refresh Credits",
            f"Refreshed credits for {refreshed} list(s).\n{skipped} skipped (no URLs or already has credits).",
        )

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
        messagebox.showinfo("Saved", f'"{dialog.result_name}" saved — {stats["unique_domains"]:,} domains.')
