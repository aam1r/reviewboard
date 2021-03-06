from __future__ import with_statement
import fnmatch
import os
import re
import subprocess
import tempfile
from difflib import SequenceMatcher

try:
    import pygments
    from pygments.lexers import get_lexer_for_filename
    # from pygments.lexers import guess_lexer_for_filename
    from pygments.formatters import HtmlFormatter
except ImportError:
    pass

from django.utils.html import escape
from django.utils.http import urlquote
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext as _

from djblets.log import log_timed
from djblets.siteconfig.models import SiteConfiguration
from djblets.util.contextmanagers import controlled_subprocess
from djblets.util.misc import cache_memoize

from reviewboard.accounts.models import Profile
from reviewboard.admin.checks import get_can_enable_syntax_highlighting
from reviewboard.diffviewer.myersdiff import MyersDiffer
from reviewboard.diffviewer.smdiff import SMDiffer
from reviewboard.scmtools.core import PRE_CREATION, HEAD


# The maximum size a line can be before we start shutting off styling.
STYLED_MAX_LINE_LEN = 1000
STYLED_MAX_LIMIT_BYTES = 200000 # 200KB

DEFAULT_DIFF_COMPAT_VERSION = 1

NEW_FILE_STR = _("New File")
NEW_CHANGE_STR = _("New Change")

NEWLINES_RE = re.compile(r'\r?\n')
NEWLINE_CONVERSION_RE = re.compile(r'\r(\r?\n)?')

ALPHANUM_RE = re.compile(r'\w')
WHITESPACE_RE = re.compile(r'\s')


# A list of regular expressions for headers in the source code that we can
# display in collapsed regions of diffs and diff fragments in reviews.
HEADER_REGEXES = {
    '.cs': [
        re.compile(
            r'^\s*((public|private|protected|static)\s+)+'
            r'([a-zA-Z_][a-zA-Z0-9_\.\[\]]*\s+)+?'     # return arguments
            r'[a-zA-Z_][a-zA-Z0-9_]*'                  # method name
            r'\s*\('                                   # signature start
        ),
        re.compile(
            r'^\s*('
            r'(public|static|private|protected|internal|abstract|partial)'
            r'\s+)*'
            r'(class|struct)\s+([A-Za-z0-9_])+'
        ),
    ],

    # This can match C/C++/Objective C header files
    '.c': [
        re.compile(r'^@(interface|implementation|class|protocol)'),
        re.compile(r'^[A-Za-z0-9$_]'),
    ],
    '.java': [
        re.compile(
            r'^\s*((public|private|protected|static)\s+)+'
            r'([a-zA-Z_][a-zA-Z0-9_\.\[\]]*\s+)+?'     # return arguments
            r'[a-zA-Z_][a-zA-Z0-9_]*'                  # method name
            r'\s*\('                                   # signature start
        ),
        re.compile(
            r'^\s*('
            r'(public|static|private|protected)'
            r'\s+)*'
            r'(class|struct)\s+([A-Za-z0-9_])+'
        ),
    ],
    '.js': [
        re.compile(r'^\s*function [A-Za-z0-9_]+\s*\('),
        re.compile(r'^\s*(var\s+)?[A-Za-z0-9_]+\s*[=:]\s*function\s*\('),
    ],
    '.m': [
        re.compile(r'^@(interface|implementation|class|protocol)'),
        re.compile(r'^[-+]\s+\([^\)]+\)\s+[A-Za-z0-9_]+[^;]*$'),
        re.compile(r'^[A-Za-z0-9$_]'),
    ],
    '.php': [
        re.compile(r'^\s*(class|function) [A-Za-z0-9_]+'),
    ],
    '.pl': [
        re.compile(r'^\s*sub [A-Za-z0-9_]+'),
    ],
    '.py': [
        re.compile(r'^\s*(def|class) [A-Za-z0-9_]+\s*\(?'),
    ],
    '.rb': [
        re.compile(r'^\s*(def|class) [A-Za-z0-9_]+\s*\(?'),
    ],
}

HEADER_REGEX_ALIASES = {
    # C/C++/Objective-C
    '.cc': '.c',
    '.cpp': '.c',
    '.cxx': '.c',
    '.c++': '.c',
    '.h': '.c',
    '.hh': '.c',
    '.hpp': '.c',
    '.hxx': '.c',
    '.h++': '.c',
    '.C': '.c',
    '.H': '.c',
    '.mm': '.m',

    # Perl
    '.pm': '.pl',

    # Python
    'SConstruct': '.py',
    'SConscript': '.py',
    '.pyw': '.py',
    '.sc': '.py',

    # Ruby
    'Rakefile': '.rb',
    '.rbw': '.rb',
    '.rake': '.rb',
    '.gemspec': '.rb',
    '.rbx': '.rb',
}


class UserVisibleError(Exception):
    pass


class DiffCompatError(Exception):
    pass


class NoWrapperHtmlFormatter(HtmlFormatter):
    """An HTML Formatter for Pygments that don't wrap items in a div."""
    def __init__(self, *args, **kwargs):
        super(NoWrapperHtmlFormatter, self).__init__(*args, **kwargs)

    def _wrap_div(self, inner):
        """
        Method called by the formatter to wrap the contents of inner.
        Inner is a list of tuples containing formatted code. If the first item
        in the tuple is zero, then it's a wrapper, so we should ignore it.
        """
        for tup in inner:
            if tup[0]:
                yield tup


