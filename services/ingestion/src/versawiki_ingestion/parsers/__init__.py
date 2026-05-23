"""Parsers: file-type adapters returning a uniform `ParseResult`."""

from .base import BaseParser, ParseResult
from .email import EmailParser
from .excel import ExcelParser
from .registry import ParserRegistry

__all__ = ["BaseParser", "ParseResult", "EmailParser", "ExcelParser", "ParserRegistry"]
