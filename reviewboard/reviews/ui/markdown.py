from reviewboard.reviews.ui.base import ReviewUI


class MarkdownReviewUI(ReviewUI):
    model = None
    comment_model = None
    template_name = 'reviews/ui/markdown.html'
    object_key = 'markdown'
