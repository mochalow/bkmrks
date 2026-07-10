import sys
from pathlib import Path

# Модули проекта (main, parser, storage) лежат на уровень выше docs/.
# Якорим путь к conf.py, а не к текущему каталогу, иначе результат
# зависит от того, откуда запущен sphinx-build (из docs/ или из корня репо).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

project = "bkmrks"
author = "Ivan Mochalov"
copyright = "2026, Ivan Mochalov"
release = "0.1.0"
language = "ru"

extensions = [
    "sphinx.ext.autodoc",  # вытягивает docstring-и из кода
    "sphinx.ext.napoleon",  # понимает Google-стиль (Args:/Returns:/Raises:)
    "sphinx.ext.viewcode",  # добавляет ссылки на исходники
    "myst_parser",  # Markdown-страницы и include README
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_heading_anchors = 3

# Napoleon: только Google-стиль, NumPy выключаем
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# Типы берём из аннотаций сигнатур и вставляем в описание параметров -
# в docstring-ах их дублировать не нужно.
autodoc_typehints = "description"
autodoc_member_order = "bysource"

# Дополнительные опции по умолчанию для .. autoclass:: и .. automodule::
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

html_title = "bkmrks — документация"
html_short_title = "bkmrks"
html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_favicon = "_static/favicon.svg"

pygments_style = "sphinx"
pygments_dark_style = "monokai"

html_theme_options = {
    "sidebar_hide_name": False,
    "top_of_page_button": "edit",
    "light_logo": None,
    "dark_logo": None,
    "light_css_variables": {
        "color-brand-primary": "#009688",
        "color-brand-content": "#00796b",
        "color-admonition-title--note": "#009688",
        "color-admonition-title-background--note": "rgba(0, 150, 136, 0.1)",
    },
    "dark_css_variables": {
        "color-brand-primary": "#4db6ac",
        "color-brand-content": "#80cbc4",
        "color-admonition-title--note": "#4db6ac",
        "color-admonition-title-background--note": "rgba(77, 182, 172, 0.15)",
    },
}

exclude_patterns = ["_build", "node_modules"]


# Скрываем служебные атрибуты Pydantic (model_config и т.п.) из Sphinx-документации.
# Они появляются автоматически при :members: на классах BaseModel.
def _skip_pydantic_internals(app, what, name, obj, skip, options):
    if name in ("model_config", "model_fields", "model_computed_fields"):
        return True
    return skip


def setup(app):
    app.connect("autodoc-skip-member", _skip_pydantic_internals)