def Differ(a, b, ignore_space=False,
           compat_version=DEFAULT_DIFF_COMPAT_VERSION):
    """
    Factory wrapper for returning a differ class based on the compat version
    and flags specified.
    """
    if compat_version == 0:
        return SMDiffer(a, b)
    elif compat_version == 1:
        return MyersDiffer(a, b, ignore_space)
    else:
        raise DiffCompatError(
            "Invalid diff compatibility version (%s) passed to Differ" %
                (compat_version))


def convert_line_endings(data):
    # Files without a trailing newline come out of Perforce (and possibly
    # other systems) with a trailing \r. Diff will see the \r and
    # add a "\ No newline at end of file" marker at the end of the file's
    # contents, which patch understands and will happily apply this to
    # a file with a trailing \r.
    #
    # The problem is that we normalize \r's to \n's, which breaks patch.
    # Our solution to this is to just remove that last \r and not turn
    # it into a \n.
    #
    # See http://code.google.com/p/reviewboard/issues/detail?id=386
    # and http://reviews.reviewboard.org/r/286/
    if data == "":
        return ""

    if data[-1] == "\r":
        data = data[:-1]

    return NEWLINE_CONVERSION_RE.sub('\n', data)


def patch(diff, file, filename):
    """Apply a diff to a file.  Delegates out to `patch` because noone
       except Larry Wall knows how to patch."""

    log_timer = log_timed("Patching file %s" % filename)

    if diff.strip() == "":
        # Someone uploaded an unchanged file. Return the one we're patching.
        return file

    # Prepare the temporary directory if none is available
    tempdir = tempfile.mkdtemp(prefix='reviewboard.')

    (fd, oldfile) = tempfile.mkstemp(dir=tempdir)
    f = os.fdopen(fd, "w+b")
    f.write(convert_line_endings(file))
    f.close()

    diff = convert_line_endings(diff)

    newfile = '%s-new' % oldfile

    process = subprocess.Popen(['patch', '-o', newfile, oldfile],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)

    with controlled_subprocess("patch", process) as p:
        p.stdin.write(diff)
        p.stdin.close()
        patch_output = p.stdout.read()
        failure = p.wait()

    if failure:
        f = open("%s.diff" %
                 (os.path.join(tempdir, os.path.basename(filename))), "w")
        f.write(diff)
        f.close()

        log_timer.done()

        # FIXME: This doesn't provide any useful error report on why the patch
        # failed to apply, which makes it hard to debug.  We might also want to
        # have it clean up if DEBUG=False
        raise Exception(_("The patch to '%s' didn't apply cleanly. The temporary " +
                          "files have been left in '%s' for debugging purposes.\n" +
                          "`patch` returned: %s") %
                        (filename, tempdir, patch_output))

    f = open(newfile, "r")
    data = f.read()
    f.close()

    os.unlink(oldfile)
    os.unlink(newfile)
    os.rmdir(tempdir)

    log_timer.done()

    return data


def get_line_changed_regions(oldline, newline):
    if oldline is None or newline is None:
        return (None, None)

    # Use the SequenceMatcher directly. It seems to give us better results
    # for this. We should investigate steps to move to the new differ.
    differ = SequenceMatcher(None, oldline, newline)

    # This thresholds our results -- we don't want to show inter-line diffs if
    # most of the line has changed, unless those lines are very short.

    # FIXME: just a plain, linear threshold is pretty crummy here.  Short
    # changes in a short line get lost.  I haven't yet thought of a fancy
    # nonlinear test.
    if differ.ratio() < 0.6:
        return (None, None)

    oldchanges = []
    newchanges = []
    back = (0, 0)

    for tag, i1, i2, j1, j2 in differ.get_opcodes():
        if tag == "equal":
            if (i2 - i1 < 3) or (j2 - j1 < 3):
                back = (j2 - j1, i2 - i1)
            continue

        oldstart, oldend = i1 - back[0], i2
        newstart, newend = j1 - back[1], j2

        if oldchanges != [] and oldstart <= oldchanges[-1][1] < oldend:
            oldchanges[-1] = (oldchanges[-1][0], oldend)
        elif not oldline[oldstart:oldend].isspace():
            oldchanges.append((oldstart, oldend))

        if newchanges != [] and newstart <= newchanges[-1][1] < newend:
            newchanges[-1] = (newchanges[-1][0], newend)
        elif not newline[newstart:newend].isspace():
            newchanges.append((newstart, newend))

        back = (0, 0)

    return (oldchanges, newchanges)


def convert_to_utf8(s, enc):
    """
    Returns the passed string as a unicode string. If conversion to UTF-8
    fails, we try the user-specified encoding, which defaults to ISO 8859-15.
    This can be overridden by users inside the repository configuration, which
    gives users repository-level control over file encodings (file-level control
    is really, really hard).
    """
    if isinstance(s, unicode):
        return s.encode('utf-8')
    elif isinstance(s, basestring):
        try:
            # First try strict unicode (for when everything is valid utf-8)
            return unicode(s, 'utf-8')
        except UnicodeError:
            # Now try any candidate encodings.
            for e in enc.split(','):
                try:
                    u = unicode(s, e)
                    return u.encode('utf-8')
                except UnicodeError:
                    pass

            # Finally, try to convert to straight unicode and replace all
            # unknown characters.
            try:
                return unicode(s, 'utf-8', errors='replace')
            except UnicodeError:
                raise Exception(_("Diff content couldn't be converted to UTF-8 "
                                  "using the following encodings: %s") % enc)
    else:
        raise TypeError("Value to convert is unexpected type %s", type(s))


