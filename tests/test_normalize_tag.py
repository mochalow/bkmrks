"""Юнит-тесты нормализации тега.

Контрактные проверки тега (нормализация, идемпотентность, запрет ``/``)
идут через HTTP в ``test_tags_api.py``. Здесь - свойство самой чистой
функции: примеры проверяет таблица, свойство проверяет генератор.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from main import _normalize_tag

# Фикстура изоляции хранилища autouse и приезжает даже сюда; тест диска
# не касается, поэтому проверку hypothesis на функциональные фикстуры
# здесь глушим.
#
# deadline снят: вердикт свойства чистой функции не должен
# зависеть от загрузки машины.
_PROPERTY = settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


@_PROPERTY
@given(st.text(alphabet=st.characters(exclude_characters="/")))
def test_tag_normalization_is_idempotent(raw):
    """Нормализация нормализованного тега ничего не меняет.

    Без этого свойства «повторное добавление тега идемпотентно» держится
    на трёх примерах: тег, прошедший нормализацию, при следующем
    добавлении мог бы дать другую строку и создать дубликат.

    Символ ``/`` исключён из алфавита: на нём функция осознанно бросает
    422, это отдельная ветка и отдельный тест.
    """
    once = _normalize_tag(raw)

    assert _normalize_tag(once) == once
