import inspect

import pydantic_settings
import pydantic_settings.main as main

defaults = []
for mod in (pydantic_settings, main):
    for name in dir(mod):
        obj = getattr(mod, name)
        targets = [obj]
        if isinstance(obj, type):
            targets.append(obj.__init__)
        for target in targets:
            try:
                sig = inspect.signature(target)
            except (TypeError, ValueError):
                continue
            param = sig.parameters.get('cli_kebab_case')
            if param is not None:
                defaults.append(param.default)

assert defaults and defaults[0] is True, 'docs say cli_kebab_case defaults to True'  # DOC-LITERAL
print('DOCS_OK')