def get_original_file(filediff):
    """
    Get a file either from the cache or the SCM, applying the parent diff if
    it exists.

    SCM exceptions are passed back to the caller.
    """
    data = ""

    if filediff.source_revision != PRE_CREATION:
        def fetch_file(file, revision):
            log_timer = log_timed("Fetching file '%s' r%s from %s" %
                                  (file, revision, repository))
            data = repository.get_file(file, revision)
            data = convert_line_endings(data)
            log_timer.done()
            return data

        repository = filediff.diffset.repository
        file = filediff.source_file
        revision = filediff.source_revision

        key = "%s:%s:%s" % (urlquote(filediff.diffset.repository.path),
                            urlquote(file), urlquote(revision))

        # We wrap the result of get_file in a list and then return the first
        # element after getting the result from the cache. This prevents the
        # cache backend from converting to unicode, since we're no longer
        # passing in a string and the cache backend doesn't recursively look
        # through the list in order to convert the elements inside.
        #
        # Basically, this fixes the massive regressions introduced by the
        # Django unicode changes.
        data = cache_memoize(key, lambda: [fetch_file(file, revision)],
                             large_data=True)[0]

    # If there's a parent diff set, apply it to the buffer.
    if filediff.parent_diff:
        data = patch(filediff.parent_diff, data, filediff.source_file)

    return data


def get_patched_file(buffer, filediff):
    tool = filediff.diffset.repository.get_scmtool()
    diff = tool.normalize_patch(filediff.diff, filediff.source_file,
                                filediff.source_revision)
    return patch(diff, buffer, filediff.dest_file)


def register_interesting_lines_for_filename(differ, filename):
    """Registers regexes for interesting lines to a differ based on filename.

    This will add watches for headers (functions, classes, etc.) to the diff
    viewer. The regular expressions used are based on the filename provided.
    """
    # Add any interesting lines we may want to show.
    regexes = []

    if file in HEADER_REGEX_ALIASES:
        regexes = HEADER_REGEXES[HEADER_REGEX_ALIASES[filename]]
    else:
        basename, ext = os.path.splitext(filename)

        if ext in HEADER_REGEXES:
            regexes = HEADER_REGEXES[ext]
        elif ext in HEADER_REGEX_ALIASES:
            regexes = HEADER_REGEXES[HEADER_REGEX_ALIASES[ext]]

    for regex in regexes:
        differ.add_interesting_line_regex('header', regex)


def compute_chunk_last_header(lines, numlines, meta, last_header=None):
    """Computes information for the displayed function/class headers.

    This will record the displayed headers, their line numbers, and expansion
    offsets relative to the header's collapsed line range.

    The last_header variable, if provided, will be modified, which is
    important when processing several chunks at once. It will also be
    returned as a convenience.
    """
    if last_header is None:
        last_header = [None, None]

    line = lines[0]

    for i, (linenum, header_key) in enumerate([(line[1], 'left_headers'),
                                               (line[4], 'right_headers')]):
        headers = meta[header_key]

        if headers:
            header = headers[-1]
            last_header[i] = {
                'line': header[0],
                'text': header[1].strip(),
            }

    return last_header


