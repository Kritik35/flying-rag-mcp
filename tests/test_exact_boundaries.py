"""Шифр совпал, потому что оказался началом другого шифра.

`exact_hits` сравнивал подстрокой, и `ZX-100` засчитывался внутри `ZX-1000`.
На этом корпусе это не выдумка: коды помещений идут подряд и отличаются одной
цифрой — `R.L2.15.114` входит в `R.L2.15.1145`, `1.02.11.024` в
`1.02.11.0245`. Совпадение по шифру — первый тай-брейк ранжирования, то есть
ложное совпадение поднимает чужой лист на первое место.

Границу задаёт не пробел: `(А-01.2.14)`, `У-02.8.1,` и `П1-TRF-01-01.` — это
те же шифры. Границей считается всё, что не может быть продолжением шифра,
то есть не буква, не цифра и не один из разделителей `.`, `-`, `/`, `_`.

Вторая часть — короткие шифры. `exact_tokens('В1-а')` возвращал пустой список:
шаблон требовал либо три разделённых части, либо пять знаков подряд. Марка
системы из двух частей — обычное дело в проекте, и её тоже надо ловить.
"""
from __future__ import annotations

import unittest

from rag_server.query_shape import exact_hits, exact_tokens


class BoundaryTests(unittest.TestCase):
    def test_a_code_does_not_match_inside_a_longer_code(self):
        self.assertEqual(exact_hits(["ZX-100"], "поз. ZX-1000 в ведомости"), 0)

    def test_a_room_code_does_not_match_inside_a_longer_one(self):
        self.assertEqual(exact_hits(["R.L2.15.114"], "помещение R.L2.15.1145"), 0)
        self.assertEqual(exact_hits(["1.02.11.024"], "прим. 1.02.11.0245"), 0)

    def test_the_code_itself_still_matches(self):
        self.assertEqual(exact_hits(["ZX-100"], "поз. ZX-100 в ведомости"), 1)
        self.assertEqual(exact_hits(["R.L2.15.114"], "R.L2.15.114 Венткамера"), 1)

    def test_punctuation_around_the_code_is_a_boundary(self):
        for text in ("(А-01.2.14)", "А-01.2.14,", "А-01.2.14.", "«А-01.2.14»",
                     "лист А-01.2.14; далее"):
            self.assertEqual(exact_hits(["А-01.2.14"], text), 1, text)

    def test_a_code_at_the_very_start_or_end_matches(self):
        self.assertEqual(exact_hits(["У-02.8.1"], "У-02.8.1"), 1)
        self.assertEqual(exact_hits(["У-02.8.1"], "система У-02.8.1"), 1)

    def test_a_prefix_of_a_longer_code_is_not_a_hit_even_at_the_start(self):
        self.assertEqual(exact_hits(["У-02.8.1"], "У-02.8.12 в разделе"), 0)

    def test_several_codes_are_counted_separately(self):
        text = "помещения R.L2.15.114 и R.L2.15.115"
        self.assertEqual(exact_hits(["R.L2.15.114", "R.L2.15.115"], text), 2)
        self.assertEqual(exact_hits(["R.L2.15.114", "R.L2.15.999"], text), 1)

    def test_an_empty_input_is_no_hits(self):
        self.assertEqual(exact_hits([], "что угодно"), 0)
        self.assertEqual(exact_hits(["ZX-100"], ""), 0)


class ShortCodeTests(unittest.TestCase):
    """Марка системы из двух частей — тоже шифр."""

    def test_a_two_part_system_mark_is_an_identifier(self):
        self.assertEqual(exact_tokens("В1-а"), ["В1-а"])
        self.assertEqual(exact_tokens("П2-CAF"), ["П2-CAF"])

    def test_the_long_forms_still_work(self):
        self.assertEqual(exact_tokens("П1-TRF-01-01"), ["П1-TRF-01-01"])
        self.assertEqual(exact_tokens("R.L2.15.114"), ["R.L2.15.114"])
        self.assertEqual(exact_tokens("O01163"), ["O01163"])

    def test_an_ordinary_hyphenated_word_is_not_an_identifier(self):
        """Иначе шифром станет половина русского текста."""
        for word in ("во-первых", "из-за", "кто-то", "какой-нибудь",
                     "тепло-холодоснабжение"):
            self.assertEqual(exact_tokens(word), [], word)

    def test_a_bare_number_is_not_an_identifier(self):
        self.assertEqual(exact_tokens("2100"), [])
        self.assertEqual(exact_tokens("27,93"), [])


if __name__ == "__main__":
    unittest.main()
