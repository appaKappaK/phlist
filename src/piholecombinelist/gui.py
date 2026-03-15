"""Desktop GUI for Pi-hole Combined Blocklist Generator."""
# v1.0.0

import threading
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

import customtkinter as ctk

from . import __version__
from .combiner import ListCombiner
from .database import Database
from .fetcher import ListFetcher

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class SaveToLibraryDialog(ctk.CTkToplevel):
    """Modal dialog: enter a name and choose a folder before saving to the library."""

    def __init__(self, parent, db: Database) -> None:
        super().__init__(parent)
        self.title("Save to Library")
        self.geometry("360x200")
        self.resizable(False, False)
        self.grab_set()

        self.result_name: Optional[str] = None
        self.result_folder_id: Optional[int] = None

        ctk.CTkLabel(self, text="List name:").pack(padx=20, pady=(20, 4), anchor="w")
        self._name_entry = ctk.CTkEntry(self, width=320)
        self._name_entry.pack(padx=20)

        ctk.CTkLabel(self, text="Folder:").pack(padx=20, pady=(12, 4), anchor="w")
        folders = db.get_folders()
        self._folder_map = {f["name"]: f["id"] for f in folders}
        folder_names = ["Root"] + list(self._folder_map.keys())
        self._folder_var = ctk.StringVar(value="Root")
        self._folder_menu = ctk.CTkOptionMenu(
            self, variable=self._folder_var, values=folder_names, width=320
        )
        self._folder_menu.pack(padx=20)

        ctk.CTkButton(self, text="Save", command=self._on_save, width=320).pack(
            padx=20, pady=16
        )

    def _on_save(self) -> None:
        name = self._name_entry.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please enter a list name.", parent=self)
            return
        self.result_name = name
        chosen = self._folder_var.get()
        self.result_folder_id = self._folder_map.get(chosen)  # None = root
        self.destroy()