def get_chunks(diffset, filediff, interfilediff, force_interdiff,
               enable_syntax_highlighting):
    def diff_line(vlinenum, oldlinenum, newlinenum, oldline, newline,
                  oldmarkup, newmarkup):
        # This function accesses the variable meta, defined in an outer context.
        if (oldline and newline and
            len(oldline) <= STYLED_MAX_LINE_LEN and
            len(newline) <= STYLED_MAX_LINE_LEN and
            oldline != newline):
            oldregion, newregion = get_line_changed_regions(oldline, newline)
        else:
            oldregion = newregion = []

        result = [vlinenum,
                  oldlinenum or '', mark_safe(oldmarkup or ''), oldregion,
                  newlinenum or '', mark_safe(newmarkup or ''), newregion,
                  (oldlinenum, newlinenum) in meta['whitespace_lines']]

        if oldlinenum and oldlinenum in meta.get('moved', {}):
            destination = meta["moved"][oldlinenum]
            result.append(destination)
        elif newlinenum and newlinenum in meta.get('moved', {}):
            destination = meta["moved"][newlinenum]
            result.append(destination)

        return result

    def new_chunk(chunk_index, all_lines, start, end, collapsable=False,
                  tag='equal', meta=None):
        if not meta:
            meta = {}

        left_headers = list(get_interesting_headers(differ, all_lines,
                                                    start, end - 1, False))
        right_headers = list(get_interesting_headers(differ, all_lines,
                                                     start, end - 1, True))

        meta['left_headers'] = left_headers
        meta['right_headers'] = right_headers

        lines = all_lines[start:end]
        numlines = len(lines)

        compute_chunk_last_header(lines, numlines, meta, last_header)

        if (collapsable and end < len(all_lines) and
            (last_header[0] or last_header[1])):
            meta['headers'] = list(last_header)

        return {
            'index': chunk_index,
            'lines': lines,
            'numlines': numlines,
            'change': tag,
            'collapsable': collapsable,
            'meta': meta,
        }

    def get_interesting_headers(differ, lines, start, end, is_modified_file):
        """Returns all headers for a region of a diff.

        This scans for all headers that fall within the specified range
        of the specified lines on both the original and modified files.
        """
        possible_functions = differ.get_interesting_lines('header',
                                                          is_modified_file)

        if not possible_functions:
            raise StopIteration

        try:
            if is_modified_file:
                last_index = last_header_index[1]
                i1 = lines[start][4]
                i2 = lines[end - 1][4]
            else:
                last_index = last_header_index[0]
                i1 = lines[start][1]
                i2 = lines[end - 1][1]
        except IndexError:
            raise StopIteration

        for i in xrange(last_index, len(possible_functions)):
            linenum, line = possible_functions[i]
            linenum += 1

            if linenum > i2:
                break
            elif linenum >= i1:
                last_index = i
                yield (linenum, line)

        if is_modified_file:
            last_header_index[1] = last_index
        else:
            last_header_index[0] = last_index

    def apply_pygments(data, filename):
        # XXX Guessing is preferable but really slow, especially on XML
        #     files.
        #if filename.endswith(".xml"):
        lexer = get_lexer_for_filename(filename, stripnl=False,
                                       encoding='utf-8')
        #else:
        #    lexer = guess_lexer_for_filename(filename, data, stripnl=False)

        try:
            # This is only available in 0.7 and higher
            lexer.add_filter('codetagify')
        except AttributeError:
            pass

        return pygments.highlight(data, lexer, NoWrapperHtmlFormatter()).splitlines()


    # There are three ways this function is called:
    #
    #     1) filediff, no interfilediff
    #        - Returns chunks for a single filediff. This is the usual way
    #          people look at diffs in the diff viewer.
    #
    #          In this mode, we get the original file based on the filediff
    #          and then patch it to get the resulting file.
    #
    #          This is also used for interdiffs where the source revision
    #          has no equivalent modified file but the interdiff revision
    #          does. It's no different than a standard diff.
    #
    #     2) filediff, interfilediff
    #        - Returns chunks showing the changes between a source filediff
    #          and the interdiff.
    #
    #          This is the typical mode used when showing the changes
    #          between two diffs. It requires that the file is included in
    #          both revisions of a diffset.
    #
    #     3) filediff, no interfilediff, force_interdiff
    #        - Returns chunks showing the changes between a source
    #          diff and an unmodified version of the diff.
    #
    #          This is used when the source revision in the diffset contains
    #          modifications to a file which have then been reverted in the
    #          interdiff revision. We don't actually have an interfilediff
    #          in this case, so we have to indicate that we are indeed in
    #          interdiff mode so that we can special-case this and not
    #          grab a patched file for the interdiff version.

    assert filediff

    file = filediff.source_file

    old = get_original_file(filediff)
    new = get_patched_file(old, filediff)

    if interfilediff:
        old = new
        interdiff_orig = get_original_file(interfilediff)
        new = get_patched_file(interdiff_orig, interfilediff)
    elif force_interdiff:
        # Basically, revert the change.
        old, new = new, old

    encoding = diffset.repository.encoding or 'iso-8859-15'
    old = convert_to_utf8(old, encoding)
    new = convert_to_utf8(new, encoding)

    # Normalize the input so that if there isn't a trailing newline, we add
    # it.
    if old and old[-1] != '\n':
        old += '\n'

    if new and new[-1] != '\n':
        new += '\n'

    a = NEWLINES_RE.split(old or '')
    b = NEWLINES_RE.split(new or '')

    # Remove the trailing newline, now that we've split this. This will
    # prevent a duplicate line number at the end of the diff.
    del(a[-1])
    del(b[-1])

    a_num_lines = len(a)
    b_num_lines = len(b)

    markup_a = markup_b = None

    siteconfig = SiteConfiguration.objects.get_current()

    threshold = siteconfig.get('diffviewer_syntax_highlighting_threshold')

    if threshold and (a_num_lines > threshold or b_num_lines > threshold):
        enable_syntax_highlighting = False

    if enable_syntax_highlighting:
        # Very long files, especially XML files, can take a long time to
        # highlight. For files over a certain size, don't highlight them.
        if (len(old) > STYLED_MAX_LIMIT_BYTES or
            len(new) > STYLED_MAX_LIMIT_BYTES):
            enable_syntax_highlighting = False

    if enable_syntax_highlighting:
        # Don't style the file if we have any *really* long lines.
        # It's likely a minified file or data or something that doesn't
        # need styling, and it will just grind Review Board to a halt.
        for lines in (a, b):
            for line in lines:
                if len(line) > STYLED_MAX_LINE_LEN:
                    enable_syntax_highlighting = False
                    break

            if not enable_syntax_highlighting:
                break

    if enable_syntax_highlighting:
        repository = filediff.diffset.repository
        tool = repository.get_scmtool()
        source_file = tool.normalize_path_for_display(filediff.source_file)
        dest_file = tool.normalize_path_for_display(filediff.dest_file)
        try:
            # TODO: Try to figure out the right lexer for these files
            #       once instead of twice.
            markup_a = apply_pygments(old or '', source_file)
            markup_b = apply_pygments(new or '', dest_file)
        except:
            pass

    if not markup_a:
        markup_a = NEWLINES_RE.split(escape(old))

    if not markup_b:
        markup_b = NEWLINES_RE.split(escape(new))

    linenum = 1
    last_header = [None, None]
    last_header_index = [0, 0]

    ignore_space = True
    for pattern in siteconfig.get("diffviewer_include_space_patterns"):
        if fnmatch.fnmatch(file, pattern):
            ignore_space = False
            break

    differ = Differ(a, b, ignore_space=ignore_space,
                    compat_version=diffset.diffcompat)

    # Register any regexes for interesting lines we may want to show.
    register_interesting_lines_for_filename(differ, file)

    # TODO: Make this back into a preference if people really want it.
    context_num_lines = siteconfig.get("diffviewer_context_num_lines")
    collapse_threshold = 2 * context_num_lines + 3

    if interfilediff:
        log_timer = log_timed(
            "Generating diff chunks for interdiff ids %s-%s (%s)" %
            (filediff.id, interfilediff.id, filediff.source_file))
    else:
        log_timer = log_timed(
            "Generating diff chunks for filediff id %s (%s)" %
            (filediff.id, filediff.source_file))

    chunk_index = 0

    for tag, i1, i2, j1, j2, meta in opcodes_with_metadata(differ):
        oldlines = markup_a[i1:i2]
        newlines = markup_b[j1:j2]
        numlines = max(len(oldlines), len(newlines))

        lines = map(diff_line,
                    xrange(linenum, linenum + numlines),
                    xrange(i1 + 1, i2 + 1), xrange(j1 + 1, j2 + 1),
                    a[i1:i2], b[j1:j2], oldlines, newlines)

        if tag == 'equal' and numlines > collapse_threshold:
            last_range_start = numlines - context_num_lines

            if linenum == 1:
                yield new_chunk(chunk_index, lines, 0, last_range_start, True)
                chunk_index += 1

                yield new_chunk(chunk_index, lines, last_range_start, numlines)
                chunk_index += 1
            else:
                yield new_chunk(chunk_index, lines, 0, context_num_lines)
                chunk_index += 1

                if i2 == a_num_lines and j2 == b_num_lines:
                    yield new_chunk(chunk_index, lines, context_num_lines,
                                    numlines, True)
                    chunk_index += 1
                else:
                    yield new_chunk(chunk_index, lines, context_num_lines,
                                    last_range_start, True)
                    chunk_index += 1

                    yield new_chunk(chunk_index, lines, last_range_start,
                                    numlines)
                    chunk_index += 1
        else:
            yield new_chunk(chunk_index, lines, 0, numlines, False, tag, meta)
            chunk_index += 1

        linenum += numlines

    log_timer.done()


