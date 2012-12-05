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

    def serialize_comments(self, comments):
        result = {}

        for comment in comments:
            result.setdefault(comment.extra_data['child_id'], []).append(
                    self.serialize_comment(comment))

        return result
