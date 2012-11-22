import markdown
import StringIO

from django.conf.urls.defaults import patterns, url

from reviewboard.reviews.ui.base import FileAttachmentReviewUI


class MarkdownReviewUI(FileAttachmentReviewUI):
    allow_inline = True
    object_key = 'markdown'
    supported_mimetypes = ['text/x-markdown']
    template_name = 'reviews/ui/markdown.html'
    urlpatterns = patterns('',
        (r'^(?P<review_request_id>[0-9]+)/file/(?P<file_attachment_id>[0-9]+)/rendered/$',
        'reviewboard.reviews.views.rendered_attachment'),
    )

    def render(self):
        buffer = StringIO.StringIO()

        markdown.markdownFromFile(input=self.obj.file, output=buffer)
        rendered = buffer.getvalue()
        buffer.close()

        return rendered
