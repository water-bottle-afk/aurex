"""Flet file upload test for Aurex.
Run with:
    python Client/test.py
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import flet as ft

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB safety cap


def main(page: ft.Page) -> None:
    page.title = "Aurex File Upload Test"
    page.theme_mode = ft.ThemeMode.DARK
    page.vertical_alignment = ft.MainAxisAlignment.START

    selected: dict = {"bytes": None, "name": "", "ext": ""}

    file_name_text = ft.Text("No file selected", size=12)
    status_text = ft.Text("", size=12, visible=False)
    preview_image = ft.Image(
        src="",
        visible=False,
        width=300,
        height=220,
        fit=ft.BoxFit.COVER,
        border_radius=10,
    )

    def set_status(message: str, *, error: bool = False, show: bool = True) -> None:
        status_text.value = message
        status_text.color = "#EF4444" if error else "#A0A0A0"
        status_text.visible = show
        page.update()

    def _on_upload(e: ft.FilePickerUploadEvent) -> None:
        if e.error:
            set_status(f"Upload error: {e.error}", error=True)
            return
        if e.progress is not None and e.progress < 1.0:
            return
        upload_dir = Path(__file__).resolve().parents[1] / "uploads"
        file_path = upload_dir / e.file_name
        if not file_path.is_file():
            set_status("Could not find uploaded file", error=True)
            return
        raw = file_path.read_bytes()
        if not raw:
            set_status("Could not read file -- try again", error=True)
            return
        if len(raw) > MAX_UPLOAD_BYTES:
            set_status("File too large (max 10MB)", error=True)
            return

        name = e.file_name
        extension = os.path.splitext(name)[1].lower().lstrip(".")
        ext = "jpg" if extension == "jpeg" else extension
        selected["bytes"] = raw
        selected["name"] = name
        selected["ext"] = ext

        mime = "image/png" if ext == "png" else "image/jpeg"
        preview_image.src = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        preview_image.visible = True
        file_name_text.value = f"Selected: {name} ({len(raw):,} bytes)"
        file_name_text.color = "#FFFFFF"
        set_status("", show=False)
        page.update()

    picker = ft.FilePicker(on_upload=_on_upload)
    page.services.append(picker)

    async def pick_file(_: ft.ControlEvent) -> None:
        files = await picker.pick_files(
            allow_multiple=False,
            file_type=ft.FilePickerFileType.IMAGE,
        )
        if not files:
            return
        f = files[0]
        name = f.name or ""
        extension = os.path.splitext(name)[1].lower().lstrip(".")
        if extension not in {"jpg", "jpeg", "png"}:
            set_status("Only JPG and PNG images are supported", error=True)
            return
        if getattr(f, "size", None) and f.size > MAX_UPLOAD_BYTES:
            set_status("File too large (max 10MB)", error=True)
            return
        upload_url = page.get_upload_url(name, 60)
        await picker.upload([ft.FilePickerUploadFile(name=name, upload_url=upload_url)])

    pick_button = ft.FilledButton(
        content="Choose Image",
        icon=ft.Icons.IMAGE_OUTLINED,
        on_click=lambda e: page.run_task(pick_file, e),
    )

    page.add(
        ft.Text("Aurex File Upload Test", size=22, weight=ft.FontWeight.BOLD),
        ft.Row([pick_button, file_name_text], alignment=ft.MainAxisAlignment.START),
        preview_image,
        status_text,
    )


if __name__ == "__main__":
    upload_dir = Path(__file__).resolve().parents[1] / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    if not os.getenv("FLET_SECRET_KEY"):
        os.environ["FLET_SECRET_KEY"] = "dev-secret-change-me"
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        upload_dir=str(upload_dir),
    )
