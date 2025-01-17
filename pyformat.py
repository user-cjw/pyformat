#!/usr/bin/env python

# Copyright (C) 2013-2017 Steven Myint
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""Formats Python code to follow a consistent style."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import io
from pathlib import Path
import signal
import sys
from typing import Tuple

from add_trailing_comma._main import _fix_src as add_trailing_comma_to_code
import autoflake
import autopep8
import docformatter
import inspect
import isort
import unify


__version__ = '1.0a0'


def formatters(aggressive, apply_config, filename='',
               remove_all_unused_imports=False, remove_unused_variables=False,
               sort_imports=False,
               add_trailing_comma=False):
    """Return list of code formatters."""
    if aggressive:
        yield lambda code: autoflake.fix_code(
            code,
            remove_all_unused_imports=remove_all_unused_imports,
            remove_unused_variables=remove_unused_variables)
        if add_trailing_comma:
            yield lambda code: add_trailing_comma_to_code(code, min_version=(3, 6))

        autopep8_options = autopep8.parse_args(
            [filename] + int(aggressive) * ['--aggressive'],
            apply_config=apply_config)
    else:
        autopep8_options = autopep8.parse_args(
            [filename], apply_config=apply_config)

    yield lambda code: autopep8.fix_code(code, options=autopep8_options)
    if any(x[0]=='Formatter' for x in inspect.getmembers(docformatter)):
        configurator = docformatter.Configurater(["docformatter","-"])
        configurator.do_parse_arguments()
        yield docformatter.Formatter(configurator.args, None, None, None)._do_format_code
    else:
        yield docformatter.format_code
    yield unify.format_code
    if sort_imports:
        yield _format_by_isort


def _format_by_isort(code):
    config_dict = {
        'settings_path': Path('.').resolve().absolute()
    }
    config = isort.Config(**config_dict)
    return isort.code(code=code, config=config)


def format_code(source, aggressive=False, apply_config=False, filename='',
                remove_all_unused_imports=False,
                remove_unused_variables=False, sort_imports=False,
                add_trailing_comma=False):
    """Return formatted source code."""
    formatted_source = source

    for fix in formatters(
            aggressive, apply_config, filename,
            remove_all_unused_imports, remove_unused_variables, sort_imports,
            add_trailing_comma):
        formatted_source = fix(formatted_source)

    return formatted_source


def detect_io_encoding(input_file: io.BytesIO, limit_byte_check=-1):
    """Return file encoding."""
    try:
        from lib2to3.pgen2 import tokenize as lib2to3_tokenize
        encoding: str = lib2to3_tokenize.detect_encoding(input_file.readline)[
            0]

        input_file.read(limit_byte_check).decode(encoding)

        return encoding
    except (LookupError, SyntaxError, UnicodeDecodeError):
        return 'latin-1'


def read_file(filename: str) -> Tuple[str, str]:
    """Read file from filesystem or from stdin when `-` is given."""

    if is_stdin(filename):
        data = sys.stdin.buffer.read()
    else:
        with open(filename, 'rb') as fp:
            data = fp.read()
    input_file = io.BytesIO(data)
    encoding = detect_io_encoding(input_file)
    return data.decode(encoding), encoding


def is_stdin(filename: str):
    return filename == '-'


def format_file(filename, args, standard_out):
    """Run format_code() on a file.

    Return True if the new formatting differs from the original.
    """
    source, encoding = read_file(filename)

    if not source:
        return False

    formatted_source = format_code(
        source,
        aggressive=args.aggressive,
        apply_config=args.config,
        filename=filename,
        remove_all_unused_imports=args.remove_all_unused_imports,
        remove_unused_variables=args.remove_unused_variables,
        sort_imports=args.sort_imports,
        add_trailing_comma=args.add_trailing_comma)

    # Always write to stdout (even when no changes were made) when working with
    # in-place stdin. This is what most tools (editors) expect.
    if args.in_place and is_stdin(filename):
        standard_out.write(formatted_source)
        return True

    if source != formatted_source:
        if args.in_place:
            with autopep8.open_with_encoding(filename, mode='w',
                                             encoding=encoding) as output_file:
                output_file.write(formatted_source)
        else:
            diff = autopep8.get_diff_text(
                io.StringIO(source).readlines(),
                io.StringIO(formatted_source).readlines(),
                filename)
            standard_out.write(''.join(diff))

        return True

    return False


