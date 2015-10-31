import os
import sys
import argparse
import csv
import errno
import re
import shutil
import subprocess


def create_missing_directories_if_necessary(path):
    """
    Mimics the command 'mkdir -p'.
    """
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def replace_image_fields_with_image_tags(string):
    """
    Recursively finds all {{image:size}} fields and returns a string replaced
    with HTML compliant <img> tags.
    """
    for match in re.finditer('{{(.*?)}}', string, re.DOTALL):
        image_path = match.group(1)

        if len(image_path) > 0:
            # determine whether a size has been explicitly specified; e.g.
            # images/name-of-image.svg:16x16
            size_index = image_path.rfind(':')

            explicit_width = None
            explicit_height = None

            if size_index is not -1:
                size = image_path[size_index + 1:]
                size = size.split('x')

                if len(size) > 1:
                    explicit_width = int(size[0])
                    explicit_height = int(size[1])

                    if explicit_width < 0:
                        explicit_width = None

                    if explicit_height < 0:
                        explicit_height = None

                if (explicit_width is not None and
                   explicit_height is not None):
                        image_tag = '<img src="{0}" width="{1}" height="{2}">'
                        image_tag = image_tag.format(image_path[:size_index],
                                                     explicit_width,
                                                     explicit_height)
            else:
                image_tag = '<img src="{0}">'.format(image_path)

            string = string[:match.start()] + image_tag + string[match.end():]

            # since the string we're finding matches on has just been changed,
            # we have to recursively look for more fields if there are any
            string = replace_image_fields_with_image_tags(string)

            break

    return string


def content_from_template(data, template):
    """
    Returns the contents of the template with all template fields replaced by
    any matching fields in the provided data.
    """
    content = template

    for field in data:
        # ignore special variable columns
        if not field.startswith('@'):
            field_value = str(data[field])
            # replace any special image fields with html compliant <img> tags
            field_value = replace_image_fields_with_image_tags(field_value)

            # template fields are always represented by wrapping {{ }}'s'
            template_field = re.escape('{{%s}}' % str(field))

            # find any occurences of the field, using a case-insensitive
            # comparison, to ensure that e.g. {{name}} is populated with the
            # value from column "Name", even though the casing might differ
            search = re.compile(template_field, re.IGNORECASE)

            # finally populate any found occurences of the template field with
            # the resulting value from the data
            content = search.sub(field_value, content)

    return content


def colorize_help_description(help_description, required):
    apply_red_color = '\x1B[31m'
    apply_yellow_color = '\x1B[33m'
    apply_normal_color = '\033[0m'

    if required:
        help_description = apply_red_color + help_description
    else:
        help_description = apply_yellow_color + help_description

    return help_description + apply_normal_color


def colorize_warning(warning):
    apply_yellow_color = '\x1B[33m'
    apply_normal_color = '\033[0m'

    return apply_yellow_color + warning + apply_normal_color


def colorize_error(error):
    apply_red_color = '\x1B[31m'
    apply_normal_color = '\033[0m'

    return apply_red_color + error + apply_normal_color


