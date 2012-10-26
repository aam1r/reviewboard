from reviewboard.reviews.ui.base import ReviewUI
from reviewboard.reviews.models import Markdown


class MarkdownReviewUI(ReviewUI):
    model = Markdown
    comment_model = None
    template_name = 'reviews/ui/markdown.html'
    object_key = 'markdown'