def _format_file(parameters):
    """Helper function for optionally running format_file() in parallel."""
    (filename, args, _, standard_error) = parameters

    standard_error = standard_error or sys.stderr

    if args.verbose:
        print('{0}: '.format(filename), end='', file=standard_error)

    try:
        changed = format_file(*parameters[:-1])
    except IOError as exception:
        print('{}'.format(exception), file=standard_error)
        return (False, True)
    except KeyboardInterrupt:  # pragma: no cover
        return (False, True)  # pragma: no cover

    if args.verbose:
        print('changed' if changed else 'unchanged', file=standard_error)

    return (changed, False)


def format_multiple_files(filenames, args, standard_out, standard_error):
    """Format files and return booleans (any_changes, any_errors).

    Optionally format files recursively.
    """
    filenames = autopep8.find_files(list(filenames),
                                    args.recursive,
                                    args.exclude_patterns)
    if args.jobs > 1:
        import multiprocessing
        pool = multiprocessing.Pool(args.jobs)

        # We pass neither standard_out nor standard_error into "_format_file()"
        # since multiprocessing cannot serialize io.
        result = pool.map(_format_file,
                          [(name, args, None, None) for name in filenames])
    else:
        result = [_format_file((name, args, standard_out, standard_error))
                  for name in filenames]

    return (any(changed_and_error[0] for changed_and_error in result),
            any(changed_and_error[1] for changed_and_error in result))


def parse_args(argv):
    """Return parsed arguments."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, prog='pyformat')
    parser.add_argument('-i', '--in-place', action='store_true',
                        help='make changes to files instead of printing diffs')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='drill down directories recursively')
    parser.add_argument('-a', '--aggressive', action='count', default=0,
                        help='use more aggressive formatters')
    parser.add_argument('--remove-all-unused-imports', action='store_true',
                        help='remove all unused imports, '
                             'not just standard library '
                             '(requires "aggressive")')
    parser.add_argument('--remove-unused-variables', action='store_true',
                        help='remove unused variables (requires "aggressive")')
    parser.add_argument('--sort-imports', action='store_true',
                        help='sort imports')
    parser.add_argument('--add-trailing-comma', action='store_true',
                        help='add trailing comma to code (requires "aggressive")')
    parser.add_argument('-j', '--jobs', type=int, metavar='n', default=1,
                        help='number of parallel jobs; '
                             'match CPU count if value is less than 1')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='print verbose messages')
    parser.add_argument('--exclude', action='append',
                        dest='exclude_patterns', default=[], metavar='pattern',
                        help='exclude files this pattern; '
                             'specify this multiple times for multiple '
                             'patterns')
    parser.add_argument('--no-config', action='store_false', dest='config',
                        help="don't look for and apply local configuration "
                             'files; if not passed, defaults are updated with '
                             "any config files in the project's root "
                             'directory')
    parser.add_argument('--version', action='version',
                        version='%(prog)s ' + __version__)
    parser.add_argument('files', nargs='+', help='files to format')

    args = parser.parse_args(argv[1:])

    if args.jobs < 1:
        import multiprocessing
        args.jobs = multiprocessing.cpu_count()

    return args


def _main(argv, standard_out, standard_error):
    """Internal main entry point.

    Return exit status. 0 means no error.
    """
    args = parse_args(argv)

    if args.jobs > 1 and not args.in_place:
        print('parallel jobs requires --in-place',
              file=standard_error)
        return 2

    if not args.aggressive:
        if args.remove_all_unused_imports:
            print('--remove-all-unused-imports requires --aggressive',
                  file=standard_error)
            return 2

        if args.remove_unused_variables:
            print('--remove-unused-variables requires --aggressive',
                  file=standard_error)
            return 2

        if args.add_trailing_comma:
            print('--add-trailing-comma requires --aggressive',
                  file=standard_error)
            return 2

    changed_and_error = format_multiple_files(set(args.files),
                                              args,
                                              standard_out,
                                              standard_error)
    return 1 if changed_and_error[1] else 0


def main():
    """Main entry point."""
    try:
        # Exit on broken pipe.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except AttributeError:  # pragma: no cover
        # SIGPIPE is not available on Windows.
        pass

    try:
        return _main(sys.argv,
                     standard_out=sys.stdout,
                     standard_error=sys.stderr)
    except KeyboardInterrupt:  # pragma: no cover
        return 2  # pragma: no cover


if __name__ == '__main__':
    sys.exit(main())
