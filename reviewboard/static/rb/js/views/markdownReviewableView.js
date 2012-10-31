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

    rendered: function() {
        return $('<div/>').html(this.model.get('rendered')).text();
    },

    /*
     * Renders the view.
     */
    renderContent: function() {
        return this;
    }
});