def is_valid_move_range(lines):
    """Determines if a move range is valid and should be included.

    This performs some tests to try to eliminate trivial changes that
    shouldn't have moves associated.

    Specifically, a move range is valid if it has at least one line
    with alpha-numeric characters and is at least 4 characters long when
    stripped.
    """
    for line in lines:
        line = line.strip()

        if len(line) >= 4 and ALPHANUM_RE.search(line):
            return True

    return False


def opcodes_with_metadata(differ):
    """Returns opcodes from the differ with extra metadata.

    This is a wrapper around a differ's get_opcodes function, which returns
    extra metadata along with each range. That metadata includes information
    on moved blocks of code and whitespace-only lines.

    This returns a list of opcodes as tuples in the form of
    (tag, i1, i2, j1, j2, meta).
    """
    groups = []
    removes = {}
    inserts = []

    for tag, i1, i2, j1, j2 in differ.get_opcodes():
        meta = {
            # True if this chunk is only whitespace.
            "whitespace_chunk": False,

            # List of tuples (x,y), with whitespace changes.
            "whitespace_lines": [],
        }

        if tag == 'replace':
            # replace groups are good for whitespace only changes.
            assert (i2 - i1) == (j2 - j1)

            for i, j in zip(xrange(i1, i2), xrange(j1, j2)):
                if (WHITESPACE_RE.sub("", differ.a[i]) ==
                    WHITESPACE_RE.sub("", differ.b[j])):
                    # Both original lines are equal when removing all
                    # whitespace, so include their original line number in
                    # the meta dict.
                    meta["whitespace_lines"].append((i + 1, j + 1))

            # If all lines are considered to have only whitespace change,
            # the whole chunk is considered a whitespace-only chunk.
            if len(meta["whitespace_lines"]) == (i2 - i1):
                meta["whitespace_chunk"] = True

        group = (tag, i1, i2, j1, j2, meta)
        groups.append(group)

        # Store delete/insert ranges for later lookup. We will be building
        # keys that in most cases will be unique for the particular block
        # of text being inserted/deleted. There is a chance of collision,
        # so we store a list of matching groups under that key.
        #
        # Later, we will loop through the keys and attempt to find insert
        # keys/groups that match remove keys/groups.
        if tag == 'delete':
            for i in xrange(i1, i2):
                line = differ.a[i].strip()

                if line:
                    removes.setdefault(line, []).append((i, group))
        elif tag == 'insert':
            inserts.append(group)

    # We now need to figure out all the moved locations.
    #
    # At this point, we know all the inserted groups, and all the individually
    # deleted lines. We'll be going through and finding consecutive groups
    # of matching inserts/deletes that represent a move block.
    #
    # The algorithm will be documented as we go in the code.
    #
    # We start by looping through all the inserted groups.
    for itag, ii1, ii2, ij1, ij2, imeta in inserts:
        # Store some state on the range we'll be working with inside this
        # insert group.
        #
        # i_move_cur is the current location inside the insert group
        # (from ij1 through ij2).
        #
        # i_move_range is the current range of consecutive lines that we'll
        # use for a move. Each line in this range has a corresponding
        # consecutive delete line.
        #
        # r_move_ranges represents deleted move ranges. The key is a
        # string in the form of "{i1}-{i2}-{j1}-{j2}", with those positions
        # taken from the remove group for the line. The value
        # is an array of tuples of (r_start, r_end, r_group). These values
        # are used to quickly locate deleted lines we've found that match
        # the inserted lines, so we can assemble ranges later.
        i_move_cur = ij1
        i_move_range = (i_move_cur, i_move_cur)
        r_move_ranges = {} # key -> [(start, end, group)]

        # Loop through every location from ij1 through ij2 until we've
        # reached the end.
        while i_move_cur <= ij2:
            try:
                iline = differ.b[i_move_cur].strip()
            except IndexError:
                iline = None

            if iline is not None and iline in removes:
                # The inserted line at this location has a corresponding
                # removed line.
                #
                # If there's already some information on removed line ranges
                # for this particular move block we're processing then we'll
                # update the range.
                #
                # The way we do that is to find each removed line that
                # matches this inserted line, and for each of those find
                # out if there's an existing move range that the found
                # removed line immediately follows. If there is, we update
                # the existing range.
                #
                # If there isn't any move information for this line, we'll
                # simply add it to the move ranges.
                for ri, rgroup in removes.get(iline, []):
                    key = "%s-%s-%s-%s" % rgroup[1:5]

                    if r_move_ranges:
                        for i, r_move_range in \
                            enumerate(r_move_ranges.get(key, [])):
                            # If the remove information for the line is next in
                            # the sequence for this calculated move range...
                            if ri == r_move_range[1] + 1:
                                r_move_ranges[key][i] = (r_move_range[0], ri,
                                                         rgroup)
                                break
                    else:
                        # We don't have any move ranges yet, so it's time to
                        # build one based on any removed lines we find that
                        # match the inserted line.
                        r_move_ranges[key] = [(ri, ri, rgroup)]

                # On to the next line in the sequence...
                i_move_cur += 1
            else:
                # We've reached the very end of the insert group. See if
                # we have anything that looks like a move.
                if r_move_ranges:
                    r_move_range = None

                    # Go through every range of lines we've found and
                    # find the longest.
                    #
                    # The longest move range wins. If we find two ranges that
                    # are equal, though, we'll ignore both. The idea is that
                    # if we have two identical moves, then it's probably
                    # common enough code that we don't want to show the move.
                    # An example might be some standard part of a comment
                    # block, with no real changes in content.
                    #
                    # Note that with the current approach, finding duplicate
                    # moves doesn't cause us to reset the winning range
                    # to the second-highest identical match. We may want to
                    # do that down the road, but it means additional state,
                    # and this is hopefully uncommon enough to not be a real
                    # problem.
                    for ranges in r_move_ranges.itervalues():
                        for r1, r2, rgroup in ranges:
                            if not r_move_range:
                                r_move_range = (r1, r2, rgroup)
                            else:
                                len1 = r_move_range[2] - r_move_range[1]
                                len2 = r2 - r1

                                if len1 < len2:
                                    r_move_range = (r1, r2, rgroup)
                                elif len1 == len2:
                                    # If there are two that are the same, it
                                    # may be common code that we don't want to
                                    # see moves for. Comments, for example.
                                    r_move_range = None

                    # If we have a move range, see if it's one we want to
                    # include or filter out. Some moves are not impressive
                    # enough to display. For example, a small portion of a
                    # comment, or whitespace-only changes.
                    if (r_move_range and
                        is_valid_move_range(
                            differ.a[r_move_range[0]:r_move_range[1]])):

                        # Rebuild the insert and remove ranges based on
                        # where we are now and which range we won.
                        #
                        # The new ranges will be actual lists of positions,
                        # rather than a beginning and end. These will be
                        # provided to the renderer.
                        #
                        # The ranges expected by the renderers are 1-based,
                        # whereas our calculations for this algorithm are
                        # 0-based, so we add 1 to the numbers.
                        #
                        # The upper boundaries passed to the range() function
                        # must actually be one higher than the value we want.
                        # So, for r_move_range, we actually increment by 2.
                        # We only increment i_move_cur by one, because
                        # i_move_cur already factored in the + 1 by being
                        # at the end of the while loop.
                        i_move_range = range(i_move_range[0] + 1,
                                             i_move_cur + 1)
                        r_move_range = range(r_move_range[0] + 1,
                                             r_move_range[1] + 2)

                        rmeta = rgroup[-1]
                        rmeta.setdefault('moved', {}).update(
                            dict(zip(r_move_range, i_move_range)))
                        imeta.setdefault('moved', {}).update(
                            dict(zip(i_move_range, r_move_range)))

                # Reset the state for the next range.
                i_move_cur += 1
                i_move_range = (i_move_cur, i_move_cur)
                r_move_ranges = {}

    return groups


