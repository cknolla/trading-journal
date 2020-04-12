"""
Convenient methods to transform strings.
"""

import re
from datetime import datetime, date
from enum import IntEnum


def _convert_snake_to_camel(snake_case_string: str) -> str:
    """
    Convert a string provided in snake_case to camelCase
    """
    words = iter(snake_case_string.split("_"))
    return next(words) + "".join(word.capitalize() for word in words)

    ## another way to do it
    # pattern = re.compile(r'_([a-z])')
    # return pattern.sub(lambda x: x.group(1).upper(), snake_case_string)


def _convert_snake_to_pascal(snake_case_string: str) -> str:
    """
    Convert a string provided in snake_case to PascalCase
    """
    return ''.join(word.capitalize() for word in snake_case_string.split('_'))


def _convert_snake_to_kebab(snake_case_string: str) -> str:
    """
    Convert a string provided in snake_case to kebab-case
    """
    return snake_case_string.replace('_', '-')


def _convert_camel_to_snake(camel_case_string: str) -> str:
    """
    Convert a string provided in camelCase to snake_case
    """
    pattern = re.compile(r'([A-Z])')
    return pattern.sub(lambda x: '_' + x.group(1).lower(), camel_case_string)


def _convert_camel_to_pascal(camel_case_string: str) -> str:
    """
    Convert a string provided in camelCase to PascalCase
    """
    return camel_case_string[:1].upper() + camel_case_string[1:]


def _convert_camel_to_kebab(camel_case_string: str) -> str:
    """
    Convert a string provided in camelCase to kebab-case
    """
    pattern = re.compile(r'([A-Z])')
    return pattern.sub(lambda x: '-' + x.group(1).lower(), camel_case_string)


def _convert_pascal_to_snake(pascal_case_string: str) -> str:
    """
    Convert a string provided in PascalCase to snake_case
    """
    return '_'.join(word.lower() for word in re.findall('[A-Z][^A-Z]*', pascal_case_string))


def _convert_pascal_to_camel(pascal_case_string: str) -> str:
    """
    Convert a string provided in PascalCase to camelCase
    """
    return pascal_case_string[:1].lower() + pascal_case_string[1:]


def _convert_pascal_to_kebab(pascal_case_string: str) -> str:
    """
    Convert a string provided in PascalCase to kebab-case
    """
    return '-'.join(word.lower() for word in re.findall('[A-Z][^A-Z]*', pascal_case_string))


def _convert_kebab_to_pascal(kebab_case_string: str) -> str:
    """
    Convert a string provided in kebab-case to PascalCase
    """
    return ''.join(word.capitalize() for word in kebab_case_string.split('-'))


def _convert_kebab_to_camel(kebab_case_string: str) -> str:
    """
    Convert a string provided in kebab-case to camelCase
    """
    words = iter(kebab_case_string.split("-"))
    return next(words) + "".join(word.capitalize() for word in words)


def _convert_kebab_to_snake(kebab_case_string: str) -> str:
    """
    Convert a string provided in kebab-case to snake_case
    """
    return kebab_case_string.replace('-', '_')


class Case(IntEnum):
    """
    List of surpported string cases
    """
    SNAKE = 1
    CAMEL = 2
    PASCAL = 3
    KEBAB = 4


def convert_case(string: str, source_case: Case, target_case: Case) -> str:
    """
    Convert provided string from source_case to target_case
    """
    dispatch = {
        Case.SNAKE: {
            Case.CAMEL: _convert_snake_to_camel,
            Case.PASCAL: _convert_snake_to_pascal,
            Case.KEBAB: _convert_snake_to_kebab,
        },
        Case.CAMEL: {
            Case.SNAKE: _convert_camel_to_snake,
            Case.PASCAL: _convert_camel_to_pascal,
            Case.KEBAB: _convert_camel_to_kebab,
        },
        Case.PASCAL: {
            Case.SNAKE: _convert_pascal_to_snake,
            Case.CAMEL: _convert_pascal_to_camel,
            Case.KEBAB: _convert_pascal_to_kebab,
        },
        Case.KEBAB: {
            Case.SNAKE: _convert_kebab_to_snake,
            Case.CAMEL: _convert_kebab_to_camel,
            Case.PASCAL: _convert_kebab_to_pascal,
        }
    }
    return dispatch[source_case][target_case](string)


def dt_str(dt_object: datetime, format_='%Y-%m-%dT%H:%M:%S') -> str:
    """
    Converts python datetime object into datetime string
    """
    return dt_object.strftime(format_)


def str_dt(date_string: str, format_='%Y-%m-%dT%H:%M:%S') -> datetime:
    """
    Converts a datetime string into a datetime object
    """
    return datetime.strptime(date_string, format_)