class CombineTab(ctk.CTkFrame):
    """The Combine tab: add sources, combine, view/copy/save output."""

    def __init__(self, parent, db: Database, switch_to_library_cb) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._switch_to_library = switch_to_library_cb

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
        left.rowconfigure(5, weight=1)
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
        ctk.CTkButton(url_row, text="+", width=36, command=self._add_url).grid(
            row=0, column=1
        )

        # Browse file button
        ctk.CTkButton(
            left, text="Browse File...", command=self._browse_file, anchor="w"
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 0))

        # Paste area
        ctk.CTkLabel(left, text="Paste raw blocklist text:").grid(
            row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 2)
        )
        self._paste_box = ctk.CTkTextbox(left, height=120)
        self._paste_box.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10)
        ctk.CTkButton(
            left, text="Add Pasted Text", command=self._add_pasted
        ).grid(row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(6, 0))

        # Sources list
        ctk.CTkLabel(left, text="Sources added:").grid(
            row=6, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 2)
        )
        self._sources_frame = ctk.CTkScrollableFrame(left, height=130)
        self._sources_frame.grid(
            row=7, column=0, columnspan=2, sticky="nsew", padx=10
        )
        left.rowconfigure(7, weight=1)

        ctk.CTkButton(
            left,
            text="COMBINE ALL",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._combine,
        ).grid(row=8, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

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
        btn_row.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkButton(btn_row, text="Copy to Clipboard", command=self._copy).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(btn_row, text="Save File...", command=self._save_file).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            btn_row, text="Save to Library", command=self._save_to_library
        ).pack(side="left")

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
        text = self._paste_box.get("1.0", "end").strip()
        if not text:
            return
        label = f"[pasted #{len(self._sources) + 1}]"
        self._sources.append((label, text))
        self._paste_box.delete("1.0", "end")
        self._refresh_sources_list()

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
        # Run in a thread so the UI stays responsive during URL fetches
        threading.Thread(target=self._run_combine, daemon=True).start()

    def _run_combine(self) -> None:
        fetcher = ListFetcher()
        combiner = ListCombiner()

        for label, content in self._sources:
            if content is not None:
                # In-memory pasted text
                combiner.add_list(content, label)
            else:
                fetched = fetcher.fetch(label)
                if fetched:
                    combiner.add_list(fetched, label)

        result = combiner.get_combined()
        stats = combiner.get_stats()

        # Store for Save to Library
        self._last_result = result
        self._last_stats = stats

        # Update UI on main thread
        self.after(0, lambda: self._update_output(result, stats))

    def _update_output(self, result: str, stats: dict) -> None:
        self._output_box.configure(state="normal")
        self._output_box.delete("1.0", "end")
        self._output_box.insert("1.0", result)
        self._output_box.configure(state="disabled")
        self._domains_label.configure(text=f"Domains: {stats['unique_domains']}")
        self._dupes_label.configure(
            text=f"Duplicates removed: {stats['duplicates_removed']}"
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
        if not hasattr(self, "_last_result") or not self._last_result:
            messagebox.showwarning("Nothing to save", "Combine sources first.")
            return
        dialog = SaveToLibraryDialog(self, self._db)
        self.wait_window(dialog)
        if dialog.result_name:
            self._db.save_list(
                name=dialog.result_name,
                content=self._last_result,
                domain_count=self._last_stats["unique_domains"],
                duplicates_removed=self._last_stats["duplicates_removed"],
                folder_id=dialog.result_folder_id,
            )
            messagebox.showinfo("Saved", f'"{dialog.result_name}" saved to library.')
            self._switch_to_library()

    def load_content_as_source(self, label: str, content: str) -> None:
        """Called by LibraryTab to inject a saved list as an in-memory source."""
        self._sources.append((label, content))
        self._refresh_sources_list()


class LibraryTab(ctk.CTkFrame):
    """The Library tab: browse folders and saved lists, load back into combiner."""

    def __init__(self, parent, db: Database, get_combine_tab_cb) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._get_combine_tab = get_combine_tab_cb
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
        self._move_folder_var = ctk.StringVar(value="Root")
        self._move_menu = ctk.CTkOptionMenu(
            move_row, variable=self._move_folder_var, values=["Root"], width=160
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

        # Root entry
        root_btn = ctk.CTkButton(
            self._folders_frame,
            text="📁 Root",
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
        names = ["Root"] + [f["name"] for f in folders]
        self._move_folder_map = {"Root": None, **{f["name"]: f["id"] for f in folders}}
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
            self._db.create_folder(name.strip())
            self.refresh()

    def _rename_folder(self) -> None:
        if self._selected_folder_id is None:
            messagebox.showinfo("Select a folder", "Select a folder to rename.")
            return
        new_name = simpledialog.askstring("Rename Folder", "New name:", parent=self)
        if new_name and new_name.strip():
            self._db.rename_folder(self._selected_folder_id, new_name.strip())
            self.refresh()

    def _delete_folder(self) -> None:
        if self._selected_folder_id is None:
            messagebox.showinfo("Select a folder", "Select a folder to delete.")
            return
        if messagebox.askyesno(
            "Delete folder",
            "Delete this folder? Lists inside will be moved to Root.",
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
        combine_tab.load_content_as_source(
            f"[library] {row['name']}", row["content"]
        )
        # Switch to Combine tab
        self.master.set("Combine")

    def _move_list(self) -> None:
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list to move.")
            return
        folder_name = self._move_folder_var.get()
        folder_id = self._move_folder_map.get(folder_name)
        self._db.move_list(self._selected_list_id, folder_id)
        self._refresh_lists()
        messagebox.showinfo("Moved", f"List moved to {folder_name}.")


class App(ctk.CTk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title(f"Pi-hole Combined Blocklist Generator  v{__version__}")
        self.geometry("1000x680")
        self.minsize(800, 560)

        self._db = Database()

        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self._tabs.add("Combine")
        self._tabs.add("Library")

        self._combine_tab = CombineTab(
            self._tabs.tab("Combine"),
            self._db,
            switch_to_library_cb=lambda: self._tabs.set("Library"),
        )
        self._combine_tab.pack(fill="both", expand=True)

        self._library_tab = LibraryTab(
            self._tabs.tab("Library"),
            self._db,
            get_combine_tab_cb=lambda: self._combine_tab,
        )
        self._library_tab.pack(fill="both", expand=True)

        # Refresh library whenever the tab is selected
        self._tabs._segmented_button.configure(
            command=lambda tab: self._library_tab.refresh() if tab == "Library" else None
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._db.close()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
