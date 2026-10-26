import attr
import inspect

documented = "attr.s(these=None, repr_ns=None, repr=None, cmp=None, hash=None, init=None, slots=False, frozen=False, weakref_slot=True, str=False, auto_attribs=False, kw_only=False, cache_hash=False, auto_exc=False, eq=None, order=None, auto_detect=False, collect_by_mro=False, getstate_setstate=None, on_setattr=None, field_transformer=None, match_args=True, unsafe_hash=None)"
actual_params = list(inspect.signature(attr.s).parameters)
# DOC-LITERAL-BEGIN
assert "force_kw_only" not in actual_params, "docs omit force_kw_only but implementation accepts it"
# DOC-LITERAL-END
print("DOCS_OK")
