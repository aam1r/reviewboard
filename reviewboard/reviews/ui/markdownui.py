import markdown
import StringIO

from reviewboard.reviews.ui.base import FileAttachmentReviewUI


class MarkdownReviewUI(FileAttachmentReviewUI):
    supported_mimetypes = ['text/x-markdown']
    template_name = 'reviews/ui/markdown.html'
    object_key = 'markdown'

    def render(self):
        buffer = StringIO.StringIO()

        markdown.markdownFromFile(input=self.obj.file, output=buffer)
        rendered = buffer.getvalue()
        buffer.close()

        return rendered
