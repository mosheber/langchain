import unittest

import pytest

from langchain_community.document_loaders.parsers.language.lua import LuaSegmenter


@pytest.mark.requires("tree_sitter", "tree_sitter_languages")
class TestLuaSegmenter(unittest.TestCase):
    def setUp(self) -> None:
        self.example_code = """function F()
    print("Hello")
end

local function G()
    print("Goodbye")
end"""

        self.expected_simplified_code = """-- Code for: function F()

-- Code for: local function G()"""

        self.expected_extracted_code = [
            'function F()\n    print("Hello")\nend',
            'local function G()\n    print("Goodbye")\nend',
        ]

    def test_is_valid(self) -> None:
        self.assertTrue(LuaSegmenter("local a").is_valid())
        self.assertFalse(LuaSegmenter("a b c 1 2 3").is_valid())

    def test_extract_functions_classes(self) -> None:
        segmenter = LuaSegmenter(self.example_code)
        extracted_code = segmenter.extract_functions_classes()
        self.assertEqual(extracted_code, self.expected_extracted_code)

    def test_simplify_code(self) -> None:
        segmenter = LuaSegmenter(self.example_code)
        simplified_code = segmenter.simplify_code()
        self.assertEqual(simplified_code, self.expected_simplified_code)
