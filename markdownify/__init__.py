from bs4 import BeautifulSoup, NavigableString, Comment
import re
import six


convert_heading_re = re.compile(r'convert_h(\d+)')
line_beginning_re = re.compile(r'^', re.MULTILINE)
whitespace_re = re.compile(r'[\t ]+')
all_whitespace_re = re.compile(r'[\s]+')
html_heading_re = re.compile(r'h[1-6]')


# Heading styles
ATX = 'atx'
ATX_CLOSED = 'atx_closed'
UNDERLINED = 'underlined'
SETEXT = UNDERLINED

# Newline style
SPACES = 'spaces'
BACKSLASH = 'backslash'

# Strong and emphasis style
ASTERISK = '*'
UNDERSCORE = '_'


def escape(text):
    if not text:
        return ''
    return text.replace('_', r'\_')


def chomp(text):
    """
    If the text in an inline tag like b, a, or em contains a leading or trailing
    space, strip the string and return a space as suffix of prefix, if needed.
    This function is used to prevent conversions like
        <b> foo</b> => ** foo**
    """
    prefix = ' ' if text and text[0] == ' ' else ''
    suffix = ' ' if text and text[-1] == ' ' else ''
    text = text.strip()
    return (prefix, suffix, text)


def _todict(obj):
    return dict((k, getattr(obj, k)) for k in dir(obj) if not k.startswith('_'))


