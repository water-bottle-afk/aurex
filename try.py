import flet as ft

def main(page: ft.Page):
    # Basic Page Setup
    page.title = "Aurex Python UI"
    page.theme_mode = ft.ThemeMode.DARK
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    txt_number = ft.TextField(value="0", text_align=ft.TextAlign.RIGHT, width=100)

    def minus_click(e):
        txt_number.value = str(int(txt_number.value) - 1)
        page.update()

    def plus_click(e):
        txt_number.value = str(int(txt_number.value) + 1)
        page.update()

    page.add(
        ft.Row(
            [
                # USE STRINGS INSTEAD OF CONSTANTS
                ft.IconButton(icon="remove", on_click=minus_click),
                txt_number,
                ft.IconButton(icon="add", on_click=plus_click),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        ft.Text("Python 3.14 is officially driving your phone UI!", size=20)
    )

if __name__ == "__main__":
    # Using 0.0.0.0 to ensure your phone can see the PC
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, host="10.100.102.58", port=8555)