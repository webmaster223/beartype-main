#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2023 Beartype authors.
# See "LICENSE" for further details.

'''
**Unmemoized beartype decorators** (i.e., core lower-level unmemoized decorators
underlying the higher-level memoized :func:`beartype.beartype` decorator, whose
implementation in the parent :mod:`beartype._decor.decorcache` submodule
is a thin wrapper efficiently memoizing closures internally created and returned
by that decorator; in turn, those closures directly defer to this submodule).

This private submodule is effectively the :func:`beartype.beartype` decorator
despite *not* actually being that decorator (due to being unmemoized).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeException,
    BeartypeDecorWrappeeException,
)
from beartype._cave._cavefast import MethodDecoratorBuiltinTypes
from beartype._cave._cavemap import NoneTypeOr
from beartype._conf.confcls import BeartypeConf
from beartype._data.cls.datacls import TYPES_BEARTYPEABLE
from beartype._data.hint.datahinttyping import (
    BeartypeableT,
    TypeStack,
)
from beartype._decor._decormore import (
    beartype_descriptor_decorator_builtin,
    beartype_func,
    beartype_func_contextlib_contextmanager,
    beartype_pseudofunc,
)
from beartype._util.cls.utilclstest import is_type_subclass
from beartype._util.func.mod.utilfuncmodtest import (
    is_func_contextlib_contextmanager,
)
from beartype._util.func.utilfunctest import (
    is_func_python,
)
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_10
# from beartype._util.text.utiltextansi import strip_text_ansi
from beartype._util.text.utiltextlabel import label_object_context
from beartype._util.text.utiltextmunge import (
    truncate_str,
    uppercase_str_char_first,
)
from beartype._util.text.utiltextprefix import prefix_beartypeable
from traceback import format_exc
from warnings import warn

# ....................{ DECORATORS                         }....................
def beartype_object(
    # Mandatory parameters.
    obj: BeartypeableT,
    conf: BeartypeConf,

    # Variadic keyword parameters.
    **kwargs
) -> BeartypeableT:
    '''
    Decorate the passed **beartypeable** (i.e., caller-defined object that may
    be decorated by the :func:`beartype.beartype` decorator) with optimal
    type-checking dynamically generated unique to that beartypeable.

    Parameters
    ----------
    obj : BeartypeableT
        **Beartypeable** (i.e., pure-Python callable or class) to be decorated.
    conf : BeartypeConf
        **Beartype configuration** (i.e., dataclass encapsulating all flags,
        options, settings, and other metadata configuring the current decoration
        of the decorated callable or class).

    All remaining keyword parameters are passed as is to whichever lower-level
    decorator this higher-level decorator calls on the passed beartypeable.

    Returns
    ----------
    BeartypeableT
        Either:

        * If the passed object is a class, this existing class embellished with
          dynamically generated type-checking.
        * If the passed object is a callable, a new callable wrapping that
          callable with dynamically generated type-checking.

    See Also
    ----------
    :func:`beartype._decor.decormain.beartype`
        Memoized parent decorator wrapping this unmemoized child decorator.
    '''
    # print(f'Decorating object {repr(obj)}...')

    # Return either...
    return (
        _beartype_object_fatal(obj, conf, **kwargs)
        # If this beartype configuration requests that this decorator raise
        # fatal exceptions at decoration time, defer to the lower-level
        # decorator doing so;
        if conf.warning_cls_on_decorator_exception is None else
        # Else, this beartype configuration requests that this decorator emit
        # fatal warnings at decoration time. In this case, defer to the
        # lower-level decorator doing so.
        _beartype_object_nonfatal(obj, conf, **kwargs)
    )

# ....................{ PRIVATE ~ decorators               }....................
def _beartype_object_fatal(
    # Mandatory parameters.
    obj: BeartypeableT,
    conf: BeartypeConf,

    # Optional parameters.
    cls_stack: TypeStack = None,
) -> BeartypeableT:
    '''
    Decorate the passed **beartypeable** (i.e., caller-defined object that may
    be decorated by the :func:`beartype.beartype` decorator) with optimal
    type-checking dynamically generated unique to that beartypeable.

    Parameters
    ----------
    obj : BeartypeableT
        **Beartypeable** (i.e., pure-Python callable or class) to be decorated.
    conf : BeartypeConf
        **Beartype configuration** (i.e., dataclass encapsulating all flags,
        options, settings, and other metadata configuring the current decoration
        of the decorated callable or class).
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.

    Returns
    ----------
    BeartypeableT
        Either:

        * If the passed object is a class, this existing class embellished with
          dynamically generated type-checking.
        * If the passed object is a callable, a new callable wrapping that
          callable with dynamically generated type-checking.

    See Also
    ----------
    :func:`beartype._decor.decormain.beartype`
        Memoized parent decorator wrapping this unmemoized child decorator.
    '''

    # If this object is a class, return this class decorated with type-checking.
    #
    # Note that the passed "cls_curr" class is ignorable in this context.
    # Why? There are three cases. "obj" is either a:
    # * Root decorated class, in which case both "cls_root" and
    #   "cls_curr" are "None". Ergo, "cls_curr" conveys *NO*
    #   meaningful semantics.
    # * Inner decorated class of a root decorated class, in which case both
    #   "cls_root" and "cls_curr" refer to that root decorated case.
    #   Ergo, "cls_curr" conveys *NO* additional meaningful semantics.
    # * Leaf decorated class of an inner decorated class of a root decorated
    #   class, in which case "cls_root" and "cls_curr" refer to
    #   different classes. However, lexical scoping rules in Python prevent
    #   leaf classes from directly referring to any parent classes *OTHER* than
    #   module-scoped root classes. Ergo, "cls_curr" conveys *NO*
    #   meaningful semantics again.
    #
    # In all cases, "cls_curr" conveys *NO* meaningful semantics.
    if isinstance(obj, type):
        # print(f'Decorating type {repr(obj)}...')
        return _beartype_type(  # type: ignore[return-value]
            cls=obj,
            conf=conf,
            cls_stack=cls_stack,
        )
    # Else, this object is a non-class.
    # print(f'Decorating non-type {repr(obj)}...')

    # Type of this object.
    obj_type = type(obj)

    # If this object is an uncallable builtin method descriptor (i.e., either a
    # property, class method, instance method, or static method object),
    # @beartype was listed above rather than below the builtin decorator
    # generating this descriptor in the chain of decorators decorating this
    # decorated callable. Although @beartype typically *MUST* decorate a
    # callable directly, this edge case is sufficiently common *AND* trivial to
    # resolve to warrant doing so. To do so, this conditional branch effectively
    # reorders @beartype to be the first decorator decorating the pure-Python
    # function underlying this method descriptor: e.g.,
    #
    #     # This branch detects and reorders this edge case...
    #     class MuhClass(object):
    #         @beartype
    #         @classmethod
    #         def muh_classmethod(cls) -> None: pass
    #
    #     # ...to resemble this direct decoration instead.
    #     class MuhClass(object):
    #         @classmethod
    #         @beartype
    #         def muh_classmethod(cls) -> None: pass
    #
    # Note that most but *NOT* all of these objects are uncallable. Regardless,
    # *ALL* of these objects are unsuitable for direct decoration. Specifically:
    # * Under Python < 3.10, *ALL* of these objects are uncallable.
    # * Under Python >= 3.10:
    #   * Descriptors created by @classmethod and @property are uncallable.
    #   * Descriptors created by @staticmethod are technically callable but
    #     C-based and thus unsuitable for decoration.
    if obj_type in MethodDecoratorBuiltinTypes:
        return beartype_descriptor_decorator_builtin(  # type: ignore[return-value]
            descriptor=obj,
            conf=conf,
            cls_stack=cls_stack,
        )
    # Else, this object is *NOT* an uncallable builtin method descriptor.
    #
    # If this object is uncallable, raise an exception.
    elif not callable(obj):
        raise BeartypeDecorWrappeeException(
            f'Uncallable {repr(obj)} not decoratable by @beartype.')
    # Else, this object is callable.
    #
    # If this object is *NOT* a pure-Python function, this object is a
    # pseudo-callable (i.e., arbitrary pure-Python *OR* C-based object whose
    # class defines the __call__() dunder method enabling this object to be
    # called like a standard callable). In this case, attempt to monkey-patch
    # runtime type-checking into this pure-Python callable by replacing the
    # bound method descriptor of the type of this object implementing the
    # __call__() dunder method with a comparable descriptor calling a
    # @beartype-generated runtime type-checking wrapper function.
    elif not is_func_python(obj):
        return beartype_pseudofunc(  # type: ignore[return-value]
            pseudofunc=obj,
            conf=conf,
            cls_stack=cls_stack,
        )
    # Else, this object is a pure-Python function.
    #
    # If this function is a @contextlib.contextmanager-based isomorphic
    # decorator closure (i.e., closure both created and returned by the standard
    # @contextlib.contextmanager decorator where that closure isomorphically
    # preserves both the number and types of all passed parameters and returns
    # by accepting only a variadic positional argument and variadic keyword
    # argument), @beartype was listed above rather than below the
    # @contextlib.contextmanager decorator creating and returning this closure
    # in the chain of decorators decorating this decorated callable. This is
    # non-ideal, as the type of *ALL* objects created and returned by
    # @contextlib.contextmanager-decorated context managers is a private class
    # of the "contextlib" module rather than the types implied by the type hints
    # originally annotating the returns of those context managers. If @beartype
    # did *not* actively detect and intervene in this edge case, then runtime
    # type-checkers dynamically generated by @beartype for those managers would
    # erroneously raise type-checking violations after calling those managers
    # and detecting the apparent type violation: e.g.,
    #
    #     >>> from beartype.typing import Iterator
    #     >>> from contextlib import contextmanager
    #     >>> @contextmanager
    #     ... def muh_context_manager() -> Iterator[None]: yield
    #     >>> type(muh_context_manager())
    #     <class 'contextlib._GeneratorContextManager'>  # <-- not an "Iterator"
    #
    # This conditional branch effectively reorders @beartype to be the first
    # decorator decorating the callable underlying this context manager,
    # preserving consistency between return types *AND* return type hints: e.g.,
    #
    #     from beartype.typing import Iterator
    #     from contextlib import contextmanager
    #
    #     # This branch detects and reorders this edge case...
    #     @beartype
    #     @contextmanager
    #     def muh_contextmanager(cls) -> Iterator[None]: yield
    #
    #     # ...to resemble this direct decoration instead.
    #     @contextmanager
    #     @beartype
    #     def muh_contextmanager(cls) -> Iterator[None]: yield
    elif is_func_contextlib_contextmanager(obj):
        return beartype_func_contextlib_contextmanager(  # type: ignore[return-value]
            func=obj,
            conf=conf,
            cls_stack=cls_stack,
        )
    # Else, this function is *NOT* a @contextlib.contextmanager-based isomorphic
    # decorator closure.

    # Return a new callable decorating that callable with type-checking.
    return beartype_func(  # type: ignore[return-value]
        func=obj,
        conf=conf,
        cls_stack=cls_stack,
    )


#FIXME: Unit test us up, please.
def _beartype_object_nonfatal(
    # Mandatory parameters.
    obj: BeartypeableT,
    conf: BeartypeConf,

    # Variadic keyword parameters.
    **kwargs
) -> BeartypeableT:
    '''
    Decorate the passed **beartypeable** (i.e., pure-Python callable or class)
    with optimal type-checking dynamically generated unique to that
    beartypeable and any otherwise uncaught exception raised by doing so safely
    coerced into a warning instead.

    Motivation
    ----------
    This decorator is principally intended to be called by our **import hook
    API** (i.e., public functions exported by the :mod:`beartype.claw`
    subpackage). Raising detailed exception tracebacks on unexpected error
    conditions is:

    * The right thing to do for callables and classes manually type-checked with
      the :func:`beartype.beartype` decorator.
    * The wrong thing to do for callables and classes automatically type-checked
      by import hooks installed by public functions exported by the
      :mod:`beartype.claw` subpackage. Why? Because doing so would render those
      import hooks fragile to the point of being practically useless on
      real-world packages and codebases by unexpectedly failing on the first
      callable or class defined *anywhere* under a package that is not
      type-checkable by :func:`beartype.beartype` (whether through our fault or
      that package's). Instead, the right thing to do is to:

      * Emit a warning for each callable or class that :func:`beartype.beartype`
        fails to generate a type-checking wrapper for.
      * Continue to the next callable or class.

    Parameters
    ----------
    obj : BeartypeableT
        **Beartypeable** (i.e., pure-Python callable or class) to be decorated.
    conf : BeartypeConf
        **Beartype configuration** (i.e., dataclass encapsulating all flags,
        options, settings, and other metadata configuring the current decoration
        of the decorated callable or class).

    All remaining keyword parameters are passed as is to the lower-level
    :func:`._beartype_object_fatal` decorator internally called by this
    higher-level decorator on the passed beartypeable.

    Returns
    ----------
    BeartypeableT
        Either:

        * If :func:`.beartype_object` raises an exception, the passed object
          unmodified as is.
        * If :func:`.beartype_object` raises no exception:

          * If the passed object is a class, this existing class embellished with
            dynamically generated type-checking.
          * If the passed object is a callable, a new callable wrapping that
            callable with dynamically generated type-checking.

    Warns
    ----------
    warning_category
        If :func:`.beartype_object` fails to generate a type-checking wrapper
        for this callable or class by raising a fatal exception, this function
        coerces that exception into a non-fatal warning describing that error.
    '''

    # Attempt to decorate the passed beartypeable.
    try:
        return _beartype_object_fatal(obj, conf, **kwargs)
    # If doing so unexpectedly raises an exception, coerce that fatal exception
    # into a non-fatal warning for nebulous safety.
    except Exception as exception:
        # Category of warning to be emitted.
        warning_category = conf.warning_cls_on_decorator_exception
        assert is_type_subclass(warning_category, Warning), (
            f'{repr(warning_category)} not warning category.')

        # Original error message to be embedded in the warning message to be
        # emitted, stripped of *ALL* ANSI color. While colors improve the
        # readability of exception messages that percolate down to an ANSI-aware
        # command line, warnings are usually harvested and then regurgitated by
        # intermediary packages into ANSI-unaware logfiles.
        #
        # This message is defined as either...
        error_message = (
            # If this exception is beartype-specific, this exception's message
            # is probably human-readable as is. In this case, maximize brevity
            # and readability by coercing *ONLY* this message (rather than both
            # this message *AND* traceback) truncated to a reasonable maximum
            # length into a warning message.
            truncate_str(text=str(exception), max_len=1024)
            if isinstance(exception, BeartypeException) else
            # Else, this exception is *NOT* beartype-specific. In this case,
            # this exception's message is probably *NOT* human-readable as is.
            # Prepend that non-human-readable message by this exception's
            # traceback for disambiguity and debuggability. Note that the
            # format_exc() function appends this exception's message to this
            # traceback and thus suffices as is.
            format_exc()
        )

        # Indent this exception message by globally replacing *EVERY* newline in
        # this message with a newline followed by four spaces. Doing so visually
        # offsets this lower-level exception message from the higher-level
        # warning message embedding this exception message below.
        error_message = error_message.replace('\n', '\n    ')

        # Warning message to be emitted, consisting of:
        # * A human-readable label contextually describing this beartypeable,
        #   capitalized such that the first character is uppercase.
        # * This indented exception message.
        warning_message = uppercase_str_char_first(
            f'{prefix_beartypeable(obj)}{label_object_context(obj)}:\n'
            f'{error_message}'
        )

        # Emit this message under this category.
        warn(warning_message, warning_category)

    # Return this object unmodified, as @beartype failed to successfully wrap
    # this object with a type-checking class or callable. So it goes, fam.
    return obj  # type: ignore[return-value]

# ....................{ PRIVATE ~ decorators : type        }....................
def _beartype_type(
    # Mandatory parameters.
    cls: BeartypeableT,
    conf: BeartypeConf,

    # Optional parameters.
    cls_stack: TypeStack = None,
) -> BeartypeableT:
    '''
    Decorate the passed class with dynamically generated type-checking.

    Parameters
    ----------
    cls : BeartypeableT
        Class to be decorated by :func:`beartype.beartype`.
    conf : BeartypeConf
        Beartype configuration configuring :func:`beartype.beartype` uniquely
        specific to this class.
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.

    Returns
    ----------
    BeartypeableT
        This class decorated by :func:`beartype.beartype`.
    '''
    assert isinstance(cls, type), f'{repr(cls)} not type.'
    assert isinstance(cls_stack, NoneTypeOr[tuple]), (
        f'{repr(cls_stack)} neither tuple nor "None".')
    # assert isinstance(conf, BeartypeConf), f'{repr(conf)} not configuration.'

    #FIXME: Insufficient. We also want to set a beartype-specific dunder
    #attribute -- say, "__beartyped" -- on this class. Additionally, if this
    #class has already been @beartyped, we want to detect that here and avoid
    #re-@beartype-ing this class. In short, we want to generalize our existing
    #"beartype._util.func.mod.utilbeartypefunc" submodule to support classes as
    #well. Let's shift that submodule somewhere more general, please. Perhaps:
    #* Rename "beartype._util.func.mod.utilbeartypefunc" to
    #  "beartype._util.check.utilcheckfunc".
    #* Define a new "beartype._util.check.utilchecktype" submodule containing
    #  similar class-specific functionality.
    #FIXME: Actually... *NO.* We absolutely do *NOT* want to monkey-patch random
    #@beartype-specific attributes into user-defined classes, because then the
    #Python ecosystem will shudder, then sway, then crack, and finally tumble
    #into the churning seas below. Instead, let's find something *ELSE* that is
    #actually safe to monkey-patch. Method objects are the classic example.
    #Nobody cares if we monkey-patch those. The most common method object would
    #be the "cls.__init__" object. Of course, many types do *NOT* define that
    #object -- but many types also do. We could simply:
    #* Decide whether the "cls.__init__" method exists.
    #* Decide whether the "cls.__init__.__beartyped_cls" attribute exists. Note
    #  that this attribute is distinct from our existing "__beartyped"
    #  attribute, when records a lower-level and less useful truth.
    #
    #For example:
    #    is_type_beartyped = getattr(
    #        getattr(cls, '__init__', None), '__beartyped_cls', False)
    #
    #Pretty sure that suffices. It's just a simple two-liner. This is only an
    #optimization, so it doesn't particularly matter if it fails to apply to
    #some classes. So, let's a-go!

    #FIXME: Unit test us up, please. Test against at least:
    #* A dataclass. We already do this, of course. Hurrah!
    #* An uncallable class (i.e., defining *NO* __call__() dunder method)
    #  defining at least:
    #  * A class variable (e.g., "muh_classvar: ClassVar[int] = 42").
    #  * A standard instance method.
    #  * A class method.
    #  * A static method.
    #  * A property getter, setter, and deleter.
    #* A callable class (i.e., defining a __call__() dunder method).
    #* A PEP 563-fueled self-referential class. See this as a simple example:
    #     https://github.com/beartype/beartype/issues/152#issuecomment-1197778501

    # Replace the passed class stack with a new class stack appending this
    # decorated class to the top of this stack, reflecting the fact that this
    # decorated class is now the most deeply lexically nested class for the
    # currently recursive chain of @beartype-decorated classes.
    cls_stack = (
        # If the caller passed *NO* class stack, then this class is necessarily
        # the first decorated class being decorated directly by @beartype and
        # thus the root decorated class.
        #
        # Note this is the common case and thus tested first. Since nested
        # classes effectively do *NOT* exist in the wild, this comprises
        # 99.999% of all real-world cases.
        (cls,)
        if cls_stack is None else
        # Else, the caller passed a clack stack comprising at least a root
        # decorated class. Preserve that class as is to properly expose that
        # class elsewhere.
        cls_stack + (cls,)
    )

    # For the unqualified name and value of each direct (i.e., *NOT* indirectly
    # inherited) attribute of this class...
    for attr_name, attr_value in cls.__dict__.items():  # pyright: ignore[reportGeneralTypeIssues]
        # If this attribute is beartypeable...
        if isinstance(attr_value, TYPES_BEARTYPEABLE):
            # This attribute decorated with type-checking configured by this
            # configuration if *NOT* already decorated.
            attr_value_beartyped = beartype_object(
                obj=attr_value,
                conf=conf,
                cls_stack=cls_stack,
            )

            # Attempt to...
            try:
                # Replace this undecorated attribute with this decorated
                # attribute.
                #
                # Note that class attributes are *ONLY* settable by calling the
                # tragically slow setattr() builtin. Attempting to directly set
                # an attribute on the class dictionary raises an exception. Why?
                # Because class dictionaries are actually low-level
                # "mappingproxy" objects that intentionally override the
                # __setattr__() dunder method to unconditionally raise an
                # exception. Why? Because that constraint enables the
                # type.__setattr__() dunder method to enforce critical
                # efficiency constraints on class attributes -- including that
                # class attribute keys are *NOT* only strings but also valid
                # Python identifiers:
                #     >>> class OhGodHelpUs(object): pass
                #     >>> OhGodHelpUs.__dict__['even_god_cannot_help'] = 2
                #     TypeError: 'mappingproxy' object does not support item
                #     assignment
                #
                # See also this relevant StackOverflow answer by Python luminary
                # Raymond Hettinger:
                #     https://stackoverflow.com/a/32720603/2809027
                setattr(cls, attr_name, attr_value_beartyped)
            # If doing so raises a builtin "TypeError"...
            except TypeError as exception:
                #FIXME: Shift this detection logic into a new
                #is_typeerror_attr_immutable() tester, please.

                # Message raised with this "TypeError".
                exception_message = str(exception)

                # If this message satisfies a pattern , then this "TypeError" signifies this attribute
                # to be inherited from an immutable builtin type (e.g., "str")
                # subclassed by this user-defined subclass. In this case,
                # silently skip past this uncheckable attribute to the next.
                #
                # Note that this pattern depends on the current Python version.
                if (
                    # The active Python interpreter targets Python >= 3.10,
                    # match a message of the form "cannot set '{attr_name}'
                    # attribute of immutable type '{cls_name}'".
                    IS_PYTHON_AT_LEAST_3_10 and (
                        exception_message.startswith("cannot set '") and
                        "' attribute of immutable type " in exception_message
                    # Else, the active Python interpreter targets Python <= 3.9.
                    # In this case, match a message of the form "can't set
                    # attributes of built-in/extension type '{cls_name}'".
                    ) or exception_message.startswith(
                        "can't set attributes of built-in/extension type '")
                ):
                    continue
                # Else, this message does *NOT* satisfy that pattern.

                # Preserve this exception by re-raising this exception.
                raise
        # Else, this attribute is *NOT* beartypeable. In this case, silently
        # ignore this attribute.

    # Return this class as is.
    return cls  # type: ignore[return-value]
