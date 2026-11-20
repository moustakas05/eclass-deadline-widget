# -*- coding: utf-8 -*-
"""
Login dialog (CustomTkinter) για εισαγωγή & αποθήκευση στοιχείων UOWM eClass.
"""

from pathlib import Path
import sys
import customtkinter as ctk

if getattr(sys, "frozen", False):
  BASE_DIR = Path(sys.executable).resolve().parent
else:
  BASE_DIR = Path(__file__).resolve().parent

ENV_PATH = BASE_DIR / ".env"

BG = "#0f172a"
CARD_BG = "#1e293b"
BORDER = "#334155"
TEXT = "#f1f5f9"
MUTED = "#94a3b8"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2563eb"
RED = "#ef4444"


class LoginDialog(ctk.CTk):

  def __init__(self, error_msg: str = ""):
    super().__init__()
    self.credentials: tuple[str, str] | None = None

    self.title("UOWM eClass Login")
    self.resizable(False, False)
    self.configure(fg_color=BG)
    self.attributes("-topmost", True)

    width, height = 350, 355
    x = (self.winfo_screenwidth() // 2) - (width // 2)
    y = (self.winfo_screenheight() // 2) - (height // 2)
    self.geometry(f"{width}x{height}+{x}+{y}")

    frame = ctk.CTkFrame(
        self, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=BORDER
    )
    frame.pack(fill="both", expand=True, padx=16, pady=16)

    ctk.CTkLabel(
        frame,
        text="Open eClass ΠΔΜ",
        font=ctk.CTkFont(size=18, weight="bold"),
        text_color=TEXT,
    ).pack(pady=(18, 2))

    ctk.CTkLabel(
        frame,
        text="Εισάγετε τα ιδρυματικά σας στοιχεία",
        font=ctk.CTkFont(size=12),
        text_color=MUTED,
    ).pack(pady=(0, 14))

    self.user_entry = ctk.CTkEntry(
        frame,
        placeholder_text="Username",
        width=260,
        height=36,
    )
    self.user_entry.pack(pady=6)

    self.pass_entry = ctk.CTkEntry(
        frame,
        placeholder_text="Password",
        show="•",
        width=260,
        height=36,
    )
    self.pass_entry.pack(pady=6)
    self.pass_entry.bind("<Return>", lambda _e: self._submit())

    self.remember_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(
        frame,
        text="Αποθήκευση στοιχείων σύνδεσης",
        variable=self.remember_var,
        font=ctk.CTkFont(size=12),
        text_color=TEXT,
    ).pack(pady=(10, 4))

    self.status_label = ctk.CTkLabel(
        frame,
        text=error_msg,
        font=ctk.CTkFont(size=11),
        text_color=RED,
        height=18,
    )
    self.status_label.pack(pady=(2, 6))

    ctk.CTkButton(
        frame,
        text="Σύνδεση",
        width=260,
        height=38,
        corner_radius=8,
        fg_color=ACCENT,
        hover_color=ACCENT_HOVER,
        text_color=TEXT,
        font=ctk.CTkFont(size=14, weight="bold"),
        command=self._submit,
    ).pack(pady=(2, 16))

    self.user_entry.focus()

  def _submit(self) -> None:
    username = self.user_entry.get().strip()
    password = self.pass_entry.get()
    if not username or not password:
      self.status_label.configure(text="Συμπληρώστε username και password.")
      return

    if self.remember_var.get():
      ENV_PATH.write_text(
          f"ECLASS_USERNAME={username}\nECLASS_PASSWORD={password}\n",
          encoding="utf-8",
      )

    self.credentials = (username, password)
    self.destroy()


def prompt_credentials(error_msg: str = "") -> tuple[str, str] | None:
  ctk.set_appearance_mode("dark")
  ctk.set_default_color_theme("blue")
  dialog = LoginDialog(error_msg=error_msg)
  dialog.mainloop()
  return dialog.credentials