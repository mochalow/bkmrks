Справочник модулей
==================

В этом разделе автоматически генерируется документация по исходному коду
Python (Sphinx + autodoc + napoleon). Все публичные и вспомогательные
функции документированы в исходниках.

Модели Pydantic
---------------

Модели :class:`main.ArticleIn`, :class:`main.TagIn` и :class:`main.Article`
описаны в модуле ``main``. Они используются и для валидации
запросов, и для генерации схемы OpenAPI.

Основные модули
---------------

main
~~~~
Точка входа FastAPI. Содержит все HTTP-маршруты, Pydantic-схемы и
вспомогательную логику приложения. Модели Pydantic включены автоматически.

.. automodule:: main
   :members:
   :private-members:
   :special-members: __all__

parser
~~~~~~
Обёртка над trafilatura. Отвечает за скачивание и очистку контента.

.. automodule:: parser
   :members:
   :private-members:

storage
~~~~~~~
Плоское файловое хранилище (JSON + изображения). Не зависит от HTTP.

.. automodule:: storage
   :members:
   :private-members: