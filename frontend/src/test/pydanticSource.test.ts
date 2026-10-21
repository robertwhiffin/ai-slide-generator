/**
 * The shared Pydantic-source reader, against a SYNTHETIC Python source.
 *
 * Deliberately does not pin deck_spec.py's field list: that is the conformance
 * test's job, and pinning it here would make every model change touch this file.
 * The one real-file test only checks the reader's own internal consistency.
 *
 * Each trap in SYNTHETIC_MODELS guards one line of the reader:
 *  - `not_a_field: int` sits in a class docstring at the field indent, so it is
 *    seen only if the docstring strip is dropped.
 *  - `local: int = 1` sits in a validator body at eight spaces, so it is seen
 *    only if the four-space class-body rule is loosened.
 *  - `b: Optional[int] = None` carries a default, so it is read only if the
 *    annotation pattern tolerates `= ...`.
 *  - `class Ghost(BaseModel):` sits in the module docstring at column 0, so it is
 *    listed only if pythonModelClasses stops stripping docstrings itself.
 *    (`fake_field: str` in that docstring is never in any class body; it records
 *    that module prose is not a field either.)
 *  - `class Kind(Enum):` is a class but not a model, so pythonModelClasses must
 *    skip it; it is listed only if the `(BaseModel)` base-class match is loosened.
 */
import deckSpecPy from '../../../src/domain/deck_spec.py?raw';
import {
  pythonClassBody,
  pythonModelClasses,
  pythonModelFieldAnnotations,
  pythonModelFields,
} from './pydanticSource';

const SYNTHETIC_MODELS = `"""Synthetic models for the reader test.

    fake_field: str

class Ghost(BaseModel):
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator


class Inner(BaseModel):
    """An inner model.

    Prose that happens to look like a field:
    not_a_field: int
    """

    a: str
    b: Optional[int] = None

    @field_validator("a")
    @classmethod
    def _check_a(cls, value: str) -> str:
        local: int = 1
        return value


class Kind(Enum):
    first = "first"


class Outer(BaseModel):
    items: list[Inner]
    inner: Inner
`;

describe('pythonModelClasses', () => {
  it('lists every BaseModel class in declaration order, ignoring docstring prose and non-model classes', () => {
    expect(pythonModelClasses(SYNTHETIC_MODELS)).toEqual(['Inner', 'Outer']);
  });
});

describe('pythonModelFields', () => {
  it('returns the class-level field names in order, not docstring or method-body lines', () => {
    expect(pythonModelFields(SYNTHETIC_MODELS, 'Inner')).toEqual(['a', 'b']);
  });

  it('reads the class it is asked for, not a neighbour', () => {
    expect(pythonModelFields(SYNTHETIC_MODELS, 'Outer')).toEqual(['items', 'inner']);
  });
});

describe('pythonModelFieldAnnotations', () => {
  it('maps each field to its annotation, in declaration order, without the default', () => {
    expect([...pythonModelFieldAnnotations(SYNTHETIC_MODELS, 'Inner')]).toEqual([
      ['a', 'str'],
      ['b', 'Optional[int]'],
    ]);
  });

  it('keeps a generic annotation and a bare class annotation apart', () => {
    expect([...pythonModelFieldAnnotations(SYNTHETIC_MODELS, 'Outer')]).toEqual([
      ['items', 'list[Inner]'],
      ['inner', 'Inner'],
    ]);
  });
});

describe('a class that is not in the source', () => {
  it.each([
    ['pythonClassBody', () => pythonClassBody(SYNTHETIC_MODELS, 'Missing')],
    ['pythonModelFields', () => pythonModelFields(SYNTHETIC_MODELS, 'Missing')],
    ['pythonModelFieldAnnotations', () => pythonModelFieldAnnotations(SYNTHETIC_MODELS, 'Missing')],
  ])('%s throws naming the class', (_name, read) => {
    expect(read).toThrow(/class Missing\(BaseModel\) not found/);
  });
});

describe('the real deck_spec.py', () => {
  it('has models, and for each the annotation keys are exactly the model fields', () => {
    const classes = pythonModelClasses(deckSpecPy);
    expect(classes.length).toBeGreaterThan(0);
    for (const className of classes) {
      expect([...pythonModelFieldAnnotations(deckSpecPy, className).keys()]).toEqual(
        pythonModelFields(deckSpecPy, className),
      );
    }
  });
});