def get_revision_str(revision):
    if revision == HEAD:
        return "HEAD"
    elif revision == PRE_CREATION:
        return ""
    else:
        return "Revision %s" % revision


def get_diff_files(diffset, filediff=None, interdiffset=None):
    """Generates a list of files that will be displayed in a diff.

    This will go through the given diffset/interdiffset, or a given filediff
    within that diffset, and generate the list of files that will be
    displayed. This file list will contain a bunch of metadata on the files,
    such as the index, original/modified names, revisions, associated
    filediffs/diffsets, and so on.

    This can be used along with populate_diff_chunks to build a full list
    containing all diff chunks used for rendering a side-by-side diff.
    """
    if filediff:
        filediffs = [filediff]

        if interdiffset:
            log_timer = log_timed("Generating diff file info for "
                                  "interdiffset ids %s-%s, filediff %s" %
                                  (diffset.id, interdiffset.id, filediff.id))
        else:
            log_timer = log_timed("Generating diff file info for "
                                  "diffset id %s, filediff %s" %
                                  (diffset.id, filediff.id))
    else:
        filediffs = diffset.files.select_related().all()

        if interdiffset:
            log_timer = log_timed("Generating diff file info for "
                                  "interdiffset ids %s-%s" %
                                  (diffset.id, interdiffset.id))
        else:
            log_timer = log_timed("Generating diff file info for "
                                  "diffset id %s" % diffset.id)


    # A map used to quickly look up the equivalent interfilediff given a
    # source file.
    interdiff_map = {}
    if interdiffset:
        for interfilediff in interdiffset.files.all():
            if not filediff or \
               filediff.source_file == interfilediff.source_file:
                interdiff_map[interfilediff.source_file] = interfilediff


    # In order to support interdiffs properly, we need to display diffs
    # on every file in the union of both diffsets. Iterating over one diffset
    # or the other doesn't suffice.
    #
    # We build a list of parts containing the source filediff, the interdiff
    # filediff (if specified), and whether to force showing an interdiff
    # (in the case where a file existed in the source filediff but was
    # reverted in the interdiff).
    filediff_parts = []

    for filediff in filediffs:
        interfilediff = None

        if filediff.source_file in interdiff_map:
            interfilediff = interdiff_map[filediff.source_file]
            del(interdiff_map[filediff.source_file])

        filediff_parts.append((filediff, interfilediff, interdiffset != None))


    if interdiffset:
        # We've removed everything in the map that we've already found.
        # What's left are interdiff files that are new. They have no file
        # to diff against.
        #
        # The end result is going to be a view that's the same as when you're
        # viewing a standard diff. As such, we can pretend the interdiff is
        # the source filediff and not specify an interdiff. Keeps things
        # simple, code-wise, since we really have no need to special-case
        # this.
        filediff_parts += [(interdiff, None, False)
                           for interdiff in interdiff_map.values()]


    files = []

    for parts in filediff_parts:
        filediff, interfilediff, force_interdiff = parts

        newfile = (filediff.source_revision == PRE_CREATION)

        if interdiffset:
            # First, find out if we want to even process this one.
            # We only process if there's a difference in files.

            if (filediff and interfilediff and
                filediff.diff == interfilediff.diff):
                continue

            source_revision = "Diff Revision %s" % diffset.revision

            if not interfilediff and force_interdiff:
                dest_revision = "Diff Revision %s - File Reverted" % \
                                interdiffset.revision
            else:
                dest_revision = "Diff Revision %s" % interdiffset.revision
        else:
            source_revision = get_revision_str(filediff.source_revision)

            if newfile:
                dest_revision = NEW_FILE_STR
            else:
                dest_revision = NEW_CHANGE_STR

        i = filediff.source_file.rfind('/')

        if i != -1:
            basepath = filediff.source_file[:i]
            basename = filediff.source_file[i + 1:]
        else:
            basepath = ""
            basename = filediff.source_file

        tool = filediff.diffset.repository.get_scmtool()
        depot_filename = tool.normalize_path_for_display(filediff.source_file)
        dest_filename = tool.normalize_path_for_display(filediff.dest_file)

        files.append({
            'depot_filename': depot_filename,
            'dest_filename': dest_filename or depot_filename,
            'basename': basename,
            'basepath': basepath,
            'revision': source_revision,
            'dest_revision': dest_revision,
            'filediff': filediff,
            'interfilediff': interfilediff,
            'force_interdiff': force_interdiff,
            'binary': filediff.binary,
            'deleted': filediff.deleted,
            'moved': filediff.moved,
            'newfile': newfile,
            'index': len(files),
            'chunks_loaded': False,
        })

    def cmp_file(x, y):
        # Sort based on basepath in asc order
        if x["basepath"] != y["basepath"]:
            return cmp(x["basepath"], y["basepath"])

        # Sort based on filename in asc order, then based on extension in desc
        # order, to make *.h be ahead of *.c/cpp
        x_file, x_ext = os.path.splitext(x["basename"])
        y_file, y_ext = os.path.splitext(y["basename"])
        if x_file != y_file:
            return cmp(x_file, y_file)
        else:
            return cmp(y_ext, x_ext)

    files.sort(cmp_file)

    log_timer.done()

    return files


