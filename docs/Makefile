# Каталоги сборки
SPHINX_SRC := .
SPHINX_OUT := _build/html
JS_OUT     := _build/js

.DEFAULT_GOAL := docs
.PHONY: docs docs-py docs-js docs-clean

docs: docs-py docs-js  ## Собрать всю статическую документацию (нужны Python + Node.js)

docs-py:  ## Документация Python (Sphinx)
	sphinx-build -b html $(SPHINX_SRC) $(SPHINX_OUT)

docs-js:  ## Документация JS (JSDoc, нужен Node.js)
	npm ci --silent 2>/dev/null || npm install --silent
	npx jsdoc -c jsdoc.json

docs-clean:  ## Удалить собранную документацию
	rm -rf _build