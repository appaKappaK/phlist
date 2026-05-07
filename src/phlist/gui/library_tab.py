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
from ..updater import has_fetchable_sources, update_list as _run_update
from .combine_tab import SaveToLibraryDialog, _credit_for_url, _DISPLAY_LIMIT
from .ctk_helpers import get_canvas, get_inner_window_id, get_scrollbar, get_underlying_textbox
from .tooltip import Tooltip

_log = logging.getLogger(__name__)

# Max lines shown in the library content viewer; matches _DISPLAY_LIMIT in combine_tab.
_LIB_PREVIEW_LIMIT = _DISPLAY_LIMIT

# ── UI colors (easy to tweak) ────────────────────────────────────────
_CLR_SELECTED = ("gray70", "gray30")          # selected item background (light, dark)
_CLR_UNSELECTED = ("gray88", "gray20")         # subtle bg in light mode, near-invisible in dark
_CLR_BTN_TEXT = ("gray10", "#DCE4EE")         # button text: near-black (light), CTk default (dark)
_CLR_BTN_DEFAULT       = ["#3B8ED0", "#1F6AA5"]   # default button (light, dark)
_CLR_BTN_DANGER        = ["#C0392B", "#922B21"]   # destructive / stop button
_CLR_BTN_DANGER_HOVER  = ["#A93226", "#7B241C"]
_CLR_BTN_SUCCESS       = ["#27AE60", "#1E8449"]   # server reachable / confirmed action
_CLR_BTN_SUCCESS_HOVER = ["#219A52", "#196F3D"]


def _slugify(name: str) -> str:
    """Convert a list name to a URL-safe path component."""
    slug = name.lower()
    slug = _re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug or "list"


class _DeleteFolderDialog(ctk.CTkToplevel):
    """Confirm folder deletion with an option to also delete all lists inside."""

    def __init__(self, parent, folder_name: str) -> None:
        super().__init__(parent)
        self.transient(parent)
        self.title("Delete Folder")
        self.geometry("360x190")
        self.resizable(False, False)

        self.confirmed = False
        self.delete_lists = False

        ctk.CTkLabel(self, text=f'Delete folder "{folder_name}"?',
                     font=ctk.CTkFont(weight="bold")).pack(pady=(18, 4), padx=20)
        ctk.CTkLabel(self, text="Lists inside will be released to 🏠 Home.",
                     text_color="gray60").pack(padx=20)

        self._del_lists_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Also delete all lists inside",
                        variable=self._del_lists_var).pack(padx=24, anchor="w", pady=(12, 14))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        ctk.CTkButton(btn_row, text="Delete", fg_color=_CLR_BTN_DANGER,
                      command=self._on_delete).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(btn_row, text="Cancel",
                      command=self.destroy).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.update_idletasks()
        self.lift()
        self.focus_force()
        self.grab_set()

    def _on_delete(self) -> None:
        self.confirmed = True
        self.delete_lists = self._del_lists_var.get()
        self.destroy()


class LibraryTab(ctk.CTkFrame):
    """The Library tab: browse folders and saved lists, load back into combiner."""

    def __init__(self, parent, db: Database, get_combine_tab_cb, switch_to_combine_cb,
                 list_type_var: ctk.StringVar) -> None:
        super().__init__(parent, fg_color="transparent")
        self._db = db
        self._get_combine_tab = get_combine_tab_cb
        self._switch_to_combine = switch_to_combine_cb
        self._list_type_var = list_type_var
        self._selected_folder_id: Optional[int] = None  # None = root
        self._selected_list_ids: set[int] = set()  # multi-select (Ctrl+click)
        self._updating = False
        self._move_folder_picked = False  # True once user explicitly picks a folder
        self._server_reachable = False
        self._content_has_content = False  # True when real list content is loaded
        self._lists_placeholder_active = False

        self._build_ui()
        self.refresh()

    @property
    def _selected_list_id(self) -> Optional[int]:
        """Primary selected list (first in selection set). Used by single-action methods."""
        return next(iter(self._selected_list_ids), None)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0, minsize=220)
        self.columnconfigure(1, weight=1)
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
        def _hide_folders_sb(canvas=get_canvas(self._folders_frame), sb=get_scrollbar(self._folders_frame)):
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                sb.grid()
            else:
                sb.grid_remove()
        get_canvas(self._folders_frame).bind("<Configure>", lambda _: self.after(0, _hide_folders_sb))

        folder_btn_row = ctk.CTkFrame(left, fg_color="transparent")
        folder_btn_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 0))
        new_folder_btn = ctk.CTkButton(
            folder_btn_row, text="+ New Folder", width=100, command=self._new_folder
        )
        new_folder_btn.pack(side="left", padx=(0, 4))
        Tooltip(new_folder_btn, "Create a new folder to organize your saved lists.")

        self._rename_folder_btn = ctk.CTkButton(
            folder_btn_row, text="Rename", width=80, command=self._rename_folder,
            state="disabled", fg_color=("gray60", "gray40"),
        )
        self._rename_folder_btn.pack(side="left", padx=(0, 4))
        Tooltip(self._rename_folder_btn, "Rename the selected folder.")

        self._del_folder_btn = ctk.CTkButton(
            folder_btn_row, text="Delete", width=70, command=self._delete_folder,
            fg_color=("gray60", "gray40"), state="disabled",
            hover_color=_CLR_BTN_DANGER_HOVER,
        )
        self._del_folder_btn.pack(side="left")
        Tooltip(self._del_folder_btn, "Delete the selected folder. Lists inside are released to 🏠 Home, or optionally deleted.")

        self._lists_header_label = ctk.CTkLabel(
            left, text="LISTS", font=ctk.CTkFont(size=12, weight="bold")
        )
        self._lists_header_label.grid(row=3, column=0, sticky="w", padx=10, pady=(12, 4))

        self._lists_frame = ctk.CTkScrollableFrame(left, height=150)
        self._lists_frame.grid(row=4, column=0, sticky="nsew", padx=10)
        left.rowconfigure(4, weight=1)
        def _hide_lists_sb(canvas=get_canvas(self._lists_frame), sb=get_scrollbar(self._lists_frame)):
            bbox = canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > canvas.winfo_height():
                sb.grid()
            else:
                sb.grid_remove()
            if self._lists_placeholder_active:
                canvas.itemconfigure(get_inner_window_id(self._lists_frame),
                                     height=canvas.winfo_height(),
                                     width=canvas.winfo_width())
        get_canvas(self._lists_frame).bind("<Configure>", lambda _: self.after(0, _hide_lists_sb))

        list_btn_row = ctk.CTkFrame(left, fg_color="transparent")
        list_btn_row.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 10))
        list_btn_row.columnconfigure(0, weight=1)
        list_btn_row.columnconfigure(1, weight=1)

        self._rename_list_btn = ctk.CTkButton(
            list_btn_row, text="Rename", command=self._rename_list, state="disabled"
        )
        self._rename_list_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        Tooltip(self._rename_list_btn, "Rename the selected list.")

        self._del_list_btn = ctk.CTkButton(
            list_btn_row, text="Delete", command=self._delete_list,
            fg_color=("gray60", "gray40"), state="disabled",
        )
        self._del_list_btn.grid(row=0, column=1, sticky="ew")
        Tooltip(self._del_list_btn, "Permanently delete the selected list from the library.")

        self._combine_sel_btn = ctk.CTkButton(
            left, text="Combine Selected", command=self._combine_selected,
            state="disabled",
        )
        self._combine_sel_btn.grid(row=6, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._combine_sel_btn, "Merge 2+ selected lists into a new combined list (Ctrl+click to multi-select).")

        self._refetch_btn = ctk.CTkButton(
            left, text="Re-fetch Sources", command=self._refetch_selected, state="disabled"
        )
        self._refetch_btn.grid(row=7, column=0, sticky="ew", padx=10, pady=(4, 2))
        Tooltip(self._refetch_btn, "Re-fetch all sources and rebuild the selected lists with fresh data.")


        self._progress_label = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11))
        self._progress_bar = ctk.CTkProgressBar(left)
        # Progress widgets hidden until Re-fetch Sources is running

        # ── Right panel (content viewer) ────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        # Action buttons row (below content viewer)
        action_row = ctk.CTkFrame(right, fg_color="transparent")
        action_row.grid(row=1, column=0, sticky="w", padx=10, pady=(6, 4))

        self._open_btn = ctk.CTkButton(action_row, text="Open", width=70, state="disabled",
                                       command=self._open_list)
        self._open_btn.pack(side="left", padx=(0, 6))
        Tooltip(self._open_btn, "Load the selected list's content into the viewer.")

        self._copy_btn = ctk.CTkButton(action_row, text="Copy", width=70, state="disabled",
                                       command=self._copy_content)
        self._copy_btn.pack(side="left", padx=(0, 6))
        Tooltip(self._copy_btn, "Copy the list contents to the clipboard.")

        self._export_btn = ctk.CTkButton(action_row, text="Export", width=70, state="disabled",
                                         command=self._export)
        self._export_btn.pack(side="left", padx=(0, 6))
        Tooltip(self._export_btn, "Export File — save the list as a .txt file to disk.")

        self._load_btn = ctk.CTkButton(action_row, text="Load", width=70, state="disabled",
                                       command=self._load_into_combiner)
        self._load_btn.pack(side="left", padx=(0, 6))
        Tooltip(self._load_btn, "Load into Combiner — add this list as a source in the Combine tab.")

        self._push_btn = ctk.CTkButton(
            action_row, text="Push", width=70, command=self._push_to_server, state="disabled",
            fg_color=("gray60", "gray40"),
        )
        self._push_btn.pack(side="left")
        self._push_tooltip = Tooltip(self._push_btn,
                                     "No server configured — add URL and API key in Settings.")
        self._push_btn.bind("<Enter>", self._on_push_enter, add="+")
        self._push_btn.bind("<Leave>", self._on_push_leave, add="+")

        self._content_box = ctk.CTkTextbox(right, wrap="none", text_color="gray50", cursor="arrow")
        self._content_box.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        self._content_box.tag_config("placeholder", justify="center")
        self._content_box.insert("1.0", "Open a list to preview its contents here", "placeholder")
        self._content_box.configure(state="disabled")
        self._content_box.bind("<B1-Motion>",
                               lambda e: "break" if not self._content_has_content else None, add="+")
        self._content_box.bind("<Configure>", self._on_content_box_resize, add="+")

        # Right-click context menu for the content viewer
        self._ctx_menu = _tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="Copy", command=lambda: self._copy_content(selection_only=True))
        self._ctx_menu.add_command(label="Select All", command=self._ctx_select_all)
        self._content_box.bind("<Button-3>", self._show_ctx_menu)

        timestamp_row = ctk.CTkFrame(right, fg_color="transparent")
        timestamp_row.grid(row=2, column=0, sticky="e", padx=10, pady=(2, 0))
        self._lib_timestamp_label = ctk.CTkLabel(
            timestamp_row, text="", text_color=("gray15", "gray60"), font=ctk.CTkFont(size=11)
        )
        self._lib_timestamp_label.pack(side="right")

        # Move row (folder dropdown + Move)
        move_row = ctk.CTkFrame(right, fg_color="transparent")
        move_row.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 8))
        self._move_folder_var = ctk.StringVar(value="🏠 Home")
        self._move_menu = ctk.CTkOptionMenu(
            move_row, variable=self._move_folder_var, values=["🏠 Home"], width=160,
            state="disabled", command=self._on_move_folder_pick,
        )
        self._move_menu.pack(side="left", padx=(0, 8))
        Tooltip(self._move_menu, "Select a folder to move the selected list into.")
        self._move_menu.bind("<Enter>", self._on_move_menu_enter, add="+")
        self._move_menu.bind("<Leave>", self._on_move_menu_leave, add="+")
        self._move_btn = ctk.CTkButton(move_row, text="Move", width=70, state="disabled",
                                       command=self._move_list)
        self._move_btn.pack(side="left", padx=(0, 8))
        Tooltip(self._move_btn, "Move the selected list to a different folder. Doesn't change content.")


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
            text="🏠 Home",
            anchor="w",
            fg_color=(
                _CLR_SELECTED if self._selected_folder_id is None else _CLR_UNSELECTED
            ),
            text_color=_CLR_BTN_TEXT,
            command=lambda: self._select_folder(None),
        )
        root_btn.pack(fill="x", pady=1)

        for folder in self._db.get_folders():
            fid = folder["id"]
            is_selected = self._selected_folder_id == fid
            has_lists = bool(self._db.get_lists(folder_id=fid))
            if has_lists:
                arrow = "▼ " if is_selected else "▶ "
            else:
                arrow = "    "
            btn = ctk.CTkButton(
                self._folders_frame,
                text=f"{arrow}📁 {folder['name']}",
                anchor="w",
                fg_color=(
                    _CLR_SELECTED if is_selected else _CLR_UNSELECTED
                ),
                text_color=_CLR_BTN_TEXT,
                command=lambda f=fid: self._select_folder(f),
            )
            btn.pack(fill="x", pady=1)


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
        except Exception as exc:
            _log.debug("Date format fallback: %s", exc)
            return iso_str

    def _refresh_lists(self) -> None:
        for w in self._lists_frame.winfo_children():
            w.destroy()
        # Reset inner frame to content-driven height
        get_canvas(self._lists_frame).itemconfigure(
            get_inner_window_id(self._lists_frame), height=0)

        items = self._db.get_lists(self._selected_folder_id)
        if not items:
            self._lists_placeholder_active = True
            self._lists_header_label.grid_remove()
            if self._selected_folder_id is None:
                placeholder = "Combine sources and save\nto library to see\nyour lists here"
            else:
                placeholder = "No lists in this folder"
            ctk.CTkLabel(
                self._lists_frame,
                text=placeholder,
                text_color="gray50",
                anchor="center",
                justify="center",
                wraplength=160,
            ).pack(expand=True, fill="both")
            def _stretch():
                c = get_canvas(self._lists_frame)
                c.itemconfigure(get_inner_window_id(self._lists_frame),
                                height=c.winfo_height(), width=c.winfo_width())
            self.after(0, _stretch)
            return
        self._lists_placeholder_active = False
        self._lists_header_label.grid()

        for item in items:
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
        self._move_folder_map = {"🏠 Home": None}
        self._move_folder_map.update({f["name"]: f["id"] for f in folders})
        names = list(self._move_folder_map.keys())
        self._move_menu.configure(values=names)

    # ── Folder actions ───────────────────────────────────────────────

    def _select_folder(self, folder_id: Optional[int]) -> None:
        self._selected_folder_id = folder_id
        self._selected_list_ids.clear()
        is_real_folder = folder_id is not None
        self._rename_folder_btn.configure(
            state="normal" if is_real_folder else "disabled",
            fg_color=_CLR_BTN_DEFAULT if is_real_folder else ("gray60", "gray40"),
        )
        self._del_folder_btn.configure(
            state="normal" if is_real_folder else "disabled",
            fg_color=_CLR_BTN_DANGER if is_real_folder else ("gray60", "gray40"),
        )
        self._refresh_folders()
        self._refresh_lists()
        self._update_combine_btn()


    def _new_folder(self) -> None:
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if name and name.strip():
            if name.strip().lower() in ("root", "home"):
                messagebox.showwarning("Reserved name", '"Home" is reserved — choose a different name.', parent=self)
                return
            self._db.create_folder(name.strip())
            self.refresh()

    def _rename_folder(self) -> None:
        if self._selected_folder_id is None:
            messagebox.showinfo("Select a folder", "Select a folder to rename.")
            return
        new_name = simpledialog.askstring("Rename Folder", "New name:", parent=self)
        if new_name and new_name.strip():
            if new_name.strip().lower() in ("root", "home"):
                messagebox.showwarning("Reserved name", '"Home" is reserved — choose a different name.', parent=self)
                return
            self._db.rename_folder(self._selected_folder_id, new_name.strip())
            self.refresh()

    def _delete_folder(self) -> None:
        if self._selected_folder_id is None:
            messagebox.showinfo("Select a folder", '"🏠 Home" is the default location and cannot be deleted.')
            return
        # Look up folder name for the dialog
        folders = {f["id"]: f["name"] for f in self._db.get_folders()}
        folder_name = folders.get(self._selected_folder_id, "this folder")
        dlg = _DeleteFolderDialog(self, folder_name)
        self.wait_window(dlg)
        if not dlg.confirmed:
            return
        if dlg.delete_lists:
            for lst in self._db.get_lists(folder_id=self._selected_folder_id):
                self._db.delete_list(lst["id"])
        self._db.delete_folder(self._selected_folder_id)
        self._selected_folder_id = None
        self._selected_list_ids.clear()
        self.refresh()

    # ── List actions ─────────────────────────────────────────────────

    def _select_list(self, list_id: int) -> None:
        """Single-click: select one list (clears others). Does NOT load content."""
        self._selected_list_ids = {list_id}
        self._refresh_lists()
        self._update_combine_btn()

    def _toggle_select_list(self, list_id: int) -> None:
        """Ctrl+click: toggle a list in/out of the multi-selection."""
        if list_id in self._selected_list_ids:
            self._selected_list_ids.discard(list_id)
        else:
            self._selected_list_ids.add(list_id)
        self._refresh_lists()
        self._update_combine_btn()

    def _update_combine_btn(self) -> None:
        """Update selection-dependent button states."""
        n = len(self._selected_list_ids)
        self._combine_sel_btn.configure(state="normal" if n >= 2 else "disabled")
        any_sel = "normal" if n >= 1 else "disabled"
        self._refetch_btn.configure(state=any_sel)
        self._rename_list_btn.configure(state=any_sel)
        self._del_list_btn.configure(
            state=any_sel,
            fg_color=_CLR_BTN_DANGER if n >= 1 else ("gray60", "gray40"),
            hover_color=_CLR_BTN_DANGER_HOVER if n >= 1 else ("gray55", "gray35"),
        )
        self._open_btn.configure(state=any_sel)
        self._copy_btn.configure(state=any_sel)
        self._load_btn.configure(state=any_sel)
        has_folders = bool(self._move_folder_map)
        menu_enabled = n >= 1 and has_folders
        if not menu_enabled:
            self._move_folder_picked = False
        self._move_menu.configure(
            state="normal" if menu_enabled else "disabled",
            fg_color=(
                _CLR_BTN_DEFAULT if (menu_enabled and self._move_folder_picked)
                else ("gray60", "gray40")
            ),
            button_color=(
                _CLR_BTN_DEFAULT if (menu_enabled and self._move_folder_picked)
                else ("gray55", "gray35")
            ),
            text_color=(
                ("gray10", "#DCE4EE") if menu_enabled else ("gray70", "gray55")
            ),
        )
        self._move_btn.configure(state="disabled")  # enabled only after folder is picked
        self._export_btn.configure(state=any_sel)
        remote_url = self._db.get_setting("remote_server_url", "")
        if n >= 1 and remote_url and self._server_reachable:
            self._push_btn.configure(state="normal", fg_color=_CLR_BTN_SUCCESS, hover_color=_CLR_BTN_SUCCESS_HOVER)
            self._push_tooltip.update("Push to Server — upload to your phlist-server instance.")
        elif n >= 1 and remote_url:
            # URL set but not verified — disabled until connection tested
            self._push_btn.configure(state="disabled", fg_color=("gray60", "gray40"))
            self._push_tooltip.update("Connection not verified — go to Settings to test first.")
        else:
            self._push_btn.configure(state="disabled", fg_color=("gray60", "gray40"))
            self._push_tooltip.update(
                "No server configured — add URL and API key in Settings → Remote Server."
                if not remote_url else
                "Select a list and verify the connection in Settings first."
            )

    def _open_list(self) -> None:
        """Load the selected list's content into the viewer."""
        if self._selected_list_id is None:
            messagebox.showinfo("Select a list", "Select a list first, then click Open.")
            return
        row = self._db.get_list(self._selected_list_id)
        if not row:
            return
        root = self.winfo_toplevel()
        root.configure(cursor="watch")
        root.update_idletasks()
        try:
            self._content_has_content = True
            self._content_box.configure(state="normal", text_color=("gray10", "gray90"), cursor="")
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
            created = self._fmt_date(row.get("created_at", ""))
            updated = self._fmt_date(row.get("updated_at", ""))
            if updated:
                self._lib_timestamp_label.configure(text=f"Created: {created}  |  Updated: {updated}")
            elif created:
                self._lib_timestamp_label.configure(text=f"Created: {created}")
            else:
                self._lib_timestamp_label.configure(text="")
        finally:
            root.configure(cursor="")

    def _show_content_placeholder(self) -> None:
        """Insert vertically + horizontally centered placeholder in the content viewer."""
        import tkinter.font as _tkfont
        text = "Open a list to preview its contents here"
        self._content_has_content = False
        self._content_box.configure(state="normal", text_color="gray50", cursor="arrow")
        self._content_box.delete("1.0", "end")
        box_h = get_underlying_textbox(self._content_box).winfo_height()
        try:
            f = _tkfont.Font(font=get_underlying_textbox(self._content_box).cget("font"))
            line_h = f.metrics("linespace")
        except Exception as exc:
            _log.debug("Font metric fallback: %s", exc)
            line_h = 16
        blank = max(0, (box_h // max(line_h, 1)) // 2 - 1) if box_h > line_h else 0
        self._content_box.insert("1.0", "\n" * blank + text, "placeholder")
        self._content_box.configure(state="disabled")

    def _on_content_box_resize(self, _event=None) -> None:
        if self._content_has_content:
            return
        if hasattr(self, "_content_ph_after"):
            self.after_cancel(self._content_ph_after)
        self._content_ph_after = self.after(50, self._show_content_placeholder)

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
            self._db.delete_list(lid)
            self._selected_list_ids.discard(lid)
            self._show_content_placeholder()
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
                self._update_combine_btn()
                self._push_btn.configure(text="Push")
                if ok:
                    pi_url = f"{url}/lists/{slug}.txt"
                    try:
                        self.clipboard_clear()
                        self.clipboard_append(pi_url)
                    except Exception:
                        pass
                    messagebox.showinfo("Pushed", f"{row['name']} pushed.\n\nPi-hole URL (copied to clipboard):\n{pi_url}")
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
        root = self.winfo_toplevel()
        root.configure(cursor="watch")
        root.update()  # force cursor repaint before the synchronous work starts

        def _do() -> None:
            try:
                sources = []
                sources_json = row.get("sources") or ""
                if sources_json:
                    try:
                        sources = json.loads(sources_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                stats = {
                    "unique_domains": row["domain_count"],
                    "duplicates_removed": row["duplicates_removed"],
                }
                self._get_combine_tab().load_library_result(
                    row["name"], sources, row["content"], stats
                )
                self._switch_to_combine()
            finally:
                root.configure(cursor="")

        self.after(1, _do)

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
        self.winfo_toplevel().configure(cursor="watch")

        timeout = int(self._db.get_setting("fetch_timeout", "30"))
        max_mb = int(self._db.get_setting("max_fetch_mb", "50"))

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
                result = _run_update(
                    sources_json,
                    self._list_type_var.get(),
                    timeout=timeout,
                    max_bytes=max_mb * 1024 * 1024,
                )
                results.append((lid, name, result))
            self.after(0, lambda: self._on_refetch_done(results))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_refetch_done(self, results: list) -> None:
        self.winfo_toplevel().configure(cursor="")
        self._progress_label.grid_forget()
        self._progress_bar.grid_forget()
        self._set_updating(False)

        updated = 0
        all_failures = []
        for lid, name, (content, domain_count, duplicates_removed, failed) in results:
            if content and self._db.get_list(lid):
                self._db.update_list(lid, content, domain_count, duplicates_removed)
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

    def _on_move_folder_pick(self, _value: str) -> None:
        """Enable the Move button and lock dropdown blue once a folder is chosen."""
        if self._selected_list_ids and _value in self._move_folder_map:
            self._move_folder_picked = True
            self._move_menu.configure(
                fg_color=_CLR_BTN_DEFAULT, button_color=_CLR_BTN_DEFAULT,
            )
            self._move_btn.configure(state="normal")

    def _on_move_menu_enter(self, _event=None) -> None:
        """Highlight dropdown blue on hover when armed but not yet picked."""
        if self._selected_list_ids and not self._move_folder_picked:
            self._move_menu.configure(
                fg_color=_CLR_BTN_DEFAULT, button_color=_CLR_BTN_DEFAULT,
            )

    def _on_move_menu_leave(self, _event=None) -> None:
        """Revert to grey on leave if no folder has been picked yet."""
        if not self._move_folder_picked:
            self._move_menu.configure(
                fg_color=("gray60", "gray40"), button_color=("gray55", "gray35"),
            )

    def _on_push_enter(self, _event=None) -> None:
        remote_url = self._db.get_setting("remote_server_url", "")
        if self._selected_list_ids and remote_url and not self._server_reachable:
            self._push_btn.configure(fg_color=_CLR_BTN_DEFAULT)

    def _on_push_leave(self, _event=None) -> None:
        if not self._server_reachable:
            self._push_btn.configure(fg_color=("gray60", "gray40"))

    def set_server_reachable(self, ok: bool) -> None:
        """Called when connection test result changes."""
        self._server_reachable = ok
        self._update_combine_btn()

    def _move_list(self) -> None:
        if self._selected_list_id is None:
            return
        folder_name = self._move_folder_var.get()
        if folder_name not in self._move_folder_map:
            return
        folder_id = self._move_folder_map[folder_name]
        self._db.move_list(self._selected_list_id, folder_id)
        self._refresh_lists()
        messagebox.showinfo("Moved", f"List moved to {folder_name}.")

    # ── Refresh Credits ────────────────────────────────────────────────

    def refresh_all_credits(self) -> None:
        """Re-extract credits from source URLs for every list in the library."""
        rows = self._db.get_all_lists()
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

        root = self.winfo_toplevel()
        root.configure(cursor="watch")
        root.update_idletasks()
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
        root.configure(cursor="")
        self.refresh()
        self._get_combine_tab().load_library_result(
            dialog.result_name, unique_sources, result, stats,
        )
        self._switch_to_combine()