def populate_diff_chunks(files, enable_syntax_highlighting=True):
    """Populates a list of diff files with chunk data.

    This accepts a list of files (generated by get_diff_files) and generates
    diff chunk data for each file in the list. The chunk data is stored in
    the file state.
    """
    key_prefix = "diff-sidebyside-"

    if enable_syntax_highlighting:
        key_prefix += "hl-"

    for file in files:
        filediff = file['filediff']
        interfilediff = file['interfilediff']
        force_interdiff = file['force_interdiff']
        chunks = []

        # If the file is binary or deleted, don't get chunks. Also don't
        # get chunks if there is no source_revision, which occurs if a
        # file has moved and has no changes.
        if (not filediff.binary and not filediff.deleted and
            filediff.source_revision != ''):
            key = key_prefix

            if not force_interdiff:
                key += str(filediff.pk)
            elif interfilediff:
                key += "interdiff-%s-%s" % (filediff.pk, interfilediff.pk)
            else:
                key += "interdiff-%s-none" % filediff.pk

            chunks = cache_memoize(
                key,
                lambda: list(get_chunks(filediff.diffset,
                                        filediff, interfilediff,
                                        force_interdiff,
                                        enable_syntax_highlighting)),
                large_data=True)

        file.update({
            'chunks': chunks,
            'num_chunks': len(chunks),
            'changed_chunk_indexes': [],
            'whitespace_only': True,
        })

        for j, chunk in enumerate(chunks):
            chunk['index'] = j

            if chunk['change'] != 'equal':
                file['changed_chunk_indexes'].append(j)
                meta = chunk.get('meta', {})

                if not meta.get('whitespace_chunk', False):
                    file['whitespace_only'] = False

        file.update({
            'num_changes': len(file['changed_chunk_indexes']),
            'chunks_loaded': True,
        })


