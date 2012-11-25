import markdown
import StringIO

from reviewboard.reviews.ui.base import FileAttachmentReviewUI


class MarkdownReviewUI(FileAttachmentReviewUI):
    allow_inline = True
    object_key = 'markdown'
    supported_mimetypes = ['text/x-markdown']
    template_name = 'reviews/ui/markdown.html'

    def render(self):
        buffer = StringIO.StringIO()

        markdown.markdownFromFile(input=self.obj.file, output=buffer)
        rendered = buffer.getvalue()
        buffer.close()

        return rendered
