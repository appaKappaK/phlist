"""Library tab: browse folders and saved lists, load back into combiner."""

import json
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

import customtkinter as ctk

from ..database import Database


class LibraryTab(ctk.CTkFrame):
    """The Library tab: browse folders and saved lists, load back into combiner."""

    def __init__(self, parent, db: Database, get_combine_tab_cb, switch_to_combine_cb) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._get_combine_tab = get_combine_tab_cb
        self._switch_to_combine = switch_to_combine_cb
        self._selected_folder_id: Optional[int] = None  # None = root
        self._selected_list_id: Optional[int] = None

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1, minsize=200)
        self.columnconfigure(1, weight=3)
        self.rowconfigure(0, weight=1)

        # ── Left panel (folders + lists) ────────────────────────────
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.rowconfigure(2, weight=1)
        left.rowconfigure(4, weight=1)
        left.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left, text="FOLDERS", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

        self._folders_frame = ctk.CTkScrollableFrame(left, height=150)
        self._folders_frame.grid(row=1, column=0, sticky="nsew", padx=10)
        left.rowconfigure(1, weight=1)

        folder_btn_row = ctk.CTkFrame(left, fg_color="transparent")
        folder_btn_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 0))
        ctk.CTkButton(
            folder_btn_row, text="+ New Folder", width=100, command=self._new_folder
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            folder_btn_row, text="Rename", width=80, command=self._rename_folder
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            folder_btn_row, text="Delete", width=70, command=self._delete_folder
        ).pack(side="left")

        ctk.CTkLabel(
            left, text="LISTS", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=3, column=0, sticky="w", padx=10, pady=(12, 4))

        self._lists_frame = ctk.CTkScrollableFrame(left, height=150)
        self._lists_frame.grid(row=4, column=0, sticky="nsew", padx=10)
        left.rowconfigure(4, weight=1)

        ctk.CTkButton(
            left, text="Delete Selected List", command=self._delete_list
        ).grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 10))

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

        stats_row = ctk.CTkFrame(right, fg_color="transparent")
        stats_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 0))
        self._lib_domains_label = ctk.CTkLabel(stats_row, text="Domains: —")
        self._lib_domains_label.pack(side="left", padx=(0, 16))
        self._lib_dupes_label = ctk.CTkLabel(stats_row, text="Duplicates removed: —")
        self._lib_dupes_label.pack(side="left")

        action_row = ctk.CTkFrame(right, fg_color="transparent")
        action_row.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkButton(action_row, text="Copy", command=self._copy).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(action_row, text="Export File...", command=self._export).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            action_row,
            text="Load into Combiner",
            command=self._load_into_combiner,
        ).pack(side="left")

        # Move-to row
        move_row = ctk.CTkFrame(right, fg_color="transparent")
        move_row.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        ctk.CTkLabel(move_row, text="Move to folder:").pack(side="left", padx=(0, 8))
        self._move_folder_var = ctk.StringVar(value="🏠 Root")
        self._move_menu = ctk.CTkOptionMenu(
            move_row, variable=self._move_folder_var, values=["🏠 Root"], width=160
        )
        self._move_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(move_row, text="Move", width=70, command=self._move_list).pack(
            side="left"
        )

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
                "gray30" if self._selected_folder_id is None else "transparent"
            ),
            command=lambda: self._select_folder(None),
        )
        root_btn.pack(fill="x", pady=1)

        for folder in self._db.get_folders():
            fid = folder["id"]
            btn = ctk.CTkButton(
                self._folders_frame,
                text=f"📁 {folder['name']}",
                anchor="w",
                fg_color=(
                    "gray30" if self._selected_folder_id == fid else "transparent"
                ),
                command=lambda f=fid: self._select_folder(f),
            )
            btn.pack(fill="x", pady=1)

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
                    "gray30" if self._selected_list_id == lid else "transparent"
                ),
                command=lambda i=lid: self._select_list(i),
            )
            btn.pack(fill="x", pady=1)

    def _refresh_move_menu(self) -> None:
        folders = self._db.get_folders()
        names = ["🏠 Root"] + [f["name"] for f in folders]
        self._move_folder_map = {"🏠 Root": None, **{f["name"]: f["id"] for f in folders}}
        self._move_menu.configure(values=names)

    # ── Folder actions ───────────────────────────────────────────────

    def _select_folder(self, folder_id: Optional[int]) -> None:
        self._selected_folder_id = folder_id
        self._selected_list_id = None
        self._refresh_folders()
        self._refresh_lists()

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
        self._selected_list_id = list_id
        self._refresh_lists()
        row = self._db.get_list(list_id)
        if not row:
            return
        self._content_box.configure(state="normal")
        self._content_box.delete("1.0", "end")
        self._content_box.insert("1.0", row["content"])
        self._content_box.configure(state="disabled")
        self._lib_domains_label.configure(text=f"Domains: {row['domain_count']}")
        self._lib_dupes_label.configure(
            text=f"Duplicates removed: {row['duplicates_removed']}"
        )

    def _delete_list(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to delete.")
            return
        if messagebox.askyesno("Delete list", "Delete this list?", parent=self):
            self._db.delete_list(self._selected_list_id)
            self._selected_list_id = None
            self._content_box.configure(state="normal")
            self._content_box.delete("1.0", "end")
            self._content_box.configure(state="disabled")
            self._lib_domains_label.configure(text="Domains: —")
            self._lib_dupes_label.configure(text="Duplicates removed: —")
            self._refresh_lists()

    def _copy(self) -> None:
        text = self._content_box.get("1.0", "end").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("Copied", "Copied to clipboard.")

    def _export(self) -> None:
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

    def _move_list(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to move.")
            return
        folder_name = self._move_folder_var.get()
        folder_id = self._move_folder_map.get(folder_name)
        self._db.move_list(self._selected_list_id, folder_id)
        self._refresh_lists()
        messagebox.showinfo("Moved", f"List moved to {folder_name}.")
