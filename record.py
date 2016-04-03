import ast
import copy
from functools import wraps
import inspect
import json
import os
import sys
import tempfile

from utils import strip_indent


RECORD_FN_NAME = '_record_state_fn_hidden_123'
DUMP_FN_NAME = '_dump_state_fn_hidden_123'
RETVAL_NAME = '_retval_hidden_123'
RECORD_STORE_NAME = '_record_store_hidden_123'

# Will be initialized in `record`.
_record_store_hidden_123 = None


def _record_state_fn_hidden_123(lineno, f_locals):
    """Stores local line data."""
    _record_store_hidden_123['data'].append((lineno, copy.deepcopy(f_locals)))


# http://stackoverflow.com/a/12240419
# TL;DR need this because the decorator would
# recursively apply on the new generated function.
_blocked = False
def record(f):
    """Transforms `f` such that after every line record_state is called."""

    # Make sure this is not a recursive decorator application.
    global _blocked
    if _blocked:
        return f

    parsed = ast.parse(strip_indent(inspect.getsource(f)))
    original_body = list(parsed.body[0].body)

    # Update body
    parsed.body[0].body = _fill_body_with_record(original_body)

    # Compile and inject modified function back into its env.
    new_f_compiled = compile(parsed, '<string>', 'exec')
    env = sys.modules[f.__module__].__dict__
    # We also need to inject our stuff in there.
    env[RECORD_FN_NAME] = globals()[RECORD_FN_NAME]

    _blocked = True
    exec(new_f_compiled, env)
    _blocked = False

    # Init record store.
    global _record_store_hidden_123
    _record_store_hidden_123 = {
        'data': []
    }

    # Wrap in our own function such that we can dump the recorded state at the end.
    @wraps(f)
    def wrapped(*args, **kwargs):
        ret = env[f.__name__](*args, **kwargs)
        dump_recorded_state()
        return ret

    return wrapped


def _make_record_state_call_expr(lineno):
    # Create locals() call.
    name = ast.Name(ctx=ast.Load(), id='locals', lineno=0, col_offset=0)
    locals_call = ast.Call(func=name, lineno=0, col_offset=0, args=[], keywords=[])

    # Create lineno constant arg.
    num = ast.Num(n=lineno, lineno=0, col_offset=0)

    # Create record_state call.
    name = ast.Name(ctx=ast.Load(), id=RECORD_FN_NAME, lineno=0, col_offset=0)
    call = ast.Call(func=name, lineno=0, col_offset=0,
                    args=[num, locals_call],
                    keywords=[])
    expr = ast.Expr(value=call, lineno=0, col_offset=0)

    return expr


def _make_return_trace_call_exprs(item):
    # Store retval in an aux var and return that instead.
    store_name = ast.Name(ctx=ast.Store(), id=RETVAL_NAME, col_offset=0, lineno=0)
    load_name = ast.Name(ctx=ast.Load(), id=RETVAL_NAME, col_offset=0, lineno=0)

    assign = ast.Assign(col_offset=0, targets=[store_name], value=item.value, lineno=0)
    ret = ast.Return(lineno=0, value=load_name, col_offset=0)

    return [
        assign,
        _make_record_state_call_expr(item.lineno),
        ret
    ]


def _fill_body_with_record(original_body, prepend=False, lineno=None):
    """Adds a record_state call after every item in the block.

    Recursive, works for nested bodies (e.g. if statements).

    `prepend` inserts a record_state call right at the start. We need this for
    recording the state on lines introducing nested blocks (`if`, `while` etc.)
    """
    new_body = []
    if prepend:
        assert lineno is not None, "Should've called prepend with a lineno."
        new_body.append(_make_record_state_call_expr(lineno))

    for item in original_body:

        # Handle return statements separately such that we capture retval as well.
        if isinstance(item, ast.Return):
            new_body.extend(_make_return_trace_call_exprs(item))
            continue

        has_nested = False
        # Look out for nested bodies.
        if hasattr(item, 'body'):
            has_nested = True
            new_nested_body = _fill_body_with_record(item.body, prepend=True, lineno=item.lineno)
            item.body = new_nested_body
        if hasattr(item, 'orelse'):
            has_nested = True
            # `else` does not have a lineno, using `if`'s lineno.
            new_nested_body = _fill_body_with_record(item.orelse, prepend=True, lineno=item.lineno)
            item.orelse = new_nested_body

        new_body.append(item)
        # Don't append a call after the end of the nested body, it's redundant.
        if not has_nested:
            new_body.append(_make_record_state_call_expr(item.lineno))

    return new_body


def dump_recorded_state():
    fd, path = tempfile.mkstemp(prefix='record_', suffix='.json')
    handle = os.fdopen(fd, 'w')
    json.dump(_record_store_hidden_123, handle)
    handle.close()
    print "Recorded execution in", path