def get_file_chunks_in_range(context, filediff, interfilediff,
                             first_line, num_lines):
    """
    A generator that yields chunks within a range of lines in the specified
    filediff/interfilediff.

    This is primarily intended for use with templates. It takes a
    RequestContext for looking up the user and for caching file lists,
    in order to improve performance and reduce lookup times for files that have
    already been fetched.

    Each returned chunk is a dictionary with the following fields:

      ============= ========================================================
      Variable      Description
      ============= ========================================================
      ``change``    The change type ("equal", "replace", "insert", "delete")
      ``numlines``  The number of lines in the chunk.
      ``lines``     The list of lines in the chunk.
      ``meta``      A dictionary containing metadata on the chunk
      ============= ========================================================


    Each line in the list of lines is an array with the following data:

      ======== =============================================================
      Index    Description
      ======== =============================================================
      0        Virtual line number (union of the original and patched files)
      1        Real line number in the original file
      2        HTML markup of the original file
      3        Changed regions of the original line (for "replace" chunks)
      4        Real line number in the patched file
      5        HTML markup of the patched file
      6        Changed regions of the patched line (for "replace" chunks)
      7        True if line consists of only whitespace changes
      ======== =============================================================
    """
    def find_header(headers):
        for header in reversed(headers):
            if header[0] < first_line:
                return {
                    'line': header[0],
                    'text': header[1],
                }

    interdiffset = None

    key = "_diff_files_%s_%s" % (filediff.diffset.id, filediff.id)

    if interfilediff:
        key += "_%s" % (interfilediff.id)
        interdiffset = interfilediff.diffset

    if key in context:
        files = context[key]
    else:
        assert 'user' in context
        files = get_diff_files(filediff.diffset, filediff, interdiffset)
        populate_diff_chunks(files, get_enable_highlighting(context['user']))
        context[key] = files

    if not files:
        raise StopIteration

    assert len(files) == 1
    last_header = [None, None]

    for chunk in files[0]['chunks']:
        if ('headers' in chunk['meta'] and
            (chunk['meta']['headers'][0] or chunk['meta']['headers'][1])):
            last_header = chunk['meta']['headers']

        lines = chunk['lines']

        if lines[-1][0] >= first_line >= lines[0][0]:
            start_index = first_line - lines[0][0]

            if first_line + num_lines <= lines[-1][0]:
                last_index = start_index + num_lines
            else:
                last_index = len(lines)

            new_chunk = {
                'lines': chunk['lines'][start_index:last_index],
                'numlines': last_index - start_index,
                'change': chunk['change'],
                'meta': chunk.get('meta', {}),
            }

            if 'left_headers' in chunk['meta']:
                left_header = find_header(chunk['meta']['left_headers'])
                right_header = find_header(chunk['meta']['right_headers'])
                del new_chunk['meta']['left_headers']
                del new_chunk['meta']['right_headers']

                if left_header or right_header:
                    header = (left_header, right_header)
                else:
                    header = last_header

                new_chunk['meta']['headers'] = header

            yield new_chunk

            first_line += new_chunk['numlines']
            num_lines -= new_chunk['numlines']

            assert num_lines >= 0
            if num_lines == 0:
                break


def get_enable_highlighting(user):
    user_syntax_highlighting = True

    if user.is_authenticated():
        try:
            profile = user.get_profile()
            user_syntax_highlighting = profile.syntax_highlighting
        except Profile.DoesNotExist:
            pass

    siteconfig = SiteConfiguration.objects.get_current()
    return (siteconfig.get('diffviewer_syntax_highlighting') and
            user_syntax_highlighting and
            get_can_enable_syntax_highlighting())
