import doctest

doc = r'''
>>> from attrs import define, field, validators
>>> @define
... class C:
...     x: int = field(validator=validators.instance_of(int))
>>> C(42)
C(x=42)
>>> C("42")
Traceback (most recent call last):
   ...
TypeError: ("'x' must be <type 'int'> (got '42' that is a <type 'str'>).", Attribute(name='x', default=NOTHING, factory=NOTHING, validator=<instance_of validator for type <type 'int'>>, type=None, kw_only=False), <type 'int'>, '42')
'''

# DOC-LITERAL-BEGIN
test = doctest.DocTestParser().get_doctest(doc, globals(), "doc", __file__, 0)
runner = doctest.DocTestRunner()
result = runner.run(test)
assert result.failed == 0
print("DOCS_OK")
# DOC-LITERAL-END