def main(argv):
    parser = argparse.ArgumentParser(
        description='Generate printable sheets of cards.')

    parser.add_argument('-f', '--filename', dest='filename', type=str,
                        required=True,
                        help=colorize_help_description(
                            'A path to a CSV file containing card data',
                            required=True))

    parser.add_argument('-t', '--template', dest='template', type=str,
                        required=False,
                        help=colorize_help_description(
                            'A path to a card template',
                            required=False))

    parser.add_argument('--title', dest='title', type=str,
                        required=False,
                        help=colorize_help_description(
                            'The title of the generated cards',
                            required=False))

    parser.add_argument('--description', dest='description', type=str,
                        required=False, default='Pages generated by cards.py',
                        help=colorize_help_description(
                            'The description of the generated cards',
                            required=False))

    parser.add_argument('--version-identifier', dest='version_identifier',
                        required=False, default='', type=str,
                        help=colorize_help_description(
                            'A version identifier that is put on'
                            ' each generated card. Requires that the template'
                            ' provides a {{version}} field.',
                            required=False))

    parser.add_argument('--disable-cut-guides', dest='disable_cut_guides',
                        required=False, default=False, action='store_true',
                        help=colorize_help_description(
                            'Disable cut guides on the margins of the '
                            'generated pages',
                            required=False))

    parser.add_argument('--verbose', dest='verbose',
                        required=False, default=False, action='store_true',
                        help=colorize_help_description(
                            'Show more information',
                            required=False))

    args = vars(parser.parse_args())

    # required arguments
    data_path = args['filename']

    # optional arguments
    default_template_path = args['template']
    title = args['title']
    description = args['description']
    version_identifier = args['version_identifier']
    disable_cut_guides = bool(args['disable_cut_guides'])
    is_verbose = bool(args['verbose'])

    with open(data_path) as f:
        data = csv.DictReader(f)

        if (default_template_path is not None and
           len(default_template_path) > 0):
            with open(default_template_path) as t:
                default_template = t.read().strip()

            if is_verbose and len(default_template) == 0:
                print(colorize_warning(
                    '[!] The provided template appears to be empty. '
                    'Blank cards may occur.'))
        else:
            default_template = None

            if is_verbose:
                print(colorize_warning(
                    '[!] A default template was not provided. '
                    'Blank cards may occur.'))

        with open('template/page.html') as p:
            page = p.read()

            if disable_cut_guides:
                cut_guides_display = 'style="display: none"'
            else:
                cut_guides_display = 'style="display: block"'

            page = page.replace('{{cut_guides_style}}', cut_guides_display)

        with open('template/card.html') as c:
            card = c.read()

        with open('template/index.html') as i:
            index = i.read()

        cards = ''
        pages = ''

        cards_on_page = 0
        cards_on_all_pages = 0

        max_cards_per_page = 9

        pages_total = 0

        for row in data:
            # determine how many instances of this card to generate (defaults
            # to a single instance if not specified)
            count = int(row.get('@count', 1))

            if count < 0:
                # if a negative count is specified, treat it as none
                count = 0

            for i in range(count):
                # determine which template to use for this card (defaults to
                # the template specified from the --template option)
                template_path = row.get('@template', default_template_path)
                template = None

                if (template_path is not default_template_path and
                   len(template_path) > 0):
                    if not os.path.isabs(template_path):
                        # if the template path is not an absolute path, assume
                        # that it's located relative to where the data is
                        template_path = os.path.join(
                            os.path.dirname(data_path),
                            template_path)

                    try:
                        with open(template_path) as t:
                            template = t.read().strip()
                    except IOError:
                        if is_verbose:
                            print(colorize_error(
                                '[!] A card provided a template that could not'
                                ' be opened: \'{0}\''.format(template_path)))
                else:
                    # if the template path points to the same template as
                    # provided throuh --template, we already have it available
                    template = default_template

                if template is not None:
                    card_content = content_from_template(row, template)
                    card_content = card_content.replace(
                        '{{card_index}}', str(cards_on_all_pages + 1))
                    card_content = card_content.replace(
                        '{{version}}', version_identifier)
                else:
                    card_content = """
                                   <b>Error</b>: a template was not provided
                                   for this card.<br /><br />

                                   Provide one using the <b>--template</b>
                                   argument, or through a <b>@template</b>
                                   column.
                                   """

                cards += card.replace(
                    '{{content}}', card_content)

                cards_on_page += 1
                cards_on_all_pages += 1

                if cards_on_page == max_cards_per_page:
                    pages += page.replace('{{cards}}', cards)

                    pages_total += 1

                    cards_on_page = 0
                    cards = ''

        if cards_on_page > 0:
            pages += page.replace('{{cards}}', cards)

            pages_total += 1

        create_missing_directories_if_necessary('generated')

        pages_or_page = 'pages' if pages_total > 1 else 'page'
        cards_or_card = 'cards' if cards_on_all_pages > 1 else 'card'

        with open('generated/index.html', 'w') as result:
            if not title or len(title) == 0:
                title = 'cards.py: {0} {1} on {2} {3}'.format(
                    cards_on_all_pages, cards_or_card,
                    pages_total, pages_or_page)

            pages = pages.replace('{{cards_total}}', str(cards_on_all_pages))

            index = index.replace('{{title}}', title)
            index = index.replace('{{description}}', description)
            index = index.replace('{{pages}}', pages)

            generated_path = os.path.abspath(result.name)

            result.write(index)

        shutil.copyfile('template/index.css', 'generated/index.css')

        print('Generated {0} {1} on {2} {3}. See \'generated/index.html\'.'
              .format(cards_on_all_pages, cards_or_card,
                      pages_total, pages_or_page))

        if sys.platform.startswith('darwin'):
            subprocess.call(('open', generated_path))
        elif os.name == 'nt':
            subprocess.call(('start', generated_path), shell=True)
        elif os.name == 'posix':
            subprocess.call(('xdg-open', generated_path))

if __name__ == "__main__":
    main(sys.argv)
