import markdown
import StringIO

from django.conf.urls.defaults import patterns, url
from reviewboard.reviews.ui.base import FileAttachmentReviewUI


class MarkdownReviewUI(FileAttachmentReviewUI):
    object_key = 'markdown'
    supported_mimetypes = ['text/x-markdown']
    template_name = 'reviews/ui/markdown.html'
    urlpatterns = patterns('',
        url(r'^(?P<review_request_id>[0-9]+)/file/(?P<file_attachment_id>[0-9]+)/fetch$',
            'reviewboard.reviews.views.fetch_rendered_attachment',
            name='markdown-pluggable-fetch'),
        )

    def render(self):
        buffer = StringIO.StringIO()

        markdown.markdownFromFile(input=self.obj.file, output=buffer)
        rendered = buffer.getvalue()
        buffer.close()

        return rendered
