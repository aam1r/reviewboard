import markdown
import StringIO

from reviewboard.reviews.ui.base import ReviewUI


class MarkdownReviewUI(FileAttachmentReviewUI):
    supported_mimetypes = ['text/x-markdown']
    template_name = 'reviews/ui/markdown.html'
    object_key = 'markdown'

    def render(self):
        new_lines = ['\r\n', '\r', '\n']
        buffer = StringIO.StringIO()
        file = list(self.review_request.get_file_attachments())[0].file

        markdown.markdownFromFile(input=file, output=buffer)
        rendered = buffer.getvalue()
        buffer.close()

        for x in new_lines:
            rendered = rendered.replace(x, '')

        return rendered
