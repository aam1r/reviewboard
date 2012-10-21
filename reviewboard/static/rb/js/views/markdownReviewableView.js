/*
 * Displays a review UI for Markdown files.
 */
RB.MarkdownReviewableView = RB.AbstractReviewableView.extend({
    className: 'markdown-review-ui',

    /*
     * Initializes the view.
     */
    initialize: function() {
        RB.AbstractReviewableView.prototype.initialize.call(this);
    },

    /*
     * Renders the view.
     */
    renderContent: function() {
        var self = this;
        return this;
    },
});