class MarkdownConverter(object):
    class DefaultOptions:
        strip = None
        convert = None
        autolinks = True
        heading_style = UNDERLINED
        bullets = '*+-'  # An iterable of bullet types.
        strong_em_symbol = ASTERISK
        newline_style = SPACES

    class Options(DefaultOptions):
        pass

    def __init__(self, **options):
        # Create an options dictionary. Use DefaultOptions as a base so that
        # it doesn't have to be extended.
        self.options = _todict(self.DefaultOptions)
        self.options.update(_todict(self.Options))
        self.options.update(options)
        if self.options['strip'] is not None and self.options['convert'] is not None:
            raise ValueError('You may specify either tags to strip or tags to'
                             ' convert, but not both.')

    def convert(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        return self.process_tag(soup, convert_as_inline=False, children_only=True)

    def process_tag(self, node, convert_as_inline, children_only=False):
        text = ''
        # markdown headings can't include block elements (elements w/newlines)
        isHeading = html_heading_re.match(node.name) is not None
        convert_children_as_inline = convert_as_inline

        if not children_only and isHeading:
            convert_children_as_inline = True

        # Remove whitespace-only textnodes in lists
        def is_list_node(el):
            return el and el.name in ['ol', 'ul', 'li']

        if is_list_node(node):
            for el in node.children:
                # Only extract (remove) whitespace-only text node if any of the conditions is true:
                # - el is the first element in its parent
                # - el is the last element in its parent
                # - el is adjacent to an list node
                can_extract = not el.previous_sibling or not el.next_sibling or is_list_node(el.previous_sibling) or is_list_node(el.next_sibling)
                if isinstance(el, NavigableString) and six.text_type(el).strip() == '' and can_extract:
                    el.extract()

        # Convert the children first
        for el in node.children:
            if isinstance(el, Comment):
                continue
            elif isinstance(el, NavigableString):
                text += self.process_text(el)
            else:
                text += self.process_tag(el, convert_children_as_inline)

        if not children_only:
            convert_fn = getattr(self, 'convert_%s' % node.name, None)
            if convert_fn and self.should_convert_tag(node.name):
                text = convert_fn(node, text, convert_as_inline)

        return text

    def process_text(self, el):
        text = six.text_type(el)
        # remove trailing whitespaces if any of the following condition is true:
        # - current text node is the last node in li
        # - current text node is followed by an embedded list
        if el.parent.name == 'li' and (not el.next_sibling or el.next_sibling.name in ['ul', 'ol']):
            return escape(all_whitespace_re.sub(' ', text or '')).rstrip()
        return escape(whitespace_re.sub(' ', text or ''))

    def __getattr__(self, attr):
        # Handle headings
        m = convert_heading_re.match(attr)
        if m:
            n = int(m.group(1))

            def convert_tag(el, text, convert_as_inline):
                return self.convert_hn(n, el, text, convert_as_inline)

            convert_tag.__name__ = 'convert_h%s' % n
            setattr(self, convert_tag.__name__, convert_tag)
            return convert_tag

        raise AttributeError(attr)

    def should_convert_tag(self, tag):
        tag = tag.lower()
        strip = self.options['strip']
        convert = self.options['convert']
        if strip is not None:
            return tag not in strip
        elif convert is not None:
            return tag in convert
        else:
            return True

    def indent(self, text, level):
        return line_beginning_re.sub('\t' * level, text) if text else ''

    def underline(self, text, pad_char):
        text = (text or '').rstrip()
        return '%s\n%s\n\n' % (text, pad_char * len(text)) if text else ''

    def convert_a(self, el, text, convert_as_inline):
        prefix, suffix, text = chomp(text)
        if not text:
            return ''
        if convert_as_inline:
            return text
        href = el.get('href')
        title = el.get('title')
        # For the replacement see #29: text nodes underscores are escaped
        if self.options['autolinks'] and text.replace(r'\_', '_') == href and not title:
            # Shortcut syntax
            return '<%s>' % href
        title_part = ' "%s"' % title.replace('"', r'\"') if title else ''
        return '%s[%s](%s%s)%s' % (prefix, text, href, title_part, suffix) if href else text

    def convert_b(self, el, text, convert_as_inline):
        return self.convert_strong(el, text, convert_as_inline)

    def convert_blockquote(self, el, text, convert_as_inline):

        if convert_as_inline:
            return text

        return '\n' + (line_beginning_re.sub('> ', text) + '\n\n') if text else ''

    def convert_br(self, el, text, convert_as_inline):
        if convert_as_inline:
            return ""

        if self.options['newline_style'].lower() == BACKSLASH:
            return '\\\n'
        else:
            return '  \n'

    def convert_em(self, el, text, convert_as_inline):
        em_tag = self.options['strong_em_symbol']
        prefix, suffix, text = chomp(text)
        if not text:
            return ''
        return '%s%s%s%s%s' % (prefix, em_tag, text, em_tag, suffix)

    def convert_hn(self, n, el, text, convert_as_inline):
        if convert_as_inline:
            return text

        style = self.options['heading_style'].lower()
        text = text.rstrip()
        if style == UNDERLINED and n <= 2:
            line = '=' if n == 1 else '-'
            return self.underline(text, line)
        hashes = '#' * n
        if style == ATX_CLOSED:
            return '%s %s %s\n\n' % (hashes, text, hashes)
        return '%s %s\n\n' % (hashes, text)

    def convert_i(self, el, text, convert_as_inline):
        return self.convert_em(el, text, convert_as_inline)

    def convert_list(self, el, text, convert_as_inline):

        # Converting a list to inline is undefined.
        # Ignoring convert_to_inline for list.

        nested = False
        before_paragraph = False
        if el.next_sibling and el.next_sibling.name not in ['ul', 'ol']:
            before_paragraph = True
        while el:
            if el.name == 'li':
                nested = True
                break
            el = el.parent
        if nested:
            # remove trailing newline if nested
            return '\n' + self.indent(text, 1).rstrip()
        return text + ('\n' if before_paragraph else '')

    convert_ul = convert_list
    convert_ol = convert_list

    def convert_li(self, el, text, convert_as_inline):
        parent = el.parent
        if parent is not None and parent.name == 'ol':
            if parent.get("start"):
                start = int(parent.get("start"))
            else:
                start = 1
            bullet = '%s.' % (start + parent.index(el))
        else:
            depth = -1
            while el:
                if el.name == 'ul':
                    depth += 1
                el = el.parent
            bullets = self.options['bullets']
            bullet = bullets[depth % len(bullets)]
        return '%s %s\n' % (bullet, text or '')

    def convert_p(self, el, text, convert_as_inline):
        if convert_as_inline:
            return text
        return '%s\n\n' % text if text else ''

    def convert_strong(self, el, text, convert_as_inline):
        strong_tag = 2 * self.options['strong_em_symbol']
        prefix, suffix, text = chomp(text)
        if not text:
            return ''
        return '%s%s%s%s%s' % (prefix, strong_tag, text, strong_tag, suffix)

    def convert_img(self, el, text, convert_as_inline):
        alt = el.attrs.get('alt', None) or ''
        src = el.attrs.get('src', None) or ''
        title = el.attrs.get('title', None) or ''
        title_part = ' "%s"' % title.replace('"', r'\"') if title else ''
        if convert_as_inline:
            return alt

        return '![%s](%s%s)' % (alt, src, title_part)

    def convert_table(self, el, text, convert_as_inline):
        rows = el.find_all('tr')
        text_data = []
        for row in rows:
            headers = row.find_all('th')
            columns = row.find_all('td')
            if len(headers) > 0:
                headers = [head.text.strip() for head in headers]
                text_data.append('| ' + ' | '.join(headers) + ' |')
                text_data.append('| ' + ' | '.join(['---'] * len(headers)) + ' |')
            elif len(columns) > 0:
                columns = [colm.text.strip() for colm in columns]
                text_data.append('| ' + ' | '.join(columns) + ' |')
            else:
                continue
        return '\n'.join(text_data)

    def convert_hr(self, el, text, convert_as_inline):
        return '\n\n---\n\n'

    def convert_figure(self, el, text, convert_as_inline):
        caption_node = el.find('figcaption')
        caption = caption_node.text if caption_node else ''

        img = el.find('img')
        if img:
            if not caption:
                caption = img.attrs.get('alt', '')

            if convert_as_inline:
                return caption

            src = img.attrs.get('src', '')
            return '![%s](%s)\n\n' % (caption, src)

        iframe = el.find('iframe')
        if iframe:
            src = iframe.attrs.get('src')
            return '<!-- %s -->\n\n' % src

        video = el.find('video')
        if video:
            src = video.attrs.get('src')
            return '<!-- upload-video: %s [%s] -->\n\n' % (src, caption)

        return ''

    def convert_pre(self, el, text, convert_as_inline):
        return '%s\n\n' % text


def markdownify(html, **options):
    return MarkdownConverter(**options).convert(html)
