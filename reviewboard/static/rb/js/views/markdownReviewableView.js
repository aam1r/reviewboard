/*
 * Displays a review UI for Markdown files.
 */
RB.MarkdownReviewableView = RB.AbstractReviewableView.extend({
    className: 'markdown-review-ui',

    /*
     * Renders the view.
     */
    renderContent: function() {
        this.$el.html(this.model.get('rendered'));

        return this;
    }
});
